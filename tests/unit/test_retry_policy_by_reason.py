"""FX-S1: retry policy by failure class (deterministic payload fail-fast).

Covers:

- :func:`should_retry_failure_reason` (pure policy, no DB):
  ``invalid_payload`` is deterministic and MUST NOT be retried; every other
  reason (including ``timeout`` and empty) remains retryable.
- ``_mark_run_failed`` of BOTH workers
  (``process_ingestion_runs`` and
  ``process_ingestion_runs_persistent_session``):

  - ``InvalidJsonError`` (reason ``invalid_payload``) on the first attempt
    ends the run terminal ``failed`` with ``FinalRunFailure``
    (``attempts_exhausted=1``) and closes the drained batch;
  - ``EvolutionPdfTimeoutError`` (reason ``timeout``) keeps the existing
    requeue +60s regression;
  - ``attempt_count == max_attempts`` with a retryable reason stays
    terminal (unchanged);
  - a batch-bound empty admissions snapshot (RPAP-S2, reason
    ``invalid_payload``) also fails fast;
  - the fail-fast log line is aggregate-only (run label + reason, no
    ``str(exc)``, no identity sentinel).
"""

from __future__ import annotations

import importlib
from datetime import timedelta
from io import StringIO

import pytest
from django.utils import timezone

from apps.ingestion.extractors.errors import (
    EmptyAdmissionsSnapshotError,
    InvalidJsonError,
)
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
from apps.ingestion.run_lifecycle import safe_failure_text


def _lifecycle():
    """Import the shared lifecycle module lazily (FX-S1 RED: the pure policy
    does not exist yet, so the import fails inside the failing tests)."""
    return importlib.import_module("apps.ingestion.run_lifecycle")

# ---------------------------------------------------------------------------
# R1: pure retry policy
# ---------------------------------------------------------------------------


class TestShouldRetryFailureReason:
    """R1: deterministic payload failures must not burn retry attempts."""

    def test_invalid_payload_is_not_retryable(self):
        assert _lifecycle().should_retry_failure_reason("invalid_payload") is False

    def test_timeout_is_retryable(self):
        assert _lifecycle().should_retry_failure_reason("timeout") is True

    def test_unknown_reason_is_retryable(self):
        assert _lifecycle().should_retry_failure_reason("navigation") is True

    def test_empty_reason_is_retryable(self):
        assert _lifecycle().should_retry_failure_reason("") is True

    def test_other_taxonomy_reasons_are_retryable(self):
        for reason in ("source_unavailable", "validation_error", "unexpected_exception"):
            assert _lifecycle().should_retry_failure_reason(reason) is True

    def test_deterministic_set_is_pinned(self):
        assert _lifecycle()._DETERMINISTIC_FAILURE_REASONS == frozenset(
            {"invalid_payload"}
        )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FX_S1_SENTINEL = "SENSITIVE-IDENTITY-SEED-FX-S1"


def _make_run(
    *,
    batch: CensusExecutionBatch | None,
    attempt_count: int = 1,
    max_attempts: int = 3,
) -> IngestionRun:
    """Create a run mid-processing (status running, attempt in progress)."""
    run = IngestionRun.objects.create(
        status="running",
        intent="full_sync",
        batch=batch,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        parameters_json={
            "patient_record": "FXS1-P1",
            "intent": "full_sync",
        },
    )
    IngestionRunAttempt.objects.create(
        run=run,
        attempt_number=attempt_count,
    )
    return run


def _run_command(worker: str):
    """Instantiate the worker command with captured streams."""
    out, err = StringIO(), StringIO()
    if worker == "persistent":
        cmd: object = PersistentWorkerCommand(stdout=out, stderr=err)
    else:
        cmd = CurrentWorkerCommand(stdout=out, stderr=err)
    return cmd, out, err


def _assert_fail_fast_terminal(
    run: IngestionRun, batch: CensusExecutionBatch
) -> None:
    """Assert the terminal fail-fast contract on the first attempt."""
    run.refresh_from_db()
    batch.refresh_from_db()
    assert run.status == "failed"
    assert run.next_retry_at is None
    assert run.finished_at is not None
    assert run.failure_reason == "invalid_payload"
    assert run.timed_out is False
    assert run.error_message == safe_failure_text("invalid_payload")
    # Batch with no other queued/running runs closes as failed.
    assert batch.status == "failed"
    assert batch.finished_at is not None
    # Attempt record reflects the terminal attempt.
    attempt = run.attempts.order_by("-attempt_number").first()
    assert attempt is not None
    assert attempt.status == "failed"
    assert attempt.failure_reason == "invalid_payload"
    assert attempt.error_message == safe_failure_text("invalid_payload")
    # FinalRunFailure records the actual (reduced) attempt count.
    failure = FinalRunFailure.objects.get(run=run)
    assert failure.attempts_exhausted == run.attempt_count == 1


def _assert_requeued_regression(run: IngestionRun, batch: CensusExecutionBatch) -> None:
    """Assert the untouched timeout requeue +60s regression."""
    run.refresh_from_db()
    batch.refresh_from_db()
    assert run.status == "queued"
    assert run.finished_at is None
    assert run.failure_reason == "timeout"
    assert run.timed_out is True
    now = timezone.now()
    lower = now + timedelta(seconds=45)
    upper = now + timedelta(seconds=90)
    assert run.next_retry_at is not None
    assert lower <= run.next_retry_at <= upper
    assert FinalRunFailure.objects.filter(run=run).count() == 0
    assert batch.status == "running"
    assert batch.finished_at is None


# ---------------------------------------------------------------------------
# R2/R3/R4: persistent worker _mark_run_failed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkRunFailedPersistentWorker:
    """Persistent worker (production topology) fail-fast/regression."""

    def test_invalid_json_fails_fast_on_first_attempt(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, _, _ = _run_command("persistent")

        cmd._mark_run_failed(run, InvalidJsonError("expected array"))

        _assert_fail_fast_terminal(run, batch)

    def test_timeout_still_requeues_with_backoff(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, _, _ = _run_command("persistent")

        cmd._mark_run_failed(run, EvolutionPdfTimeoutError("deadline exceeded"))

        _assert_requeued_regression(run, batch)

    def test_exhausted_attempts_with_retryable_reason_stays_terminal(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=3, max_attempts=3)
        cmd, _, _ = _run_command("persistent")

        cmd._mark_run_failed(run, EvolutionPdfTimeoutError("deadline exceeded"))

        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"
        assert run.next_retry_at is None
        failure = FinalRunFailure.objects.get(run=run)
        assert failure.attempts_exhausted == 3
        assert batch.status == "failed"

    def test_batch_bound_empty_snapshot_fails_fast(self):
        """RPAP-S2: empty batch-bound capture is invalid_payload -> fail-fast."""
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, _, _ = _run_command("persistent")

        cmd._mark_run_failed(
            run, EmptyAdmissionsSnapshotError(EmptyAdmissionsSnapshotError.SANITIZED_MESSAGE)
        )

        _assert_fail_fast_terminal(run, batch)

    def test_fail_fast_log_is_sanitized_and_distinct(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, out, err = _run_command("persistent")
        exc = InvalidJsonError(f"payload broken at {FX_S1_SENTINEL}")

        cmd._mark_run_failed(run, exc)

        log = err.getvalue()
        assert "fail-fast" in log
        assert "invalid_payload" in log
        assert FX_S1_SENTINEL not in log
        assert "payload broken" not in log
        assert FX_S1_SENTINEL not in out.getvalue()


# ---------------------------------------------------------------------------
# R2/R3/R4: current worker _mark_run_failed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkRunFailedCurrentWorker:
    """Current worker shares the same retry-policy guard."""

    def test_invalid_json_fails_fast_on_first_attempt(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, _, _ = _run_command("current")

        cmd._mark_run_failed(run, InvalidJsonError("expected array"))

        _assert_fail_fast_terminal(run, batch)

    def test_timeout_still_requeues_with_backoff(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, _, _ = _run_command("current")

        cmd._mark_run_failed(run, EvolutionPdfTimeoutError("deadline exceeded"))

        _assert_requeued_regression(run, batch)

    def test_fail_fast_log_is_sanitized_and_distinct(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _make_run(batch=batch, attempt_count=1, max_attempts=3)
        cmd, out, err = _run_command("current")
        exc = InvalidJsonError(f"payload broken at {FX_S1_SENTINEL}")

        cmd._mark_run_failed(run, exc)

        log = err.getvalue()
        assert "fail-fast" in log
        assert "invalid_payload" in log
        assert FX_S1_SENTINEL not in log
        assert "payload broken" not in log
        assert FX_S1_SENTINEL not in out.getvalue()
