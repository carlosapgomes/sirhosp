"""RPAP-S4 unit tests: current-census admissions recovery.

Covers the vertical slice requirements:

- R1: latest complete census with unique successful census-run provenance;
- R2: dry-run by default with zero mutation and aggregate-only output;
- R3: explicit bounded apply (limit 1..100) in a single recovery batch;
- R4: idempotency and second-evaluation (concurrency) deduplication;
- R5: immutable historical runs and no empty recovery batch;
- R6: composition with the canonical ``queue_admissions_only_run`` helper;
- R7: stdout/stderr/errors never carry patient identifiers.
"""

from __future__ import annotations

import io
from datetime import timedelta
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.census.admissions_recovery import (
    MAX_RECOVERY_LIMIT,
    RECOVERY_BATCH_PURPOSE,
    CensusAdmissionsRecoveryError,
    apply_current_census_admissions_recovery,
    plan_current_census_admissions_recovery,
)
from apps.census.management.commands.recover_current_census_admissions import (
    Command,
)
from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import MINIMUM_CENSUS_SECTORS
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.patients.models import Admission, Patient

COMMAND_NAME = "recover_current_census_admissions"

SENTINEL_PATIENT = "PRIV-PAT-042"
SENTINEL_SECTOR = "PRIV-SETOR-777"


def _make_census_run(*, status: str = "succeeded") -> IngestionRun:
    """Create a census-extraction IngestionRun (default: successful)."""
    return IngestionRun.objects.create(
        status=status,
        intent="census_extraction",
        parameters_json={"intent": "census_extraction"},
    )


def _occupied_row(
    *,
    census_run: IngestionRun,
    captured_at,
    setor: str,
    leito: str,
    prontuario: str,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        ingestion_run=census_run,
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        especialidade="NEF",
        bed_status=BedStatus.OCCUPIED,
    )


def _filler_rows(
    *, census_run: IngestionRun, captured_at, start: int, count: int
) -> None:
    """Add empty-bed rows so the captured_at group reaches the sector gate."""
    for i in range(start, start + count):
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            ingestion_run=census_run,
            setor=f"SETOR FILLER {i:03d}",
            leito=f"FL{i:03d}",
            prontuario="",
            nome="DESOCUPADO",
            bed_status=BedStatus.EMPTY,
        )


def _complete_census(
    *,
    census_run: IngestionRun,
    occupied: list[tuple[str, str, str]],
    captured_at=None,
):
    """Create a complete census (>= MINIMUM_CENSUS_SECTORS sectors).

    ``occupied`` is a list of (setor, leito, prontuario) tuples for
    occupied beds. Returns the shared captured_at value.
    """
    captured_at = captured_at or timezone.now()
    sectors = set()
    for setor, leito, prontuario in occupied:
        _occupied_row(
            census_run=census_run,
            captured_at=captured_at,
            setor=setor,
            leito=leito,
            prontuario=prontuario,
        )
        sectors.add(setor)
    missing = max(0, MINIMUM_CENSUS_SECTORS - len(sectors))
    _filler_rows(
        census_run=census_run,
        captured_at=captured_at,
        start=0,
        count=missing,
    )
    return captured_at


def _baseline_counts() -> dict[str, int]:
    return {
        "batches": CensusExecutionBatch.objects.count(),
        "runs": IngestionRun.objects.count(),
        "patients": Patient.objects.count(),
        "admissions": Admission.objects.count(),
    }


def _run_snapshot(run: IngestionRun) -> dict[str, Any]:
    """Snapshot every mutable field of a run for immutability comparison."""
    return {
        "status": run.status,
        "intent": run.intent,
        "parameters_json": run.parameters_json,
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "next_retry_at": run.next_retry_at,
        "queued_at": run.queued_at,
        "processing_started_at": run.processing_started_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "failure_reason": run.failure_reason,
        "timed_out": run.timed_out,
        "worker_label": run.worker_label,
        "worker_heartbeat_at": run.worker_heartbeat_at,
        "admissions_seen": run.admissions_seen,
        "admissions_created": run.admissions_created,
        "admissions_updated": run.admissions_updated,
        "events_processed": run.events_processed,
        "events_created": run.events_created,
        "events_skipped": run.events_skipped,
        "events_revised": run.events_revised,
        "gaps_json": run.gaps_json,
        "error_message": run.error_message,
        "batch_id": run.batch_id,
    }


@pytest.mark.django_db
class TestRecoverySourceResolution:
    """R1: the source is the latest complete census with unique run."""

    def test_missing_snapshot_blocks_recovery(self):
        with pytest.raises(CensusAdmissionsRecoveryError) as exc:
            plan_current_census_admissions_recovery()
        assert exc.value.reason == "missing_snapshot"

    def test_incomplete_snapshot_blocks_recovery(self):
        census_run = _make_census_run()
        captured_at = timezone.now()
        _occupied_row(
            census_run=census_run,
            captured_at=captured_at,
            setor="UTI A",
            leito="UG01A",
            prontuario="PAT-1",
        )
        # Only one distinct sector -> below the completeness gate.
        with pytest.raises(CensusAdmissionsRecoveryError) as exc:
            plan_current_census_admissions_recovery()
        assert exc.value.reason == "incomplete_snapshot"

    def test_ambiguous_provenance_blocks_recovery(self):
        run_a = _make_census_run()
        run_b = _make_census_run()
        captured_at = timezone.now()
        _occupied_row(
            census_run=run_a,
            captured_at=captured_at,
            setor="UTI A",
            leito="UG01A",
            prontuario="PAT-A",
        )
        _occupied_row(
            census_run=run_b,
            captured_at=captured_at,
            setor="UTI B",
            leito="UG01B",
            prontuario="PAT-B",
        )
        # Two runs share the captured_at group -> ambiguous provenance.
        _filler_rows(
            census_run=run_a,
            captured_at=captured_at,
            start=0,
            count=20,
        )
        _filler_rows(
            census_run=run_b,
            captured_at=captured_at,
            start=20,
            count=20,
        )
        with pytest.raises(CensusAdmissionsRecoveryError) as exc:
            plan_current_census_admissions_recovery()
        assert exc.value.reason == "ambiguous_provenance"

    def test_unresolved_census_run_blocks_recovery(self):
        census_run = _make_census_run(status="failed")
        _complete_census(
            census_run=census_run,
            occupied=[("UTI A", "UG01A", "PAT-1")],
        )
        with pytest.raises(CensusAdmissionsRecoveryError) as exc:
            plan_current_census_admissions_recovery()
        assert exc.value.reason == "unresolved_census_run"

    def test_plan_uses_latest_captured_at_group(self):
        older = _make_census_run()
        newer = _make_census_run()
        _complete_census(
            census_run=older,
            occupied=[("SETOR OCUP OLD", "LB-O", "PAT-OLD")],
            captured_at=timezone.now() - timedelta(hours=1),
        )
        _complete_census(
            census_run=newer,
            occupied=[("SETOR OCUP NEW", "LB-N", "PAT-NEW")],
            captured_at=timezone.now(),
        )
        plan = plan_current_census_admissions_recovery()
        assert plan.census_run_id == newer.pk
        assert plan.candidates == 1
        assert plan.eligible == 1


@pytest.mark.django_db
class TestDryRunDefault:
    """R2: dry-run is the default and never mutates."""

    def test_default_dry_run_is_non_mutating(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[("SETOR OCUP A", "LB-A", "PAT-1")],
        )
        before = _baseline_counts()
        out = io.StringIO()
        err = io.StringIO()
        call_command(COMMAND_NAME, stdout=out, stderr=err)
        assert _baseline_counts() == before
        assert "dry-run" in out.getvalue()

    def test_dry_run_reports_eligible_and_exclusion_counts(self):
        census_run = _make_census_run()
        captured_at = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            ingestion_run=census_run,
            setor="UTI SEM PRONT",
            leito="LB-X",
            prontuario="",
            nome="OCUPADO SEM IDENTIFICADOR",
            bed_status=BedStatus.OCCUPIED,
        )
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-ACTIVE"),
                ("SETOR OCUP B", "LB-B", "PAT-RECOVERED"),
                ("SETOR OCUP C", "LB-C", "PAT-FRESH"),
            ],
            captured_at=captured_at,
        )
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": "PAT-ACTIVE",
                "intent": "admissions_only",
            },
        )
        recovery_batch = CensusExecutionBatch.objects.create(
            status="failed",
            notes_json={
                "purpose": RECOVERY_BATCH_PURPOSE,
                "census_run_id": str(census_run.pk),
            },
        )
        IngestionRun.objects.create(
            status="failed",
            intent="admissions_only",
            parameters_json={
                "patient_record": "PAT-RECOVERED",
                "intent": "admissions_only",
            },
            batch=recovery_batch,
        )

        plan = plan_current_census_admissions_recovery()
        assert plan.candidates == 3
        assert plan.excluded_no_identifier == 1
        assert plan.excluded_active == 1
        assert plan.excluded_recovered == 1
        assert plan.eligible == 1
        assert plan.limit_applicable == 1

        out = io.StringIO()
        call_command(COMMAND_NAME, stdout=out)
        text = out.getvalue()
        for label in (
            "dry-run",
            "candidates:",
            "eligible:",
            "excluded_active:",
            "excluded_recovered:",
            "excluded_no_identifier:",
            "limit_applicable:",
        ):
            assert label in text

    def test_dry_run_recovery_from_other_census_run_is_not_excluded(self):
        census_run = _make_census_run()
        other_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-OLD"),
                ("SETOR OCUP B", "LB-B", "PAT-FRESH"),
            ],
        )
        # Recovery batch belongs to a DIFFERENT census run.
        other_batch = CensusExecutionBatch.objects.create(
            status="succeeded",
            notes_json={
                "purpose": RECOVERY_BATCH_PURPOSE,
                "census_run_id": str(other_run.pk),
            },
        )
        IngestionRun.objects.create(
            status="succeeded",
            intent="admissions_only",
            parameters_json={
                "patient_record": "PAT-OLD",
                "intent": "admissions_only",
            },
            batch=other_batch,
        )
        plan = plan_current_census_admissions_recovery()
        assert plan.candidates == 2
        assert plan.excluded_recovered == 0
        assert plan.eligible == 2

    def test_dry_run_with_optional_limit_caps_the_plan(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[("SETOR OCUP A", "LB-A", "PAT-1")],
        )
        plan = plan_current_census_admissions_recovery(limit=1)
        assert plan.limit_applicable == 1
        out = io.StringIO()
        call_command(COMMAND_NAME, limit=1, stdout=out)
        assert "limit_applicable: 1" in out.getvalue()


@pytest.mark.django_db
class TestApplyValidation:
    """R3: apply without a valid limit fails before any mutation."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"apply": True},
            {"apply": True, "limit": 0},
            {"apply": True, "limit": -5},
            {"apply": True, "limit": MAX_RECOVERY_LIMIT + 1},
            {"limit": MAX_RECOVERY_LIMIT + 1},
        ],
    )
    def test_invalid_limit_fails_before_mutation(self, kwargs):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[("SETOR OCUP A", "LB-A", "PAT-1")],
        )
        before = _baseline_counts()
        with pytest.raises(CommandError):
            call_command(COMMAND_NAME, **kwargs)
        assert _baseline_counts() == before

    def test_boundary_limits_are_accepted(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[("SETOR OCUP A", "LB-A", "PAT-1")],
        )
        result = apply_current_census_admissions_recovery(limit=1)
        assert result.runs_created == 1
        result_100 = apply_current_census_admissions_recovery(limit=100)
        assert result_100.runs_created == 0


@pytest.mark.django_db
class TestApplyBehavior:
    """R3/R4/R6: bounded apply creates one recovery batch, never duplicates."""

    def test_apply_creates_one_recovery_batch_with_at_most_n_runs(self):
        census_run = _make_census_run()
        occupied = [
            (f"SETOR OCUP {i:02d}", f"LB{i:02d}", f"PAT-{i}")
            for i in range(5)
        ]
        _complete_census(census_run=census_run, occupied=occupied)

        result = apply_current_census_admissions_recovery(limit=3)
        assert result.runs_created == 3
        assert result.batch_id is not None
        assert result.plan.eligible == 5
        assert result.plan.limit_applicable == 3

        batch = CensusExecutionBatch.objects.get(pk=result.batch_id)
        assert batch.status == "running"
        assert batch.enqueue_finished_at is not None
        assert batch.notes_json["purpose"] == RECOVERY_BATCH_PURPOSE
        assert batch.notes_json["census_run_id"] == str(census_run.pk)

        runs = IngestionRun.objects.filter(batch=batch)
        assert runs.count() == 3
        assert {r.intent for r in runs} == {"admissions_only"}
        assert {r.status for r in runs} == {"queued"}
        assert all(r.batch_id == batch.pk for r in runs)

    def test_apply_selects_deterministically_ordered_first_n(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP Z", "LB-Z", "PAT-Z"),
                ("SETOR OCUP A", "LB-A", "PAT-A"),
                ("SETOR OCUP M", "LB-M", "PAT-M"),
            ],
        )
        result = apply_current_census_admissions_recovery(limit=2)
        records = list(
            IngestionRun.objects.filter(batch_id=result.batch_id)
            .order_by("pk")
            .values_list("parameters_json__patient_record", flat=True)
        )
        assert records == ["PAT-A", "PAT-M"]

    def test_apply_dedupes_patient_across_multiple_beds(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-SAME"),
                ("SETOR OCUP B", "LB-B", "PAT-SAME"),
                ("SETOR OCUP C", "LB-C", "PAT-OTHER"),
            ],
        )
        plan = plan_current_census_admissions_recovery()
        assert plan.candidates == 2
        result = apply_current_census_admissions_recovery(limit=10)
        assert result.runs_created == 2
        assert (
            IngestionRun.objects.filter(
                intent="admissions_only",
                parameters_json__patient_record="PAT-SAME",
            ).count()
            == 1
        )

    def test_repeated_apply_is_idempotent(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-1"),
                ("SETOR OCUP B", "LB-B", "PAT-2"),
            ],
        )
        first = apply_current_census_admissions_recovery(limit=100)
        assert first.runs_created == 2
        assert CensusExecutionBatch.objects.count() == 1

        second = apply_current_census_admissions_recovery(limit=100)
        assert second.runs_created == 0
        assert second.batch_id is None
        assert CensusExecutionBatch.objects.count() == 1
        assert (
            IngestionRun.objects.filter(intent="admissions_only").count() == 2
        )

    def test_second_evaluation_does_not_duplicate_terminal_recovery(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-1"),
                ("SETOR OCUP B", "LB-B", "PAT-2"),
                ("SETOR OCUP C", "LB-C", "PAT-3"),
            ],
        )
        first = apply_current_census_admissions_recovery(limit=100)
        assert first.runs_created == 3

        # A concurrent evaluator already enqueued and terminally failed a
        # recovery run; presence in the recovery batch must still exclude
        # the patient regardless of the terminal outcome.
        recovered = IngestionRun.objects.get(
            batch_id=first.batch_id,
            parameters_json__patient_record="PAT-1",
        )
        recovered.status = "failed"
        recovered.failure_reason = "invalid_payload"
        recovered.save()

        second = apply_current_census_admissions_recovery(limit=100)
        assert second.runs_created == 0
        assert second.batch_id is None
        assert (
            IngestionRun.objects.filter(batch_id=first.batch_id).count() == 3
        )

    def test_zero_eligible_candidates_create_no_batch(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "PAT-1"),
                ("SETOR OCUP B", "LB-B", "PAT-2"),
            ],
        )
        for prontuario, status in (("PAT-1", "queued"), ("PAT-2", "running")):
            IngestionRun.objects.create(
                status=status,
                intent="admissions_only",
                parameters_json={
                    "patient_record": prontuario,
                    "intent": "admissions_only",
                },
            )
        result = apply_current_census_admissions_recovery(limit=10)
        assert result.runs_created == 0
        assert result.batch_id is None
        assert CensusExecutionBatch.objects.count() == 0


@pytest.mark.django_db
class TestHistoryAndPrivacy:
    """R5/R7: history stays immutable and output stays aggregate-only."""

    def test_historical_runs_remain_immutable(self):
        census_run = _make_census_run()
        incident_batch = CensusExecutionBatch.objects.create(status="succeeded")
        historical = IngestionRun.objects.create(
            status="succeeded",
            intent="admissions_only",
            parameters_json={
                "patient_record": "HIST-1",
                "intent": "admissions_only",
                "start_date": "01/01/2024",
            },
            batch=incident_batch,
            admissions_seen=0,
            admissions_created=0,
            admissions_updated=0,
            attempt_count=2,
            max_attempts=3,
            failure_reason="",
            timed_out=False,
            error_message="",
            worker_label="persistent-worker-1",
            worker_heartbeat_at=timezone.now(),
            next_retry_at=timezone.now(),
            queued_at=timezone.now() - timedelta(days=1),
            processing_started_at=timezone.now() - timedelta(hours=23),
            finished_at=timezone.now() - timedelta(hours=22),
        )
        _complete_census(
            census_run=census_run,
            occupied=[
                ("SETOR OCUP A", "LB-A", "HIST-1"),
                ("SETOR OCUP B", "LB-B", "FRESH-1"),
            ],
        )
        before_historical = _run_snapshot(historical)
        before_census_run = _run_snapshot(census_run)

        result = apply_current_census_admissions_recovery(limit=100)
        assert result.runs_created == 2

        historical.refresh_from_db()
        census_run.refresh_from_db()
        assert _run_snapshot(historical) == before_historical
        assert _run_snapshot(census_run) == before_census_run

    def test_output_never_contains_patient_identifiers(self):
        census_run = _make_census_run()
        _complete_census(
            census_run=census_run,
            occupied=[("SETOR OCUP A", "LB-A", SENTINEL_PATIENT)],
        )

        out = io.StringIO()
        err = io.StringIO()
        call_command(COMMAND_NAME, stdout=out, stderr=err)
        text = out.getvalue() + err.getvalue()
        assert SENTINEL_PATIENT not in text

        out2 = io.StringIO()
        err2 = io.StringIO()
        call_command(
            COMMAND_NAME,
            apply=True,
            limit=1,
            stdout=out2,
            stderr=err2,
        )
        text2 = out2.getvalue() + err2.getvalue()
        assert SENTINEL_PATIENT not in text2

    def test_blocked_error_is_sanitized(self):
        bad_run = _make_census_run(status="failed")
        _complete_census(
            census_run=bad_run,
            occupied=[("SETOR OCUP A", "LB-A", SENTINEL_PATIENT)],
        )
        err = io.StringIO()
        with pytest.raises(CommandError):
            call_command(COMMAND_NAME, stderr=err)
        assert SENTINEL_PATIENT not in err.getvalue()
        assert SENTINEL_SECTOR not in err.getvalue()

    def test_help_describes_dry_run_and_bounded_apply(self):
        help_text = Command.help
        assert "dry-run" in help_text
        assert "--apply" in help_text
        assert "1..100" in help_text
