"""Integration tests for IngestionRun retry engine (Slice CQM-S3).

Tests the retry logic in the worker:
- Failure on attempt 1/2 → requeue with next_retry_at=now+60s
- Success on retry → run status=succeeded
- Cap at 3 total attempts (no requeue after 3rd failure)
- IngestionRunAttempt persisted for each attempt
- full_sync auto-enqueued inherits batch_id from source run
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunAttempt,
)


@pytest.mark.django_db
class TestWorkerRetryOnFailure:
    """Worker requeues failed runs for retry with backoff."""

    def _queue_run(self, **kwargs):
        """Helper to create a queued IngestionRun with admissions_only intent."""
        defaults = {
            "status": "queued",
            "intent": "admissions_only",
            "parameters_json": {
                "patient_record": "RETRY_P1",
                "intent": "admissions_only",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def _make_extractor_mock(self, admissions_snapshot=None, admission_error=None):
        mock_ext = MagicMock()
        if admission_error:
            mock_ext.get_admission_snapshot.side_effect = admission_error
        elif admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def _patch_and_call(self, mock_ext):
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

    def test_fail_on_attempt_1_requeues_with_backoff(self):
        """Run failing on attempt 1 transitions back to queued with next_retry_at."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Transient source error"),
        )

        before = timezone.now()
        self._patch_and_call(mock_ext)
        after = timezone.now()

        run.refresh_from_db()
        # Run should be requeued, not terminally failed
        assert run.status == "queued"
        assert run.attempt_count == 1
        assert run.next_retry_at is not None
        # next_retry_at should be approximately now + 60s
        assert run.next_retry_at >= before + timedelta(seconds=59)
        assert run.next_retry_at <= after + timedelta(seconds=61)

        # An IngestionRunAttempt should be recorded
        attempts = IngestionRunAttempt.objects.filter(run=run).order_by("attempt_number")
        assert attempts.count() == 1
        attempt = attempts.first()
        assert attempt.attempt_number == 1
        assert attempt.status == "failed"
        assert attempt.finished_at is not None

    def test_fail_on_attempt_2_requeues_with_backoff(self):
        """Run failing on attempt 2 also requeues with backoff."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        # Simulate already having completed attempt 1
        run.attempt_count = 1
        run.status = "queued"
        run.save(update_fields=["attempt_count", "status"])
        # Create the attempt record for attempt 1
        IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="failed",
            failure_reason="source_unavailable",
            error_message="Previous transient error",
            finished_at=timezone.now() - timedelta(seconds=70),
        )

        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Transient source error"),
        )

        before = timezone.now()
        self._patch_and_call(mock_ext)
        after = timezone.now()

        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 2
        assert run.next_retry_at is not None
        assert run.next_retry_at >= before + timedelta(seconds=59)
        assert run.next_retry_at <= after + timedelta(seconds=61)

        # Two attempts total
        attempts = IngestionRunAttempt.objects.filter(run=run).order_by("attempt_number")
        assert attempts.count() == 2

    def test_fail_on_attempt_3_is_terminal(self):
        """Run failing on attempt 3 does NOT requeue (max attempts reached)."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        # Simulate already having completed attempts 1 and 2
        run.attempt_count = 2
        run.status = "queued"
        run.save(update_fields=["attempt_count", "status"])
        # Create attempt records for attempts 1 and 2
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=i,
                status="failed",
                failure_reason="source_unavailable",
                error_message=f"Previous error attempt {i}",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )

        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Persistent source error"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        # Run should be terminally failed, NOT requeued
        assert run.status == "failed"
        assert run.attempt_count == 3
        assert run.next_retry_at is None
        assert run.finished_at is not None

        # Three attempts recorded
        attempts = IngestionRunAttempt.objects.filter(run=run).order_by("attempt_number")
        assert attempts.count() == 3
        last_attempt = attempts.last()
        assert last_attempt.attempt_number == 3
        assert last_attempt.status == "failed"

    def test_success_on_retry_reaches_succeeded(self):
        """Run that fails on attempt 1 but succeeds on attempt 2 → status=succeeded."""
        from apps.ingestion.extractors.errors import ExtractionError

        # Pre-create patient so admissions can succeed on retry
        from apps.patients.models import Patient

        Patient.objects.create(
            source_system="tasy",
            patient_source_key="RETRY_P1",
            name="PACIENTE RETRY",
        )

        run = self._queue_run()
        call_count = {"n": 0}
        admission_error = ExtractionError("First attempt transient error")

        def get_admission_snapshot_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise admission_error
            # Success on subsequent calls
            return [
                {
                    "admission_key": "ADM_RETRY_001",
                    "admission_start": "2026-04-01T00:00:00",
                    "admission_end": "2026-04-19T00:00:00",
                    "ward": "UTI",
                    "bed": "LEITO 01",
                }
            ]

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = (
            get_admission_snapshot_side_effect
        )

        # First call: fails → requeued
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "queued"  # requeued for retry
        assert run.attempt_count == 1

        # Force next_retry_at to the past so claim picks it up
        run.next_retry_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["next_retry_at"])

        # Second call: succeeds
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.attempt_count == 2
        assert run.finished_at is not None

        # Both attempts recorded
        attempts = IngestionRunAttempt.objects.filter(run=run).order_by("attempt_number")
        assert attempts.count() == 2
        assert attempts.filter(attempt_number=1, status="failed").exists()
        assert attempts.filter(attempt_number=2, status="succeeded").exists()

    def test_requeued_run_not_picked_until_next_retry_at(self):
        """Requeued run is not processed again until next_retry_at has passed."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Transient error"),
        )

        # First call: fails → requeued with next_retry_at in the future
        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "queued"
        assert run.next_retry_at is not None
        # next_retry_at should be in the future
        assert run.next_retry_at > timezone.now()

        # Second call: should NOT pick up this run (next_retry_at in the future)
        mock_ext_success = self._make_extractor_mock(admissions_snapshot=[])
        self._patch_and_call(mock_ext_success)

        run.refresh_from_db()
        # Still queued (not processed yet because next_retry_at is in the future)
        assert run.status == "queued"
        assert run.attempt_count == 1  # still 1

    def test_attempt_records_failure_reason_and_error_message(self):
        """IngestionRunAttempt captures failure_reason and error_message."""
        from apps.ingestion.extractors.errors import ExtractionTimeoutError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionTimeoutError("Timed out after 120s"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "queued"  # requeued

        attempt = IngestionRunAttempt.objects.filter(run=run).first()
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.failure_reason == "timeout"
        assert attempt.timed_out is True
        assert "timed out" in attempt.error_message.lower()


@pytest.mark.django_db
class TestWorkerRetryClaimLogic:
    """Worker claim logic respects next_retry_at for eligible runs."""

    def test_claim_skips_run_with_future_retry_at(self):
        """Worker does not pick up a run whose next_retry_at is in the future."""
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            attempt_count=1,
            next_retry_at=timezone.now() + timedelta(seconds=120),
            parameters_json={
                "patient_record": "CLAIM_P1",
                "intent": "admissions_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = []

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        # Should still be queued — not picked up
        assert run.status == "queued"
        assert run.attempt_count == 1

    def test_claim_picks_run_with_past_retry_at(self):
        """Worker picks up a run whose next_retry_at is in the past."""
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            attempt_count=1,
            next_retry_at=timezone.now() - timedelta(seconds=10),
            parameters_json={
                "patient_record": "CLAIM_P2",
                "intent": "admissions_only",
            },
        )

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = []

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        # Should be picked up and succeed
        assert run.status == "succeeded"
        assert run.attempt_count == 2

    def test_claim_picks_run_with_null_retry_at(self):
        """Worker picks up a run with next_retry_at=None (first attempt)."""
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": "CLAIM_P3",
                "intent": "admissions_only",
            },
        )
        assert run.next_retry_at is None

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = []

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.attempt_count == 1


@pytest.mark.django_db
class TestWorkerRetryBatchInheritance:
    """full_sync auto-enqueued after admissions_only inherits batch_id."""

    def _make_extractor_mock(self, admissions_snapshot=None):
        mock_ext = MagicMock()
        if admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def test_full_sync_inherits_batch_from_admissions_only(self):
        """Auto-enqueued full_sync run inherits batch from the source run."""

        batch = CensusExecutionBatch.objects.create(status="running")
        admissions_snapshot = [
            {
                "admission_key": "ADM_BATCH_001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            }
        ]
        mock_ext = self._make_extractor_mock(admissions_snapshot=admissions_snapshot)

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "BATCH_P1",
                "intent": "admissions_only",
            },
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

        # Check that a full_sync run was auto-enqueued with the same batch
        full_sync_runs = IngestionRun.objects.filter(
            intent="full_sync",
            parameters_json__patient_record="BATCH_P1",
        )
        assert full_sync_runs.count() == 1
        full_sync_run = full_sync_runs.first()
        # The key assertion: batch inherited from source run
        assert full_sync_run.batch_id == batch.pk
        # Note: full_sync may be processed in the same worker loop,
        # so status could be 'queued' or 'succeeded' depending on timing.
        assert full_sync_run.status in ("queued", "succeeded")

    def test_full_sync_inherits_batch_even_on_retry(self):
        """When admissions_only succeeds on retry, full_sync still inherits batch."""
        from apps.ingestion.extractors.errors import ExtractionError
        from apps.patients.models import Patient

        batch = CensusExecutionBatch.objects.create(status="running")

        Patient.objects.create(
            source_system="tasy",
            patient_source_key="BATCH_P2",
            name="PACIENTE BATCH",
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            parameters_json={
                "patient_record": "BATCH_P2",
                "intent": "admissions_only",
            },
        )

        call_count = {"n": 0}

        def get_admission_snapshot_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ExtractionError("First attempt transient error")
            return [
                {
                    "admission_key": "ADM_BATCH_002",
                    "admission_start": "2026-04-01T00:00:00",
                    "admission_end": "2026-04-19T00:00:00",
                    "ward": "UTI",
                    "bed": "LEITO 01",
                }
            ]

        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = (
            get_admission_snapshot_side_effect
        )

        # First call: fails → requeued
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 1

        # Force next_retry_at to the past
        run.next_retry_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["next_retry_at"])

        # Second call: succeeds → auto-enqueues full_sync
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

        full_sync_runs = IngestionRun.objects.filter(
            intent="full_sync",
            parameters_json__patient_record="BATCH_P2",
        )
        assert full_sync_runs.count() == 1
        full_sync_run = full_sync_runs.first()
        assert full_sync_run.batch_id == batch.pk


@pytest.mark.django_db
class TestWorkerRetryDemographicsOnly:
    """Retry engine works for demographics_only intent too."""

    def _queue_demographics_run(self, patient_record="RETRY_DEMO"):
        return IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        )

    def test_demographics_only_fail_requeues(self):
        """demographics_only run that fails on attempt 1 is requeued."""
        from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError

        run = self._queue_demographics_run()

        with patch(
            "apps.ingestion.extractors.subprocess_utils.run_subprocess",
            side_effect=SubprocessTimeoutError(
                cmd=["python", "fake_script.py"],
                timeout=300,
            ),
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.DEMOGRAPHICS_SCRIPT_PATH",
            "/fake/path.py",
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        # Should be requeued (attempt 1 of 3)
        assert run.status == "queued"
        assert run.attempt_count == 1
        assert run.next_retry_at is not None
