"""HTEFS-S3 — explicit coverage ledger and incremental per-chunk commit.

Covers the targeted ``full_sync`` flow without any real browser, network, or
legacy access:

- ``EvolutionExtractionCoverage`` lean model (no pending/failed states; a
  missing row means coverage is not proven) and its migration;
- targeted planner that derives coverage ONLY from the explicit ledger (a
  lone ``ClinicalEvent`` never proves coverage) while the legacy no-target
  contract stays untouched;
- canonical chunking reuse (max 15 days, deterministic bounds) for planned
  gaps;
- per-chunk outer transaction around ``ingest_evolutions`` + idempotent
  coverage upsert + cumulative run counters — proven against the real test
  database after forced failures (no ``transaction.atomic`` mocks);
- retry that replans from the ledger and never re-extracts a fully covered
  chunk (only the canonical one-day boundary overlap);
- legacy no-``admission_id`` runs create no admission-specific coverage.

All identifiers and dates are clearly synthetic (``SYN-INC-*``).
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.extractors.errors import ExtractionTimeoutError
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient
from tests.unit.test_persistent_worker_command import _make_adapter_mock

_WORKER_MODULE = (
    "apps.ingestion.management.commands."
    "process_ingestion_runs_persistent_session"
)
_LEDGER_TABLE = "ingestion_evolutionextractioncoverage"


# ---------------------------------------------------------------------------
# Synthetic fixtures (no real data, no Playwright)
# ---------------------------------------------------------------------------


def _patient(key: str) -> Patient:
    return Patient.objects.create(
        source_system="tasy",
        patient_source_key=key,
        name=f"Synth Incremental Patient {key}",
    )


def _admission(
    patient: Patient,
    *,
    key: str,
    start: datetime.datetime,
    end: datetime.datetime | None = None,
) -> Admission:
    from django.utils import timezone as dj_timezone

    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=dj_timezone.make_aware(start),
        discharge_date=(
            dj_timezone.make_aware(end) if end is not None else None
        ),
    )


def _snapshot_row(key: str, start: str, end: str = "") -> dict[str, str]:
    row = {
        "admission_key": key,
        "admission_start": start,
        "ward": "SYN-INC-WARD",
        "bed": "SYN-INC-BED",
    }
    if end:
        row["admission_end"] = end
    return row


def _evolution(
    admission_key: str,
    happened_at: str,
    *,
    content: str = "SYNTH incremental evolution body.",
) -> dict[str, str]:
    """Canonical evolution dict for the shared ingestion service."""
    return {
        "admission_key": admission_key,
        "happened_at": happened_at,
        "content_text": content,
        "author_name": "DR. SYNTH-INC",
        "profession_type": "medica",
        "source_system": "tasy",
    }


def _queue_targeted_run(
    *,
    patient_key: str,
    admission: Admission,
    start_date: str,
    end_date: str,
    max_attempts: int = 1,
) -> IngestionRun:
    return IngestionRun.objects.create(
        status="queued",
        intent="full_sync",
        max_attempts=max_attempts,
        parameters_json={
            "patient_record": patient_key,
            "intent": "full_sync",
            "start_date": start_date,
            "end_date": end_date,
            "admission_id": str(admission.pk),
        },
    )


def _queue_legacy_run(
    *,
    patient_key: str,
    start_date: str,
    end_date: str,
    max_attempts: int = 1,
) -> IngestionRun:
    return IngestionRun.objects.create(
        status="queued",
        intent="full_sync",
        max_attempts=max_attempts,
        parameters_json={
            "patient_record": patient_key,
            "intent": "full_sync",
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def _run_worker(mock_adapter: MagicMock) -> None:
    with patch(
        f"{_WORKER_MODULE}.Command._create_adapter",
        return_value=mock_adapter,
    ):
        call_command("process_ingestion_runs_persistent_session")


def _recording_adapter(side_effect):
    adapter = _make_adapter_mock(snapshot_result=[])
    adapter.extract_evolutions.side_effect = side_effect
    return adapter


def _extract_calls(adapter: MagicMock) -> list[tuple[str, str]]:
    return [
        (call.kwargs["start_date"], call.kwargs["end_date"])
        for call in adapter.extract_evolutions.call_args_list
    ]


def _assert_ledger_present() -> None:
    """Assert the coverage ledger table exists (migration applied)."""
    tables = connection.introspection.table_names()
    assert _LEDGER_TABLE in tables, (
        "coverage ledger table missing — HTEFS-S3 migration not applied"
    )


def _coverage_rows() -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT admission_id, source_system, start_date, end_date, "
            f"completed_by_run_id, event_count FROM {_LEDGER_TABLE} "
            f"ORDER BY start_date, end_date"
        )
        return cursor.fetchall()


# ===========================================================================
# R1/R2 — lean coverage model + clean migration
# ===========================================================================


@pytest.mark.django_db
class TestCoverageModel:
    """EvolutionExtractionCoverage accepts confirmed facts only."""

    def test_accepts_empty_and_nonempty_and_links_run(self) -> None:
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-INC-M1")
        admission = _admission(
            patient, key="SYN-INC-ADM-M1",
            start=datetime.datetime(2024, 1, 1),
        )
        run = IngestionRun.objects.create(status="succeeded")

        nonempty = EvolutionExtractionCoverage.objects.create(
            admission=admission,
            source_system="tasy",
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 1, 15),
            completed_by_run=run,
            event_count=3,
        )
        empty = EvolutionExtractionCoverage.objects.create(
            admission=admission,
            source_system="tasy",
            start_date=datetime.date(2024, 1, 16),
            end_date=datetime.date(2024, 1, 20),
            completed_by_run=run,
            event_count=0,
        )
        nonempty.refresh_from_db()
        empty.refresh_from_db()
        assert nonempty.completed_by_run_id == run.pk
        assert nonempty.event_count == 3
        assert empty.event_count == 0
        assert empty.completed_at is not None
        _assert_ledger_present()

    def test_rejects_inverted_bounds(self) -> None:
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-INC-M2")
        admission = _admission(
            patient, key="SYN-INC-ADM-M2",
            start=datetime.datetime(2024, 1, 1),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                EvolutionExtractionCoverage.objects.create(
                    admission=admission,
                    source_system="tasy",
                    start_date=datetime.date(2024, 2, 1),
                    end_date=datetime.date(2024, 1, 1),
                    event_count=0,
                )

    def test_rejects_duplicate_bounds(self) -> None:
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-INC-M3")
        admission = _admission(
            patient, key="SYN-INC-ADM-M3",
            start=datetime.datetime(2024, 1, 1),
        )
        kwargs = {
            "admission": admission,
            "source_system": "tasy",
            "start_date": datetime.date(2024, 1, 1),
            "end_date": datetime.date(2024, 1, 10),
            "event_count": 1,
        }
        EvolutionExtractionCoverage.objects.create(**kwargs)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                EvolutionExtractionCoverage.objects.create(**kwargs)


# ===========================================================================
# R3/R4 — targeted planner reads the ledger, never ClinicalEvent
# ===========================================================================


@pytest.mark.django_db
class TestTargetedPlanner:
    """Targeted coverage comes ONLY from the explicit ledger."""

    def test_event_without_ledger_is_not_coverage(self) -> None:
        """A lone ClinicalEvent does not cover the target's date."""
        from apps.ingestion.gap_planner import (
            compute_targeted_coverage_gaps,
        )

        patient = _patient("SYN-INC-P1")
        admission = _admission(
            patient, key="SYN-INC-ADM-P1",
            start=datetime.datetime(2024, 1, 1),
        )
        # An event exists on 2024-01-10 (e.g. from an unrelated legacy run)
        # but the target admission has NO explicit coverage row.
        from django.utils import timezone as dj_timezone

        ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=None,
            event_identity_key="syn-inc-identity-1",
            content_hash="syn-inc-hash-1",
            happened_at=dj_timezone.make_aware(
                datetime.datetime(2024, 1, 10, 10, 0)
            ),
            author_name="DR. SYNTH-INC",
            profession_type="medica",
            content_text="SYNTH legacy event body.",
            signature_line="Dr. Synth CRM 1",
        )

        gaps = compute_targeted_coverage_gaps(
            admission_id=admission.pk,
            source_system="tasy",
            start_date="2024-01-01",
            end_date="2024-01-20",
        )
        assert gaps == [
            {"start_date": "2024-01-01", "end_date": "2024-01-20"}
        ], "a ClinicalEvent without ledger coverage must remain a gap"

    def test_explicit_empty_coverage_covers_interval(self) -> None:
        from apps.ingestion.gap_planner import (
            compute_targeted_coverage_gaps,
        )
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-INC-P2")
        admission = _admission(
            patient, key="SYN-INC-ADM-P2",
            start=datetime.datetime(2024, 1, 1),
        )
        EvolutionExtractionCoverage.objects.create(
            admission=admission,
            source_system="tasy",
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 1, 10),
            event_count=0,
        )
        gaps = compute_targeted_coverage_gaps(
            admission_id=admission.pk,
            source_system="tasy",
            start_date="2024-01-01",
            end_date="2024-01-10",
        )
        assert gaps == [], "explicit empty coverage must cover its interval"

    def test_overlapping_and_adjacent_coverage_union(self) -> None:
        from apps.ingestion.gap_planner import (
            compute_targeted_coverage_gaps,
        )
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-INC-P3")
        admission = _admission(
            patient, key="SYN-INC-ADM-P3",
            start=datetime.datetime(2024, 1, 1),
        )
        for start, end in (
            ("2024-01-01", "2024-01-10"),
            ("2024-01-10", "2024-01-20"),  # overlapping
            ("2024-01-21", "2024-01-31"),  # adjacent
        ):
            EvolutionExtractionCoverage.objects.create(
                admission=admission,
                source_system="tasy",
                start_date=datetime.date.fromisoformat(start),
                end_date=datetime.date.fromisoformat(end),
                event_count=1,
            )
        full = compute_targeted_coverage_gaps(
            admission_id=admission.pk,
            source_system="tasy",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        assert full == [], "overlapping/adjacent rows must unite"
        partial = compute_targeted_coverage_gaps(
            admission_id=admission.pk,
            source_system="tasy",
            start_date="2024-01-01",
            end_date="2024-02-05",
        )
        # The uncovered tail is 2024-02-01..2024-02-05; the canonical
        # first-gap backward overlap (1 day) pulls its start to 2024-01-31,
        # mirroring the legacy planner contract.
        assert partial == [
            {"start_date": "2024-01-31", "end_date": "2024-02-05"}
        ]

    def test_target_gap_chunks_are_deterministic_max_15_days(self) -> None:
        """Gaps split through the canonical chunker (no copied algorithm)."""
        from apps.ingestion.extractors.legacy_navigation import (
            build_chunks_for_interval as _assert_canonical_reexport,
        )
        from apps.ingestion.gap_planner import (
            compute_targeted_coverage_gaps,
        )

        patient = _patient("SYN-INC-P4")
        admission = _admission(
            patient, key="SYN-INC-ADM-P4",
            start=datetime.datetime(2024, 1, 1),
        )
        gaps = compute_targeted_coverage_gaps(
            admission_id=admission.pk,
            source_system="tasy",
            start_date="2024-01-01",
            end_date="2024-02-15",
        )
        assert gaps == [
            {"start_date": "2024-01-01", "end_date": "2024-02-15"}
        ]
        chunks_a = _assert_canonical_reexport(
            datetime.date.fromisoformat(gaps[0]["start_date"]),
            datetime.date.fromisoformat(gaps[0]["end_date"]),
        )
        chunks_b = _assert_canonical_reexport(
            datetime.date.fromisoformat(gaps[0]["start_date"]),
            datetime.date.fromisoformat(gaps[0]["end_date"]),
        )
        assert chunks_a == chunks_b, "chunk bounds must be deterministic"
        assert len(chunks_a) >= 2
        for chunk_start, chunk_end in chunks_a:
            span = (chunk_end - chunk_start).days + 1
            assert span <= 15, "canonical chunks span at most 15 days"


# ===========================================================================
# R5–R12 — worker incremental per-chunk commit (real DB proofs)
# ===========================================================================


@pytest.mark.django_db
class TestTargetedChunkCommit:
    """Per-chunk atomic commit against the real test database."""

    def test_first_chunk_survives_second_chunk_timeout(self) -> None:
        """R5/R6/R7/R11: chunk 1 commits; chunk 2 timeout fails the run
        while chunk 1's event, coverage and counters remain."""
        patient = _patient("SYN-INC-C1")
        admission = _admission(
            patient, key="SYN-INC-ADM-C1",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-INC-C1",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-02-15",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C1", "2024-01-01")],
        )

        calls: list[tuple[str, str]] = []

        def extract_side_effect(**kwargs):
            calls.append((kwargs["start_date"], kwargs["end_date"]))
            if len(calls) == 1:
                return [_evolution("SYN-INC-ADM-C1", "2024-01-05T10:00:00")]
            raise ExtractionTimeoutError(
                "Evolution report window timed out (sanitized)"
            )

        adapter.extract_evolutions.side_effect = extract_side_effect
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        assert adapter.cleanup_after_failure.called
        # R5: the target gap was split — more than one adapter call, each
        # within the canonical 15-day span.
        assert len(calls) >= 2, (
            f"expected chunked extraction, got single window {calls}"
        )
        for chunk_start, chunk_end in calls:
            span = (
                datetime.date.fromisoformat(chunk_end)
                - datetime.date.fromisoformat(chunk_start)
            ).days + 1
            assert span <= 15, f"chunk {chunk_start}..{chunk_end} > 15 days"
        # R7: cumulative counters reflect COMMITTED chunks only.
        assert run.events_processed == 1
        assert run.events_created == 1
        assert ClinicalEvent.objects.count() == 1
        # R6: chunk 1's coverage committed before chunk 2 failed.
        _assert_ledger_present()
        assert _coverage_rows() == [
            (
                admission.pk, "tasy",
                datetime.date(2024, 1, 1), datetime.date(2024, 1, 15),
                run.pk, 1,
            )
        ]

    def test_retry_skips_covered_first_chunk_only_edge_overlap(self) -> None:
        """R10: retry replans from the ledger and does not re-extract the
        fully covered first chunk; only the canonical one-day boundary
        overlap may re-query the covered edge (gap starts the day after the
        covered end and the planner's first-gap overlap pulls it back one
        day)."""
        patient = _patient("SYN-INC-C2")
        admission = _admission(
            patient, key="SYN-INC-ADM-C2",
            start=datetime.datetime(2024, 1, 1),
        )
        first_run = _queue_targeted_run(
            patient_key="SYN-INC-C2",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-02-15",
            max_attempts=1,
        )
        first_adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C2", "2024-01-01")],
        )
        first_calls: list[tuple[str, str]] = []

        def first_side_effect(**kwargs):
            first_calls.append((kwargs["start_date"], kwargs["end_date"]))
            if len(first_calls) == 1:
                return [_evolution("SYN-INC-ADM-C2", "2024-01-05T10:00:00")]
            raise ExtractionTimeoutError(
                "Evolution report window timed out (sanitized)"
            )

        first_adapter.extract_evolutions.side_effect = first_side_effect
        _run_worker(first_adapter)
        first_run.refresh_from_db()
        assert first_run.status == "failed"
        assert len(first_calls) >= 2

        # Retry: a fresh queued run for the same admission and window.
        retry_run = _queue_targeted_run(
            patient_key="SYN-INC-C2",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-02-15",
            max_attempts=1,
        )
        retry_adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C2", "2024-01-01")],
        )
        retry_adapter.extract_evolutions.side_effect = lambda **kwargs: []
        _run_worker(retry_adapter)

        retry_run.refresh_from_db()
        assert retry_run.status == "succeeded"
        retry_windows = _extract_calls(retry_adapter)
        assert retry_windows, "retry must still extract the remaining gap"
        starts = [start for start, _end in retry_windows]
        # The first chunk (2024-01-01 .. 2024-01-15) is NOT re-extracted as
        # a whole: no call may start before the covered chunk's last day.
        assert min(starts) >= "2024-01-15", (
            f"retry re-extracted covered chunk: {retry_windows}"
        )
        # Canonical boundary overlap: the first retry chunk starts exactly
        # on the covered chunk's last day (one-day overlap), not earlier.
        assert starts[0] == "2024-01-15"
        # Idempotent ledger: the first chunk keeps exactly one row and the
        # retry only added rows for the remaining chunks.
        _assert_ledger_present()
        rows = _coverage_rows()
        first_chunk_rows = [
            row for row in rows
            if row[2] == datetime.date(2024, 1, 1)
            and row[3] == datetime.date(2024, 1, 15)
        ]
        assert len(first_chunk_rows) == 1
        assert len(rows) == 4
        assert ClinicalEvent.objects.count() == 1

    def test_empty_first_chunk_creates_zero_coverage(self) -> None:
        """R8: an explicitly empty extraction still covers its chunk."""
        patient = _patient("SYN-INC-C3")
        admission = _admission(
            patient, key="SYN-INC-ADM-C3",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-INC-C3",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C3", "2024-01-01")],
        )
        adapter.extract_evolutions.side_effect = lambda **kwargs: []
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 0
        _assert_ledger_present()
        assert _coverage_rows() == [
            (
                admission.pk, "tasy",
                datetime.date(2024, 1, 1), datetime.date(2024, 1, 10),
                run.pk, 0,
            )
        ]

    def test_partial_ingest_failure_rolls_back_chunk(self) -> None:
        """R6: an exception mid-``ingest_evolutions`` (after one evolution
        was already persisted) reverts the whole chunk — events, coverage
        and counters — proven by querying the database after the failure."""
        patient = _patient("SYN-INC-C4")
        admission = _admission(
            patient, key="SYN-INC-ADM-C4",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-INC-C4",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C4", "2024-01-01")],
        )
        adapter.extract_evolutions.side_effect = lambda **kwargs: [
            _evolution("SYN-INC-ADM-C4", "2024-01-05T10:00:00"),
            # Invalid happened_at raises inside ingest_evolutions AFTER the
            # first evolution was persisted within the chunk transaction.
            _evolution("SYN-INC-ADM-C4", "not-a-date"),
        ]
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        # REAL rollback proof: the first evolution must NOT survive.
        assert ClinicalEvent.objects.count() == 0
        assert run.events_processed == 0
        assert run.events_created == 0
        _assert_ledger_present()
        assert _coverage_rows() == []

    def test_coverage_upsert_failure_rolls_back_chunk(self) -> None:
        """R6: when the coverage upsert fails inside the chunk transaction,
        the already-persisted clinical events and counters roll back with
        it (database-checked, not a transaction mock)."""
        patient = _patient("SYN-INC-C5")
        admission = _admission(
            patient, key="SYN-INC-ADM-C5",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-INC-C5",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C5", "2024-01-01")],
        )
        adapter.extract_evolutions.side_effect = lambda **kwargs: [
            _evolution("SYN-INC-ADM-C5", "2024-01-05T10:00:00"),
        ]
        with patch(
            f"{_WORKER_MODULE}.EvolutionExtractionCoverage.objects"
            f".update_or_create",
            side_effect=RuntimeError("forced coverage failure"),
        ):
            _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        # REAL rollback proof: clinical persistence did not survive the
        # coverage failure.
        assert ClinicalEvent.objects.count() == 0
        assert run.events_processed == 0
        assert run.events_created == 0
        # Persistence failures are database-local: no session cleanup.
        assert not adapter.cleanup_after_failure.called
        _assert_ledger_present()
        assert _coverage_rows() == []

    def test_reprocess_confirmed_bounds_no_double_count(self) -> None:
        """R9: a run whose window is fully covered by the ledger extracts
        nothing and neither duplicates coverage nor sums counters again."""
        patient = _patient("SYN-INC-C6")
        admission = _admission(
            patient, key="SYN-INC-ADM-C6",
            start=datetime.datetime(2024, 1, 1),
        )
        first_run = _queue_targeted_run(
            patient_key="SYN-INC-C6",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        first_adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C6", "2024-01-01")],
        )
        first_adapter.extract_evolutions.side_effect = lambda **kwargs: [
            _evolution("SYN-INC-ADM-C6", "2024-01-05T10:00:00"),
        ]
        _run_worker(first_adapter)
        first_run.refresh_from_db()
        assert first_run.status == "succeeded"
        assert first_run.events_processed == 1

        # Reprocess the exact same confirmed bounds.
        second_run = _queue_targeted_run(
            patient_key="SYN-INC-C6",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        second_adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C6", "2024-01-01")],
        )
        second_adapter.extract_evolutions.side_effect = lambda **kwargs: []
        _run_worker(second_adapter)

        second_run.refresh_from_db()
        assert second_run.status == "succeeded"
        second_adapter.extract_evolutions.assert_not_called()
        assert second_run.events_processed == 0
        assert second_run.events_created == 0
        _assert_ledger_present()
        rows = _coverage_rows()
        assert len(rows) == 1, "confirmed bounds must not duplicate coverage"
        assert rows[0][5] == 1
        assert ClinicalEvent.objects.count() == 1

    def test_run_without_admission_id_no_coverage_legacy(self) -> None:
        """R12: legacy no-target runs keep the accumulated flow and never
        create admission-specific coverage."""
        patient = _patient("SYN-INC-C7")
        _admission(
            patient, key="SYN-INC-ADM-C7",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_legacy_run(
            patient_key="SYN-INC-C7",
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-INC-ADM-C7", "2024-01-01")],
        )
        adapter.extract_evolutions.side_effect = lambda **kwargs: [
            _evolution("SYN-INC-ADM-C7", "2024-01-05T10:00:00"),
        ]
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert _extract_calls(adapter) == [("2024-01-01", "2024-01-10")]
        assert ClinicalEvent.objects.count() == 1
        _assert_ledger_present()
        assert _coverage_rows() == [], (
            "no-target runs must not claim admission-specific coverage"
        )
