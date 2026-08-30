"""HTEFS-S4: fixed 60-minute automatic full-sync guard via ``next_retry_at``.

Covers the bounded cross-run guard of
:func:`apps.ingestion.services.enqueue_most_recent_admission_full_sync`:

- the latest terminal targeted result (``full_sync`` or
  ``full_admission_sync``) for the SAME admission (``parameters_json
  .admission_id``) is the only guard input;
- a recent terminal failure defers the new automatic ``full_sync`` to
  ``failed.finished_at + 60 minutes`` (never ``now + 60 minutes``);
- an expired failure adds no delay and future re-enqueues never extend
  the window (derivation is always from the terminal failure);
- a later terminal success resets the guard;
- queued/running rows and terminal rows without ``finished_at`` never
  replace the last valid terminal result;
- manual ``full_admission_sync`` (views) stays immediate;
- the intra-run retry of BOTH workers is untouched: ``timeout`` keeps the
  ~+60s requeue and ``invalid_payload`` stays terminal fail-fast.

All guard timing tests pin ``django.utils.timezone.now`` to a single
frozen instant (no sleeps, no real waiting) so the deadline is provably
derived from ``finished_at``.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.extractors.errors import InvalidJsonError
from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfTimeoutError,
)
from apps.ingestion.management.commands.process_ingestion_runs import (
    Command as CurrentWorkerCommand,
)
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
    Command as PersistentWorkerCommand,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
)
from apps.ingestion.services import enqueue_most_recent_admission_full_sync
from apps.patients.models import Admission, Patient

GUARD_MINUTES = 60


# ---------------------------------------------------------------------------
# Deterministic clock + fixtures
# ---------------------------------------------------------------------------


def _frozen_at(moment):
    """Pin ``django.utils.timezone.now`` to one deterministic instant."""
    return mock.patch("django.utils.timezone.now", return_value=moment)


def _make_patient(suffix: str) -> Patient:
    return Patient.objects.create(
        source_system="tasy",
        patient_source_key=f"HTEFS-S4-{suffix}",
        name=f"HTFES S4 PATIENT {suffix}",
    )


def _make_admission(
    patient: Patient,
    suffix: str,
    *,
    days_ago: int,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-{suffix}",
        admission_date=timezone.now() - timedelta(days=days_ago),
        discharge_date=None,
    )


def _terminal_run(
    admission: Admission,
    *,
    status: str,
    intent: str = "full_sync",
    minutes_ago: int | None = 10,
    now=None,
) -> IngestionRun:
    """Create a targeted terminal row for the admission.

    ``minutes_ago=None`` creates a terminal-status row without
    ``finished_at`` (invalid terminal row per the guard contract).
    ``now`` pins the reference clock (default: real ``timezone.now()``)
    so boundary arithmetic against a frozen instant is exact.
    """
    base = now if now is not None else timezone.now()
    finished_at = (
        base - timedelta(minutes=minutes_ago)
        if minutes_ago is not None
        else None
    )
    return IngestionRun.objects.create(
        status=status,
        intent=intent,
        finished_at=finished_at,
        attempt_count=1,
        parameters_json={
            "patient_record": admission.patient.patient_source_key,
            "admission_id": str(admission.pk),
            "intent": intent,
        },
    )


def _worker_command(worker: str):
    out, err = StringIO(), StringIO()
    if worker == "persistent":
        return PersistentWorkerCommand(stdout=out, stderr=err)
    return CurrentWorkerCommand(stdout=out, stderr=err)


def _mid_processing_run(batch: CensusExecutionBatch) -> IngestionRun:
    """Create a run mid-processing (running, first attempt in progress)."""
    run = IngestionRun.objects.create(
        status="running",
        intent="full_sync",
        batch=batch,
        attempt_count=1,
        max_attempts=3,
        parameters_json={
            "patient_record": "HTEFS-S4-REG",
            "intent": "full_sync",
        },
    )
    IngestionRunAttempt.objects.create(run=run, attempt_number=1)
    return run


# ---------------------------------------------------------------------------
# Guard policy (frozen clock)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutomaticFullSyncDeferral:
    """Fixed 60-minute cross-run guard scoped to one admission."""

    def test_recent_failure_defers_until_failure_plus_60_minutes(self):
        """RED item 1: deadline is failure.finished_at+60m, not now+60m."""
        frozen = timezone.now()
        patient = _make_patient("P1")
        admission = _make_admission(patient, "A1", days_ago=3)
        failure = _terminal_run(
            admission, status="failed", minutes_ago=10, now=frozen
        )
        batch = CensusExecutionBatch.objects.create(status="running")

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient, batch=batch)

        assert run is not None
        assert run.status == "queued"
        assert run.batch == batch
        expected = failure.finished_at + timedelta(minutes=GUARD_MINUTES)
        assert run.next_retry_at == expected
        # 50 minutes remain: proof it is NOT now + 60 minutes.
        assert run.next_retry_at != frozen + timedelta(minutes=GUARD_MINUTES)
        assert run.next_retry_at - frozen == timedelta(minutes=50)

    def test_failure_exactly_60_minutes_old_is_immediately_eligible(self):
        """RED item 2a: boundary failure.finished_at+60m <= now -> None."""
        frozen = timezone.now()
        patient = _make_patient("P2")
        admission = _make_admission(patient, "A2", days_ago=3)
        _terminal_run(
            admission,
            status="failed",
            minutes_ago=GUARD_MINUTES,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_failure_older_than_60_minutes_is_immediately_eligible(self):
        """RED item 2b: expired failure adds no delay."""
        frozen = timezone.now()
        patient = _make_patient("P3")
        admission = _make_admission(patient, "A3", days_ago=3)
        _terminal_run(
            admission,
            status="failed",
            minutes_ago=GUARD_MINUTES + 1,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_reenqueue_does_not_extend_window(self):
        """RED item 4 extension (R4): re-enqueues never push the window."""
        frozen = timezone.now()
        patient = _make_patient("P4")
        admission = _make_admission(patient, "A4", days_ago=3)
        failure = _terminal_run(
            admission, status="failed", minutes_ago=10, now=frozen
        )

        with _frozen_at(frozen):
            first = enqueue_most_recent_admission_full_sync(patient)
            second = enqueue_most_recent_admission_full_sync(patient)

        assert first is not None and second is not None
        expected = failure.finished_at + timedelta(minutes=GUARD_MINUTES)
        assert first.next_retry_at == expected
        assert second.next_retry_at == expected

    def test_success_after_failure_resets_guard(self):
        """RED item 3: later terminal success means immediate eligibility."""
        frozen = timezone.now()
        patient = _make_patient("P5")
        admission = _make_admission(patient, "A5", days_ago=3)
        _terminal_run(admission, status="failed", minutes_ago=120, now=frozen)
        _terminal_run(admission, status="succeeded", minutes_ago=5, now=frozen)

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_recent_failure_after_old_success_defers(self):
        """RED item 4: newer failure replaces older success -> deferred."""
        frozen = timezone.now()
        patient = _make_patient("P6")
        admission = _make_admission(patient, "A6", days_ago=3)
        _terminal_run(
            admission, status="succeeded", minutes_ago=120, now=frozen
        )
        failure = _terminal_run(
            admission, status="failed", minutes_ago=10, now=frozen
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at == failure.finished_at + timedelta(
            minutes=GUARD_MINUTES
        )

    def test_recent_failure_of_other_admission_does_not_defer_target(self):
        """RED item 5a: guard scope is the target admission id, not patient."""
        frozen = timezone.now()
        patient = _make_patient("P7")
        _make_admission(patient, "A7-OLD", days_ago=30)
        target = _make_admission(patient, "A7-TARGET", days_ago=3)
        # Recent failure belongs to ANOTHER (older) admission of the same
        # patient; the target admission itself is clean.
        _terminal_run(
            Admission.objects.get(source_admission_key="ADM-A7-OLD"),
            status="failed",
            minutes_ago=10,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.parameters_json["admission_id"] == str(target.pk)
        assert run.next_retry_at is None

    def test_other_admissions_old_failure_does_not_reset_target_defer(self):
        """RED item 5b: target's recent failure still defers despite the
        other admission's stale failure."""
        frozen = timezone.now()
        patient = _make_patient("P8")
        _make_admission(patient, "A8-OLD", days_ago=30)
        target = _make_admission(patient, "A8-TARGET", days_ago=3)
        _terminal_run(
            Admission.objects.get(source_admission_key="ADM-A8-OLD"),
            status="failed",
            minutes_ago=120,
            now=frozen,
        )
        failure = _terminal_run(
            target, status="failed", minutes_ago=10, now=frozen
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.parameters_json["admission_id"] == str(target.pk)
        assert run.next_retry_at == failure.finished_at + timedelta(
            minutes=GUARD_MINUTES
        )

    def test_full_admission_sync_recent_failure_defers(self):
        """RED item 6a: full_admission_sync terminal failure participates."""
        frozen = timezone.now()
        patient = _make_patient("P9")
        admission = _make_admission(patient, "A9", days_ago=3)
        failure = _terminal_run(
            admission,
            status="failed",
            intent="full_admission_sync",
            minutes_ago=10,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at == failure.finished_at + timedelta(
            minutes=GUARD_MINUTES
        )

    def test_full_admission_sync_success_resets(self):
        """RED item 6b: full_admission_sync success resets the guard."""
        frozen = timezone.now()
        patient = _make_patient("P10")
        admission = _make_admission(patient, "A10", days_ago=3)
        _terminal_run(admission, status="failed", minutes_ago=120, now=frozen)
        _terminal_run(
            admission,
            status="succeeded",
            intent="full_admission_sync",
            minutes_ago=5,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_nonterminal_rows_do_not_replace_last_terminal(self):
        """RED item 7a: queued/running rows never reset the guard."""
        frozen = timezone.now()
        patient = _make_patient("P11")
        admission = _make_admission(patient, "A11", days_ago=3)
        failure = _terminal_run(
            admission, status="failed", minutes_ago=10, now=frozen
        )
        # Newer, non-terminal rows must be invisible to the guard.
        _terminal_run(admission, status="queued", minutes_ago=1, now=frozen)
        _terminal_run(admission, status="running", minutes_ago=1, now=frozen)

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at == failure.finished_at + timedelta(
            minutes=GUARD_MINUTES
        )

    def test_terminal_without_finished_at_is_ignored(self):
        """RED item 7b: terminal row without finished_at is not a result."""
        frozen = timezone.now()
        patient = _make_patient("P12")
        admission = _make_admission(patient, "A12", days_ago=3)
        _terminal_run(
            admission, status="succeeded", minutes_ago=30, now=frozen
        )
        # Newer failed row WITHOUT finished_at must not replace the last
        # valid terminal (the success), so the guard stays reset.
        _terminal_run(
            admission, status="failed", minutes_ago=None, now=frozen
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_identical_finished_at_uses_pk_tiebreak(self):
        """R2: same finished_at -> highest PK wins (deterministic)."""
        frozen = timezone.now()
        patient = _make_patient("P13")
        admission = _make_admission(patient, "A13", days_ago=3)
        older_failure = _terminal_run(
            admission, status="failed", minutes_ago=10, now=frozen
        )
        # Same instant, created later (higher pk): a success -> guard reset.
        newer_success = _terminal_run(
            admission, status="succeeded", minutes_ago=10, now=frozen
        )
        newer_success.finished_at = older_failure.finished_at
        newer_success.save(update_fields=["finished_at"])

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is None

    def test_patient_without_admission_returns_none(self):
        """RED item 8: no Admission keeps the None contract."""
        frozen = timezone.now()
        patient = _make_patient("P14")

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is None

    def test_followup_parameters_and_batch_unchanged_by_guard(self):
        """RED item 9: guard only adds next_retry_at; nothing else changes."""
        frozen = timezone.now()
        patient = _make_patient("P15")
        _make_admission(patient, "A15", days_ago=3)
        batch = CensusExecutionBatch.objects.create(status="running")

        with _frozen_at(frozen):
            baseline = enqueue_most_recent_admission_full_sync(
                patient, batch=batch
            )
            failure = _terminal_run(
                Admission.objects.get(source_admission_key="ADM-A15"),
                status="failed",
                minutes_ago=10,
                now=frozen,
            )
            deferred = enqueue_most_recent_admission_full_sync(
                patient, batch=batch
            )

        assert baseline is not None and deferred is not None
        assert deferred.parameters_json == baseline.parameters_json
        assert deferred.batch_id == baseline.batch_id == batch.pk
        assert deferred.intent == baseline.intent == "full_sync"
        assert deferred.status == "queued"
        assert baseline.next_retry_at is None
        assert deferred.next_retry_at == failure.finished_at + timedelta(
            minutes=GUARD_MINUTES
        )

    def test_deferred_run_is_not_claimed_before_deadline(self):
        """Worker eligibility ignores the deferred row until next_retry_at."""
        frozen = timezone.now()
        patient = _make_patient("P16")
        _make_admission(patient, "A16", days_ago=3)
        _terminal_run(
            Admission.objects.get(source_admission_key="ADM-A16"),
            status="failed",
            minutes_ago=10,
            now=frozen,
        )

        with _frozen_at(frozen):
            run = enqueue_most_recent_admission_full_sync(patient)

        assert run is not None
        assert run.next_retry_at is not None
        with transaction.atomic():
            assert CurrentWorkerCommand._claim_eligible_run() is None
            assert PersistentWorkerCommand._claim_eligible_run() is None


# ---------------------------------------------------------------------------
# Manual full_admission_sync stays immediate (R7)
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client(client: Client, db: object) -> Client:
    """Return a Client logged in as a standard user."""
    from django.contrib.auth.models import User

    User.objects.create_user(username="htefs4user", password="htefs4pass")
    client.login(username="htefs4user", password="htefs4pass")
    return client


@pytest.mark.django_db
class TestManualFullAdmissionSyncImmediate:
    """The manual enqueue path (views) never applies the automatic guard."""

    def test_manual_full_admission_sync_view_is_immediate(
        self,
        auth_client: Client,
    ) -> None:
        """RED item 10: recent failure does not defer the manual run."""
        frozen = timezone.now()
        patient = _make_patient("M1")
        admission = _make_admission(patient, "M1-A", days_ago=3)
        admission_date = admission.admission_date
        assert admission_date is not None
        _terminal_run(
            admission,
            status="failed",
            intent="full_admission_sync",
            minutes_ago=10,
            now=frozen,
        )

        with _frozen_at(frozen):
            response = auth_client.post(
                reverse("ingestion:create_run"),
                {
                    "patient_record": patient.patient_source_key,
                    "start_date": admission_date.date().isoformat(),
                    "end_date": timezone.localtime(frozen)
                    .date()
                    .isoformat(),
                    "intent": "full_admission_sync",
                    "admission_id": str(admission.pk),
                    "admission_source_key": admission.source_admission_key,
                },
            )

        assert response.status_code == 302
        run = (
            IngestionRun.objects.filter(
                intent="full_admission_sync",
                parameters_json__admission_id=str(admission.pk),
            )
            .order_by("-pk")
            .first()
        )
        assert run is not None
        assert run.status == "queued"
        assert run.next_retry_at is None


# ---------------------------------------------------------------------------
# Intra-run retry regressions: BOTH workers unchanged (R8)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIntraRunRetryRegressions:
    """~+60s requeue for timeout and invalid_payload fail-fast remain."""

    @pytest.mark.parametrize("worker", ["current", "persistent"])
    def test_timeout_still_requeues_with_about_60_seconds(
        self, worker: str
    ) -> None:
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _mid_processing_run(batch)

        _worker_command(worker)._mark_run_failed(
            run, EvolutionPdfTimeoutError("deadline exceeded")
        )

        run.refresh_from_db()
        assert run.status == "queued"
        assert run.failure_reason == "timeout"
        assert run.finished_at is None
        now = timezone.now()
        assert run.next_retry_at is not None
        assert now + timedelta(seconds=45) <= run.next_retry_at
        assert run.next_retry_at <= now + timedelta(seconds=90)
        assert not FinalRunFailure.objects.filter(run=run).exists()

    @pytest.mark.parametrize("worker", ["current", "persistent"])
    def test_invalid_payload_stays_terminal_fail_fast(
        self, worker: str
    ) -> None:
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _mid_processing_run(batch)

        _worker_command(worker)._mark_run_failed(
            run, InvalidJsonError("expected array")
        )

        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"
        assert run.next_retry_at is None
        assert run.finished_at is not None
        assert run.failure_reason == "invalid_payload"
        failure = FinalRunFailure.objects.get(run=run)
        assert failure.attempts_exhausted == 1
        assert batch.status == "failed"


# ---------------------------------------------------------------------------
# Guard shape: named constant + sanitized helpers (R9/R10)
# ---------------------------------------------------------------------------


def test_guard_constant_is_fixed_60_minutes() -> None:
    """R9: the guard is a single named 60-minute constant (no backoff)."""
    import apps.ingestion.services as services

    guard = services._AUTOMATIC_FULL_SYNC_GUARD
    assert guard == timedelta(minutes=GUARD_MINUTES)


def test_guard_helpers_emit_no_sensitive_identifiers() -> None:
    """R10: helpers never interpolate identity keys or raw errors."""
    import apps.ingestion.services as services

    fragments = (
        inspect.getsource(services._latest_terminal_targeted_run),
        inspect.getsource(services._automatic_full_sync_not_before),
    )
    for fragment in fragments:
        for sentinel in (
            "patient_record",
            "source_admission_key",
            "error_message",
            "str(exc",
        ):
            assert sentinel not in fragment
