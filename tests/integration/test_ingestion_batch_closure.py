"""Integration tests for final failure and batch closure (Slice CQM-S4).

Tests:
- FinalRunFailure created when retries are exhausted (3 failures).
- Batch closed automatically when no queued/running runs remain.
- Batch duration is computable (enqueue_finished_at -> finished_at).
- Batch final status is 'succeeded' when all runs succeed,
  'failed' when any FinalRunFailure exists.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
)


# RPAP-S2 (Emenda 1): minimal synthetic NON-empty snapshot used to repair
# batch-closure fixtures. Same shape as ``ADM_BATCH_001`` in
# ``tests/integration/test_ingestion_worker_retries.py``. A batch-bound empty
# capture is now an invalid payload (fail-closed), so fixtures that codified
# the old "empty batch-bound = success" semantics carry a valid capture
# instead; every original assertion is preserved.
def _batch_admissions_snapshot(key: str = "ADM_BATCH_001") -> list[dict]:
    return [
        {
            "admission_key": key,
            "admission_start": "2026-04-01T00:00:00",
            "admission_end": "2026-04-19T00:00:00",
            "ward": "UTI",
            "bed": "LEITO 01",
        }
    ]


# Follow-up isolation for the repaired fixtures: a successful batch-bound
# capture enqueues a demographics_only follow-up (batch-detached) and a
# full_sync follow-up attached to the batch. The attached child would keep
# the batch open, so the repaired closure tests isolate BOTH enqueuers.
_CURRENT_DEMO_FOLLOWUP = (
    "apps.ingestion.management.commands"
    ".process_ingestion_runs.queue_demographics_only_run"
)
_CURRENT_FULLSYNC_FOLLOWUP = (
    "apps.ingestion.services.enqueue_most_recent_admission_full_sync"
)


@pytest.mark.django_db
class TestFinalRunFailureCreation:
    """FinalRunFailure is persisted when retries are exhausted."""

    def _queue_run(self, batch, patient_record="FAIL_P1", **kwargs):
        defaults = {
            "status": "queued",
            "intent": "admissions_only",
            "batch": batch,
            "attempt_count": 2,  # 2 prior attempts done
            "parameters_json": {
                "patient_record": patient_record,
                "intent": "admissions_only",
            },
        }
        defaults.update(kwargs)
        run = IngestionRun.objects.create(**defaults)
        # Create prior attempt records
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=i,
                status="failed",
                failure_reason="source_unavailable",
                error_message=f"Previous error attempt {i}",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )
        return run

    def test_terminal_failure_creates_final_run_failure(self):
        """When a run fails on its 3rd attempt, a FinalRunFailure is created."""
        from apps.ingestion.extractors.errors import ExtractionError

        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._queue_run(batch=batch, patient_record="FF_P1")

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = ExtractionError(
            "Persistent error"
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.attempt_count == 3

        # FinalRunFailure must exist
        failure = FinalRunFailure.objects.filter(run=run).first()
        assert failure is not None
        assert failure.patient_record == "FF_P1"
        assert failure.intent == "admissions_only"
        assert failure.batch_id == batch.pk
        assert failure.attempts_exhausted == 3
        assert failure.failed_at is not None

    def test_final_run_failure_not_created_on_retry(self):
        """When a run fails on attempt 1 or 2, NO FinalRunFailure is created."""
        from apps.ingestion.extractors.errors import ExtractionError

        batch = CensusExecutionBatch.objects.create(status="running")
        # attempt_count=0 (first attempt)
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "NOFF_P1",
                "intent": "admissions_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = ExtractionError(
            "Transient error"
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "queued"  # requeued for retry
        assert run.attempt_count == 1

        # No FinalRunFailure
        assert FinalRunFailure.objects.filter(run=run).count() == 0

    def test_final_run_failure_for_demographics_only(self):
        """FinalRunFailure records intent correctly for demographics_only."""
        from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            batch=batch,
            attempt_count=2,
            parameters_json={
                "patient_record": "FF_DEMO_P1",
                "intent": "demographics_only",
            },
        )
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=i,
                status="failed",
                failure_reason="timeout",
                error_message=f"Timeout attempt {i}",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )

        with patch(
            "apps.ingestion.extractors.subprocess_utils.run_subprocess",
            side_effect=SubprocessTimeoutError(
                cmd=["python", "fake.py"],
                timeout=300,
            ),
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.DEMOGRAPHICS_SCRIPT_PATH",
            "/fake/path.py",
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"

        failure = FinalRunFailure.objects.filter(run=run).first()
        assert failure is not None
        assert failure.patient_record == "FF_DEMO_P1"
        assert failure.intent == "demographics_only"


@pytest.mark.django_db
class TestBatchClosure:
    """Batch closes automatically when no active runs remain."""

    def test_batch_closes_when_last_run_succeeds(self):
        """Batch finished_at is set when the last queued/running run succeeds."""
        enqueue_time = timezone.now() - timedelta(minutes=10)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "CLOSE_P1",
                "intent": "admissions_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = _batch_admissions_snapshot()

        # RPAP-S2 fixture repair: non-empty batch-bound capture (empty is now
        # fail-closed). Follow-ups are isolated so the batch drains after the
        # successful run, preserving the original closure assertions.
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(_CURRENT_DEMO_FOLLOWUP), patch(_CURRENT_FULLSYNC_FOLLOWUP):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

        batch.refresh_from_db()
        assert batch.finished_at is not None
        assert batch.status == "succeeded"
        # Duration must be computable
        assert batch.total_duration_seconds is not None
        assert batch.total_duration_seconds >= 0

    def test_batch_closes_when_last_full_sync_run_skips_extraction(self):
        """Batch closes on full_sync success even when extraction is skipped."""
        enqueue_time = timezone.now() - timedelta(minutes=10)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            batch=batch,
            parameters_json={
                "patient_record": "FULL_SKIP_P1",
                "start_date": "2026-04-01",
                "end_date": "2026-04-05",
                "intent": "full_sync",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = _batch_admissions_snapshot()

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.plan_extraction_windows",
            return_value={
                "gaps": [],
                "windows": [],
                "skip_extraction": True,
            },
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

        latest_attempt = (
            IngestionRunAttempt.objects.filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        assert latest_attempt is not None
        assert latest_attempt.status == "succeeded"
        assert latest_attempt.finished_at is not None

        batch.refresh_from_db()
        assert batch.finished_at is not None
        assert batch.status == "succeeded"

    def test_batch_closes_when_last_run_fails_permanently(self):
        """Batch finished_at is set when the last run exhausts retries."""
        from apps.ingestion.extractors.errors import ExtractionError

        enqueue_time = timezone.now() - timedelta(minutes=5)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            parameters_json={
                "patient_record": "CLOSE_FAIL_P1",
                "intent": "admissions_only",
            },
        )
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=i,
                status="failed",
                failure_reason="source_unavailable",
                error_message=f"Error attempt {i}",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = ExtractionError(
            "Persistent error"
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"

        batch.refresh_from_db()
        assert batch.finished_at is not None
        # Batch has failures → status should be 'failed'
        assert batch.status == "failed"
        assert batch.total_duration_seconds is not None

    def test_batch_stays_running_while_other_runs_are_queued(self):
        """Batch does NOT close while other runs are still queued."""
        batch = CensusExecutionBatch.objects.create(status="running")

        # Run 1: will succeed
        run1 = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "STAY_P1",
                "intent": "admissions_only",
            },
        )
        # Run 2: stays queued (won't be processed in this call)
        run2 = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            batch=batch,
            parameters_json={
                "patient_record": "STAY_P2",
                "intent": "demographics_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = _batch_admissions_snapshot()

        # Patch demographics to prevent run2 from being processed
        # The worker processes one run at a time; after run1 succeeds,
        # run2 is still queued, so batch should NOT close.
        # We achieve this by patching demographics to hang/fail,
        # but simpler: just verify the batch state after run1 completes.
        # The worker loop processes all eligible runs, so we need run2
        # to have a future next_retry_at to prevent processing.
        run2.next_retry_at = timezone.now() + timedelta(hours=1)
        run2.save(update_fields=["next_retry_at"])

        # RPAP-S2 fixture repair: non-empty capture + follow-up isolation so
        # run1's enqueued full_sync child cannot alter batch drainage.
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(_CURRENT_DEMO_FOLLOWUP), patch(_CURRENT_FULLSYNC_FOLLOWUP):
            call_command("process_ingestion_runs")

        run1.refresh_from_db()
        assert run1.status == "succeeded"

        run2.refresh_from_db()
        assert run2.status == "queued"  # not processed yet

        batch.refresh_from_db()
        # Batch should NOT be closed — run2 is still queued
        assert batch.finished_at is None
        assert batch.status == "running"

    def test_batch_closes_after_both_runs_complete(self):
        """Batch closes when both runs in the batch complete."""
        enqueue_time = timezone.now() - timedelta(minutes=8)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        for rec in ("BOTH_P1", "BOTH_P2"):
            IngestionRun.objects.create(
                status="queued",
                intent="admissions_only",
                batch=batch,
                parameters_json={
                    "patient_record": rec,
                    "intent": "admissions_only",
                },
            )

        mock_ext = MagicMock()
        # RPSA-S1: admission identity matching is patient-scoped and the
        # (source_system, source_admission_key) constraint is globally
        # unique, so each patient's capture carries its own admission key.
        # Reusing one key across patients now fails the run with
        # IntegrityError instead of silently mutating the first patient's
        # admission (pre-fixture-repair behavior).
        snapshots_by_patient = {
            "BOTH_P1": _batch_admissions_snapshot("ADM_BATCH_001"),
            "BOTH_P2": _batch_admissions_snapshot("ADM_BATCH_002"),
        }
        mock_ext.get_admission_snapshot.side_effect = (
            lambda **kwargs: snapshots_by_patient[kwargs["patient_record"]]
        )

        # RPAP-S2 fixture repair: non-empty captures + follow-up isolation so
        # both runs drain the batch after succeeding.
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(_CURRENT_DEMO_FOLLOWUP), patch(_CURRENT_FULLSYNC_FOLLOWUP):
            call_command("process_ingestion_runs")

        batch.refresh_from_db()
        assert batch.finished_at is not None
        assert batch.status == "succeeded"
        assert batch.total_duration_seconds is not None

    def test_batch_status_failed_when_any_final_failure_exists(self):
        """Batch status is 'failed' if at least one FinalRunFailure exists."""
        from apps.ingestion.extractors.errors import ExtractionError

        enqueue_time = timezone.now() - timedelta(minutes=3)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        # Run 1: will succeed
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "MIX_P1",
                "intent": "admissions_only",
            },
        )
        # Run 2: will fail permanently (2 prior attempts)
        run2 = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            parameters_json={
                "patient_record": "MIX_P2",
                "intent": "admissions_only",
            },
        )
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run2,
                attempt_number=i,
                status="failed",
                failure_reason="source_unavailable",
                error_message=f"Error {i}",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )

        call_count = {"n": 0}

        def snapshot_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                # First call (run1): success — RPAP-S2 fixture repair uses a
                # non-empty batch-bound capture (empty is now fail-closed).
                return _batch_admissions_snapshot()
            # Second call (run2): persistent failure
            raise ExtractionError("Persistent")

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = snapshot_side_effect

        # RPAP-S2 fixture repair: run1's follow-ups are isolated so the batch
        # drains when MIX_P2 fails terminally (original assertions intact).
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(_CURRENT_DEMO_FOLLOWUP), patch(_CURRENT_FULLSYNC_FOLLOWUP):
            call_command("process_ingestion_runs")

        batch.refresh_from_db()
        assert batch.finished_at is not None
        # Has at least one failure → batch status = 'failed'
        assert batch.status == "failed"


@pytest.mark.django_db
class TestBatchDurationComputability:
    """Batch duration is computable from enqueue_finished_at to finished_at."""

    def test_duration_computable_after_closure(self):
        """total_duration_seconds returns a value after batch closure."""
        enqueue_time = timezone.now() - timedelta(minutes=15)
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=enqueue_time,
        )

        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "DUR_P1",
                "intent": "admissions_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = _batch_admissions_snapshot()

        # RPAP-S2 fixture repair: non-empty capture + follow-up isolation so
        # the run drains the batch and the duration becomes computable.
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(_CURRENT_DEMO_FOLLOWUP), patch(_CURRENT_FULLSYNC_FOLLOWUP):
            call_command("process_ingestion_runs")

        batch.refresh_from_db()
        assert batch.finished_at is not None
        assert batch.enqueue_finished_at is not None
        duration = batch.total_duration_seconds
        assert duration is not None
        # Duration should be positive (finished_at > enqueue_finished_at)
        assert duration >= 0

    def test_duration_none_when_batch_not_closed(self):
        """total_duration_seconds is None when batch is still running."""
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=timezone.now(),
        )
        assert batch.total_duration_seconds is None
