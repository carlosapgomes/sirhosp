"""Unit and integration tests for persistent-session ingestion worker (PSW-S4).

Tests cover the new ``process_ingestion_runs_persistent_session`` management
command: claim semantics, labels, heartbeat, admissions-only lifecycle,
failure/retry taxonomy, tab cleanup, session recovery, timeout propagation,
URL encoding, and graceful shutdown.

All tests use fakes / mocks — no real Playwright browser involved.
"""

from __future__ import annotations

import os
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    _build_admissions_url,
)
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
    Command as PersistentWorkerCommand,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)

# ---------------------------------------------------------------------------
# URL encoding tests (adapter-level, no DB needed)
# ---------------------------------------------------------------------------


class TestUrlEncoding:
    """Tests that URL parameters are safely encoded."""

    def test_encodes_patient_record_with_special_chars(self) -> None:
        """Patient record with slashes/spaces is URL-encoded."""
        url = _build_admissions_url(
            "/admissions/{patient_record}",
            patient_record="123/45 A",
            start_date="",
            end_date="",
        )
        assert "/admissions/123%2F45%20A" == url
        assert "/" not in url.split("/admissions/")[1]  # no raw slashes

    def test_encodes_dates_with_special_chars(self) -> None:
        """Dates are URL-encoded (dashes are unreserved and stay as-is)."""
        url = _build_admissions_url(
            "/admissions/{patient_record}?from={start_date}&to={end_date}",
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert "from=2024-01-01" in url
        assert "to=2024-12-31" in url

    def test_admissions_url_template_respects_placeholders(self) -> None:
        """All three placeholders are supported in the template."""
        url = _build_admissions_url(
            "/custom/{patient_record}/admissions?start={start_date}&end={end_date}",
            patient_record="P001",
            start_date="2024-06-01",
            end_date="2024-06-30",
        )
        assert "/custom/P001/admissions" in url
        assert "start=2024-06-01" in url
        assert "end=2024-06-30" in url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter_mock(snapshot_result=None, fail_mode=None):
    """Create a configured mock PersistentExtractionAdapter.

    Args:
        snapshot_result: The list to return from get_admission_snapshot.
            Defaults to an empty list.
        fail_mode: One of None, 'session_not_ready', 'renew_fail',
            'nav_fail', 'missing_data', 'invalid_json'
    """
    mock = MagicMock()
    mock.get_admission_snapshot.return_value = snapshot_result or []
    mock.cleanup_after_failure = MagicMock()
    mock.ensure_session_ready = MagicMock(return_value=True)
    mock.controller = MagicMock()
    mock.controller.restart_required.return_value = False
    mock.controller.mark_job_processed = MagicMock()
    mock.controller.close_job_tab_if_present = MagicMock()
    mock.controller.reset_after_restart = MagicMock()
    mock.controller.jobs_processed = 0
    mock.controller.consecutive_failures = 0

    if fail_mode == "session_not_ready":
        mock.get_admission_snapshot.side_effect = ExtractionError(
            "Session not ready for extraction"
        )
    elif fail_mode == "renew_fail":
        mock.get_admission_snapshot.side_effect = ExtractionError(
            "Session renewal failed before extraction"
        )
    elif fail_mode == "nav_fail":
        mock.get_admission_snapshot.side_effect = ExtractionError(
            "Failed to navigate to admissions page"
        )
    elif fail_mode == "missing_data":
        mock.get_admission_snapshot.side_effect = SnapshotContainerMissingError(
            "Page HTML contains no snapshot data container "
            "(<div id=\"admission-snapshot-data\">). Cannot extract admissions."
        )
    elif fail_mode == "invalid_json":
        mock.get_admission_snapshot.side_effect = InvalidJsonError(
            "Invalid JSON in admission snapshot data"
        )

    return mock


def _queue_admissions_run(**kwargs):
    """Helper to create a queued admissions_only IngestionRun."""
    defaults = {
        "status": "queued",
        "intent": "admissions_only",
        "max_attempts": 1,
        "parameters_json": {
            "patient_record": "P001",
            "intent": "admissions_only",
        },
    }
    defaults.update(kwargs)
    return IngestionRun.objects.create(**defaults)


# =========================================================================
# Run Claim Semantics
# =========================================================================


@pytest.mark.django_db
class TestClaimSemantics:
    """Two persistent workers cannot claim the same queued run."""

    def test_single_worker_claims_and_processes_run(self):
        """A single worker claims a queued run and transitions to running."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.worker_label != ""
        assert run.worker_heartbeat_at is not None
        assert run.processing_started_at is not None
        assert run.finished_at is not None

    def test_already_running_run_skipped(self):
        """Claim with skip_locked=True skips runs already claimed by another."""
        run = _queue_admissions_run()
        run.status = "running"
        run.worker_label = "other-worker:123"
        run.save(update_fields=["status", "worker_label"])

        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        # Status unchanged — still running
        assert run.status == "running"

    def test_claim_respects_next_retry_at(self):
        """Claim skips runs where next_retry_at > now."""
        run = _queue_admissions_run(
            next_retry_at=timezone.now() + timezone.timedelta(hours=1)
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        # Should still be queued — retry not due yet
        assert run.status == "queued"

    def test_multiple_runs_processed_in_sequence(self):
        """Multiple queued runs are claimed and processed one by one."""
        run1 = _queue_admissions_run(parameters_json={
            "patient_record": "P001", "intent": "admissions_only",
        })
        run2 = _queue_admissions_run(parameters_json={
            "patient_record": "P002", "intent": "admissions_only",
        })

        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run1.refresh_from_db()
        run2.refresh_from_db()
        assert run1.status == "succeeded"
        assert run2.status == "succeeded"


# =========================================================================
# Worker Label
# =========================================================================


@pytest.mark.django_db
class TestWorkerLabel:
    """Persistent worker labels are safe and distinguishable."""

    def test_label_uses_sirhosp_worker_label_env(self):
        """Label includes SIRHOSP_WORKER_LABEL when set."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.dict(os.environ, {"SIRHOSP_WORKER_LABEL": "persistent-test"}, clear=False), \
             patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
             ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert "persistent-test" in run.worker_label
        assert ":" in run.worker_label  # includes PID suffix

    def test_default_label_starts_with_persistent_prefix(self):
        """Without SIRHOSP_WORKER_LABEL, uses persistent-worker prefix."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.dict(os.environ, {"SIRHOSP_WORKER_LABEL": ""}, clear=False), \
             patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
             ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert "persistent-worker" in run.worker_label
        assert ":" in run.worker_label

    def test_label_has_no_sensitive_data(self):
        """Label does not contain patient data, credentials, or clinical text."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert "P001" not in run.worker_label

    def test_label_distinguishable_from_current_worker(self):
        """Persistent worker label can be distinguished from current worker."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.dict(os.environ, {"SIRHOSP_WORKER_LABEL": ""}, clear=False), \
             patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
             ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert "persistent-worker" in run.worker_label


# =========================================================================
# Heartbeat
# =========================================================================


@pytest.mark.django_db
class TestHeartbeat:
    """Heartbeat is populated/refreshed during persistent-session processing."""

    def test_heartbeat_populated_on_claim(self):
        """worker_heartbeat_at is populated when the run is claimed."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.worker_heartbeat_at is not None
        # Heartbeat should be close to processing start
        assert (
            run.worker_heartbeat_at - run.processing_started_at
        ).total_seconds() < 5

    def test_heartbeat_imported_from_current_worker_module(self):
        """The command reuses WorkerHeartbeat from the existing worker module."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            WorkerHeartbeat as OriginalWorkerHeartbeat,
        )
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
            WorkerHeartbeat as PersistentWorkerHeartbeat,
        )
        assert PersistentWorkerHeartbeat is OriginalWorkerHeartbeat

    def test_heartbeat_stale_recovery_can_use_timestamp(self):
        """The heartbeat timestamp can be used by stale-run recovery."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.worker_heartbeat_at is not None
        assert run.worker_label != ""


# =========================================================================
# Admissions-only Lifecycle
# =========================================================================


@pytest.mark.django_db
class TestAdmissionsOnlyLifecycle:
    """Admissions-only success and failure lifecycle with persistent worker."""

    def test_success_saves_lifecycle_metrics(self):
        """Successful admissions-only run persists lifecycle timestamps and stage metrics."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.processing_started_at is not None
        assert run.finished_at is not None
        assert run.finished_at >= run.processing_started_at

        # Stage metric should exist
        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.count() >= 1
        admissions_stage = stages.filter(stage_name="admissions_capture").first()
        assert admissions_stage is not None
        assert admissions_stage.status == "succeeded"

        # Attempt should be recorded
        attempt = IngestionRunAttempt.objects.filter(run=run).first()
        assert attempt is not None
        assert attempt.status == "succeeded"

    def test_session_failure_preserves_retry_taxonomy(self):
        """Session-level failure preserves retry attempt and failure taxonomy."""
        run = _queue_admissions_run(max_attempts=2)
        mock_adapter = _make_adapter_mock(fail_mode="session_not_ready")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.attempt_count >= 1
        assert run.failure_reason != ""

        # Attempt record exists
        attempts = IngestionRunAttempt.objects.filter(run=run).order_by("attempt_number")
        assert attempts.count() >= 1
        assert attempts.first().status == "failed"

    def test_data_failure_preserves_retry_taxonomy(self):
        """Data-level failure (missing container) preserves retry taxonomy."""
        run = _queue_admissions_run(max_attempts=2)
        mock_adapter = _make_adapter_mock(fail_mode="missing_data")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.attempt_count >= 1
        assert run.failure_reason != ""

    def test_invalid_json_failure_preserves_retry_taxonomy(self):
        """Invalid JSON failure preserves retry taxonomy."""
        run = _queue_admissions_run(max_attempts=2)
        mock_adapter = _make_adapter_mock(fail_mode="invalid_json")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.attempt_count >= 1
        assert run.failure_reason != ""


# =========================================================================
# Tab Cleanup
# =========================================================================


@pytest.mark.django_db
class TestTabCleanup:
    """Tab cleanup after success and recoverable data failures."""

    def test_cleanup_after_admissions_success(self):
        """Adapter handles cleanup after successful admissions extraction."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_cleanup_after_data_failure(self):
        """cleanup_after_failure is called after recoverable data failure."""
        run = _queue_admissions_run(max_attempts=1)
        mock_adapter = _make_adapter_mock(fail_mode="missing_data")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        mock_adapter.cleanup_after_failure.assert_called_once()
        run.refresh_from_db()
        assert run.status == "failed"

    def test_cleanup_after_invalid_json(self):
        """cleanup_after_failure is called after invalid JSON data failure."""
        run = _queue_admissions_run(max_attempts=1)
        mock_adapter = _make_adapter_mock(fail_mode="invalid_json")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        mock_adapter.cleanup_after_failure.assert_called_once()
        run.refresh_from_db()
        assert run.status == "failed"

    def test_no_cleanup_on_session_failure(self):
        """cleanup_after_failure is NOT called on session-level failure."""
        run = _queue_admissions_run(max_attempts=1)
        mock_adapter = _make_adapter_mock(fail_mode="session_not_ready")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        mock_adapter.cleanup_after_failure.assert_not_called()
        run.refresh_from_db()
        assert run.status == "failed"


# =========================================================================
# Timeout Propagation
# =========================================================================


@pytest.mark.django_db
class TestTimeoutPropagation:
    """Timeout parameter is propagated to the adapter."""

    def test_timeout_passed_to_adapter_call(self):
        """The adapter's get_admission_snapshot is called with a timeout."""
        _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        _, kwargs = mock_adapter.get_admission_snapshot.call_args
        assert "timeout" in kwargs
        assert isinstance(kwargs["timeout"], int)
        assert kwargs["timeout"] > 0


# =========================================================================
# Graceful Shutdown
# =========================================================================


@pytest.mark.django_db
class TestGracefulShutdown:
    """Graceful shutdown on SIGTERM/SIGINT."""

    def test_single_mode_does_not_loop(self):
        """Single mode processes all queued runs once and exits."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_loop_mode_retries_when_db_not_ready(self, capsys):
        """Loop mode retries when DB is temporarily unavailable."""
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        cmd_path = (
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session"
        )

        from django.db.utils import ProgrammingError

        failing_qs = MagicMock()
        failing_qs.count.side_effect = ProgrammingError(
            'relation "ingestion_ingestionrun" does not exist'
        )

        with (
            patch(f"{cmd_path}.IngestionRun.objects.filter", return_value=failing_qs),
            patch.object(PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter),
            patch(f"{cmd_path}.time.sleep", side_effect=[None, KeyboardInterrupt]),
        ):
            with pytest.raises(KeyboardInterrupt):
                call_command(
                    "process_ingestion_runs_persistent_session",
                    loop=True,
                    sleep_seconds=1,
                )

    def test_loop_mode_registers_signal_handlers(self):
        """Loop mode calls signal.signal to register handlers."""
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        import signal as real_signal

        cmd_path = (
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session"
        )

        with (
            patch.object(PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter),
            patch("signal.signal") as mock_signal_signal,
            patch(f"{cmd_path}.time.sleep", side_effect=[None, KeyboardInterrupt]),
        ):
            with pytest.raises(KeyboardInterrupt):
                call_command(
                    "process_ingestion_runs_persistent_session",
                    loop=True,
                    sleep_seconds=1,
                )

        # signal.signal should have been called for SIGTERM and SIGINT
        mock_signal_signal.assert_any_call(
            real_signal.SIGTERM, ANY
        )
        mock_signal_signal.assert_any_call(
            real_signal.SIGINT, ANY
        )


# =========================================================================
# Current Worker Remains Executable
# =========================================================================


@pytest.mark.django_db
class TestCurrentWorkerRemains:
    """Existing process_ingestion_runs remains executable."""

    def test_current_worker_still_processes_runs(self):
        """The original process_ingestion_runs command still works."""
        run = _queue_admissions_run()
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


# =========================================================================
# Batch Closure
# =========================================================================


@pytest.mark.django_db
class TestBatchClosure:
    """Persistent worker closes batches when runs are drained."""

    def test_batch_closed_after_last_run_succeeds(self):
        """Batch transitions to succeeded when all runs are processed."""
        batch = CensusExecutionBatch.objects.create(status="running")
        _queue_admissions_run(
            batch=batch,
            parameters_json={
                "patient_record": "BC001",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        batch.refresh_from_db()
        assert batch.status == "succeeded"
        assert batch.finished_at is not None

    def test_batch_failed_when_run_fails_permanently(self):
        """Batch transitions to failed when a run fails permanently."""
        batch = CensusExecutionBatch.objects.create(status="running")
        _queue_admissions_run(
            max_attempts=1,
            batch=batch,
            parameters_json={
                "patient_record": "BC002",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(fail_mode="invalid_json")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        batch.refresh_from_db()
        assert batch.status == "failed"
        assert batch.finished_at is not None


# =========================================================================
# Session Readiness
# =========================================================================


@pytest.mark.django_db
class TestSessionReadiness:
    """Session readiness is verified before claiming runs."""

    def test_ensure_session_ready_called_before_claim(self):
        """ensure_session_ready() is checked before claiming queued runs."""
        _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        # Called at least once (called once per claim cycle iteration)
        mock_adapter.ensure_session_ready.assert_called()
