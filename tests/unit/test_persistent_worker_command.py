"""Unit and integration tests for persistent-session ingestion worker (PSW-S4).

Tests cover the new ``process_ingestion_runs_persistent_session`` management
command: claim semantics, labels, heartbeat, admissions-only lifecycle,
failure/retry taxonomy, tab cleanup, session recovery, timeout propagation,
URL encoding, and graceful shutdown.

All tests use fakes / mocks — no real Playwright browser involved.
"""

from __future__ import annotations

import datetime
import os
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
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


def _make_adapter_mock(
    snapshot_result=None,
    fail_mode=None,
    demographics_result=None,
    demographics_fail_mode=None,
):
    """Create a configured mock PersistentExtractionAdapter.

    Args:
        snapshot_result: The list to return from get_admission_snapshot.
            Defaults to an empty list.
        fail_mode: One of None, 'session_not_ready', 'renew_fail',
            'nav_fail', 'missing_data', 'invalid_json'
        demographics_result: The dict to return from get_demographics.
            Defaults to an empty dict.
        demographics_fail_mode: One of None, 'extraction_error',
            'invalid_json', 'missing_data'.
    """
    mock = MagicMock()
    mock.get_admission_snapshot.return_value = snapshot_result or []
    mock.get_demographics.return_value = (
        demographics_result if demographics_result is not None else {}
    )
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

    if demographics_fail_mode == "extraction_error":
        mock.get_demographics.side_effect = ExtractionError(
            "Demographics extraction failed"
        )
    elif demographics_fail_mode == "invalid_json":
        mock.get_demographics.side_effect = InvalidJsonError(
            "Invalid JSON in demographics data"
        )
    elif demographics_fail_mode == "missing_data":
        mock.get_demographics.side_effect = SnapshotContainerMissingError(
            "Page HTML contains no demographics data container."
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


# =========================================================================
# Full-sync Lifecycle (PSW-S8)
# =========================================================================


def _queue_full_sync_run(**kwargs):
    """Helper to create a queued full_sync IngestionRun."""
    defaults = {
        "status": "queued",
        "intent": "full_sync",
        "max_attempts": 1,
        "parameters_json": {
            "patient_record": "FS001",
            "intent": "full_sync",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    }
    defaults.update(kwargs)
    return IngestionRun.objects.create(**defaults)


_ADMISSION_SNAPSHOT_DATA = [
    {
        "admission_key": "ADM-001",
        "admission_start": "2024-01-15",
        "admission_end": "2024-01-20",
        "ward": "Enfermaria A",
        "bed": "001",
    },
]

_EVOLUTION_DATA = [
    {
        "admission_key": "ADM-001",
        "happened_at": "2024-01-16T10:30:00",
        "event_type": "medical_evolution",
        "content": "Patient stable, vital signs normal.",
        "profession": "medica",
    },
]


@pytest.mark.django_db
class TestFullSyncLifecycle:
    """Full-sync lifecycle through the persistent adapter (PSW-S8).

    The persistent worker now wires admissions capture, gap planning,
    evolution extraction through the adapter, and shared evolution
    ingestion. All tests use fakes/mocks — no real legacy access.
    """

    def test_full_sync_success_persists_expected_counters(self):
        """Full-sync success persists expected counters and stage metrics."""
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.finished_at is not None

        # Admissions metrics
        assert run.admissions_seen == 1

        # Evolution counters
        assert run.events_processed == 1
        assert run.events_created >= 1

        # Stage metrics: all four stages succeeded
        stages = {
            s.stage_name: s
            for s in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages["admissions_capture"].status == "succeeded"
        assert stages["gap_planning"].status == "succeeded"
        assert stages["evolution_extraction"].status == "succeeded"
        assert stages["ingestion_persistence"].status == "succeeded"

        # Attempt succeeded
        attempt = IngestionRunAttempt.objects.filter(run=run).first()
        assert attempt is not None
        assert attempt.status == "succeeded"

    def test_gap_planning_succeeds(self):
        """Gap planning stage is recorded as succeeded."""
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        # gaps_json was populated
        assert run.gaps_json is not None

    def test_full_sync_full_coverage_skips_extraction(self):
        """When full coverage is detected, evolution extraction is skipped.

        Pre-creates a ClinicalEvent with a happened_at date within the run
        window so ``plan_extraction_windows`` reports full coverage.
        """
        from django.utils import timezone as dj_timezone

        from apps.clinical_docs.models import ClinicalEvent
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="FS001",
            name="Test Patient",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM-COVERAGE",
            admission_date=dj_timezone.make_aware(
                datetime.datetime(2024, 6, 14, 0, 0, 0)
            ),
        )
        ClinicalEvent.objects.create(
            patient=patient,
            admission=admission,
            event_identity_key="cov-key-001",
            content_hash="abc123",
            happened_at=dj_timezone.make_aware(
                datetime.datetime(2024, 6, 15, 10, 0, 0)
            ),
            profession_type="medical_evolution",
            content_text="Pre-existing event that provides full coverage",
            author_name="Dr. Test",
            raw_payload_json={},
        )

        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "FS001",
                "intent": "full_sync",
                "start_date": "2024-06-15",
                "end_date": "2024-06-15",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        # Extraction was skipped — no evolutions extracted
        assert run.events_processed == 0
        assert run.events_created == 0

        # Extraction stage should be "skipped"
        stages = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="evolution_extraction"
        )
        assert stages.count() == 1
        assert stages.first().status == "skipped"

        # extract_evolutions should NOT have been called
        mock_adapter.extract_evolutions.assert_not_called()

    def test_evolution_extraction_failure_preserves_admissions(self):
        """Evolution extraction failure preserves admissions and marks run failed."""
        from apps.patients.models import Admission

        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.side_effect = ExtractionError(
            "Evolution extraction failed"
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "failed"

        # Admissions were captured and persisted in the database
        assert Admission.objects.filter(
            source_admission_key="ADM-001",
        ).exists()

        # Admissions stage should be succeeded
        adm_stages = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="admissions_capture"
        )
        assert adm_stages.count() == 1
        assert adm_stages.first().status == "succeeded"

        # Evolution extraction stage should be failed
        ev_stages = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="evolution_extraction"
        )
        assert ev_stages.count() == 1
        assert ev_stages.first().status == "failed"

    def test_ingestion_persistence_failure_marks_run_failed(self):
        """Ingestion persistence failure fails the run after admissions."""
        from apps.patients.models import Admission

        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".ingest_evolutions",
            side_effect=ValueError("Persistence failure"),
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "failed"

        # Admissions were persisted in the database
        assert Admission.objects.filter(
            source_admission_key="ADM-001",
        ).exists()

        # Ingestion persistence stage failed
        stages = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="ingestion_persistence"
        )
        assert stages.count() == 1
        assert stages.first().status == "failed"

    def test_admission_capture_failure_marks_run_failed(self):
        """If admissions capture fails, the run fails without gap/evolution stages."""
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(fail_mode="session_not_ready")

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "failed"

        # No gap_planning or evolution_extraction stages
        stages = IngestionRunStageMetric.objects.filter(run=run)
        stage_names = {s.stage_name for s in stages}
        assert "admissions_capture" in stage_names
        assert "gap_planning" not in stage_names
        assert "evolution_extraction" not in stage_names
        assert "ingestion_persistence" not in stage_names

    def test_full_sync_timeout_propagates_to_adapter(self):
        """Timeout is passed to adapter calls during full-sync."""
        _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        # get_admission_snapshot called with timeout
        _, kwargs = mock_adapter.get_admission_snapshot.call_args
        assert "timeout" in kwargs
        assert kwargs["timeout"] > 0

    def test_full_sync_uses_ingest_evolutions_from_shared_service(self):
        """Full-sync persistence uses the shared ingest_evolutions service."""
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".ingest_evolutions"
        ) as mock_ingest:
            mock_ingest.return_value = (1, 0, 0)
            call_command("process_ingestion_runs_persistent_session")

        # ingest_evolutions should have been called with evolutions, run, and patient
        mock_ingest.assert_called_once()
        args, kwargs = mock_ingest.call_args
        assert args[0] == _EVOLUTION_DATA  # evolutions (positional)
        assert args[1] == run  # run (positional)
        assert "patient" in kwargs  # patient (keyword)

    def test_cleanup_after_recoverable_evolution_failure(self):
        """cleanup_after_failure is called after recoverable evolution extraction failure."""
        run = _queue_full_sync_run(max_attempts=1)
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.side_effect = InvalidJsonError(
            "Invalid JSON in evolution data"
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        mock_adapter.cleanup_after_failure.assert_called_once()
        run.refresh_from_db()
        assert run.status == "failed"

    def test_admissions_only_still_works(self):
        """Existing admissions-only functionality still works unchanged."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_full_sync_calls_backfill_admission_ward_from_census(self):
        """Full-sync enriches admissions via the shared census backfill service."""
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA

        with (
            patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
            ),
            patch(
                "apps.ingestion.services.backfill_admission_ward_from_census"
            ) as mock_backfill,
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        mock_backfill.assert_called_once()


# =========================================================================
# Real handle gating & teardown (PSW-S5 safety)
# =========================================================================


@pytest.mark.django_db
class TestRealHandleGating:
    """The command must NOT auto-launch a real browser; it stays non-rollout-ready."""

    def test_default_session_handle_is_stub(self):
        """Without --real-handle the command uses the safe stub (no Chromium)."""
        cmd = PersistentWorkerCommand()
        cmd._use_real_handle = False
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
            _StubSessionHandle,
        )

        handle = cmd._create_session_handle()
        assert isinstance(handle, _StubSessionHandle)

    def test_shutdown_calls_handle_shutdown_not_restart(self):
        """_shutdown_adapter must call shutdown(), not restart_browser()."""
        mock_adapter = MagicMock()
        mock_adapter.session.shutdown = MagicMock()
        mock_adapter.session.restart_browser = MagicMock()

        PersistentWorkerCommand._shutdown_adapter(PersistentWorkerCommand(), mock_adapter)

        mock_adapter.session.shutdown.assert_called_once()
        mock_adapter.session.restart_browser.assert_not_called()

    def test_real_handle_flag_is_off_by_default(self):
        """The --real-handle flag defaults to False (rollout-ready guard)."""
        cmd = PersistentWorkerCommand()
        parser = cmd.create_parser("manage.py", "process_ingestion_runs_persistent_session")
        args = parser.parse_args([])
        assert args.real_handle is False


# =========================================================================
# Real handle contract status (PSW-S8)
# =========================================================================


@pytest.mark.django_db
class TestRealHandleContract:
    """The real handle contract now uses RealHandleBridge (PSW-S9).

    PSW-S9 implements ``RealHandleBridge``, a wrapper around the real
    ``PlaywrightSessionHandle`` that extracts admission data from the
    legacy ``#tabelaInternacoes`` table and evolution data from
    ``<script id="evolution-data-json">``, rendering them inside the
    adapter's expected synthetic container format.

    The adapter still expects ``<div id="admission-snapshot-data">`` and
    ``<div id="evolution-data">`` — the bridge translates real legacy DOM
    data into this format. Production rollout remains guarded until the
    bridge is validated against the real legacy UI in a live environment.
    """

    def test_adapter_still_uses_synthetic_container_contract(self):
        """Adapter contract still expects synthetic container divs.

        The RealHandleBridge translates real legacy DOM into this format —
        the adapter itself remains unchanged.
        """
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            _ADMISSION_DATA_DIV_ID,
            _DATA_CONTAINER_RE,
        )

        assert _ADMISSION_DATA_DIV_ID == "admission-snapshot-data"
        assert _DATA_CONTAINER_RE is not None

    def test_real_handle_bridge_exists_and_is_importable(self):
        """RealHandleBridge is implemented and importable (PSW-S9)."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        assert RealHandleBridge is not None

    def test_real_handle_flag_still_documented_as_guarded(self):
        """The --real-handle flag docs keep it guarded as a manual smoke only."""
        import inspect
        source = inspect.getsource(PersistentWorkerCommand)
        assert "--real-handle" in source
        assert "RealHandleBridge" in source
        # PSW-S10: the flag is a guarded MANUAL SMOKE path, not production rollout.
        assert "manual smoke" in source.lower()
        assert "guarded" in source.lower()


# =========================================================================
# PSW-S10: Safe single-run manual validation controls
# =========================================================================


_REAL_URL_OVERRIDES = {
    "SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE": "https://legacy.test/admissions/{patient_record}",
    "SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE": "https://legacy.test/evolutions/{patient_record}",
    "SOURCE_SYSTEM_SAFE_RENEWAL_URL": "https://legacy.test/safe-renewal",
}


def _clear_source_credentials_env(monkeypatch) -> None:
    """Remove source-system credential env vars for deterministic tests."""
    for var in ("SOURCE_SYSTEM_URL", "SOURCE_SYSTEM_USERNAME", "SOURCE_SYSTEM_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.django_db
class TestRunIdClaim:
    """--run-id claims only the selected queued run."""

    def test_run_id_claims_only_selected_run(self):
        """With --run-id, only the selected run is processed; others stay queued."""
        run1 = _queue_admissions_run(parameters_json={
            "patient_record": "R1", "intent": "admissions_only",
        })
        run2 = _queue_admissions_run(parameters_json={
            "patient_record": "R2", "intent": "admissions_only",
        })
        run3 = _queue_admissions_run(parameters_json={
            "patient_record": "R3", "intent": "admissions_only",
        })
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run2.pk,
            )

        run1.refresh_from_db()
        run2.refresh_from_db()
        run3.refresh_from_db()
        assert run1.status == "queued"  # untouched
        assert run2.status == "succeeded"  # the selected run
        assert run3.status == "queued"  # untouched

    def test_run_id_not_queued_processes_nothing(self):
        """--run-id pointing at a non-queued run processes nothing."""
        run = _queue_admissions_run()
        run.status = "running"
        run.save(update_fields=["status"])
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )

        run.refresh_from_db()
        assert run.status == "running"
        mock_adapter.get_admission_snapshot.assert_not_called()

    def test_run_id_respects_next_retry_at(self):
        """--run-id skips a run whose retry is not yet due."""
        run = _queue_admissions_run(
            next_retry_at=timezone.now() + timezone.timedelta(hours=1),
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )

        run.refresh_from_db()
        assert run.status == "queued"
        mock_adapter.get_admission_snapshot.assert_not_called()

    def test_unknown_run_id_processes_nothing(self):
        """--run-id pointing at a non-existent run processes nothing."""
        _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=999_999,
            )

        mock_adapter.get_admission_snapshot.assert_not_called()


@pytest.mark.django_db
class TestMaxRunsCap:
    """--max-runs stops after the configured number of processed runs."""

    def test_max_runs_one_stops_after_single_run(self):
        """--max-runs 1 processes exactly one run even when more are queued."""
        run1 = _queue_admissions_run(parameters_json={
            "patient_record": "M1", "intent": "admissions_only",
        })
        run2 = _queue_admissions_run(parameters_json={
            "patient_record": "M2", "intent": "admissions_only",
        })
        run3 = _queue_admissions_run(parameters_json={
            "patient_record": "M3", "intent": "admissions_only",
        })
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                max_runs=1,
            )

        run1.refresh_from_db()
        run2.refresh_from_db()
        run3.refresh_from_db()
        processed = sum(
            1 for r in (run1, run2, run3) if r.status == "succeeded"
        )
        queued = sum(
            1 for r in (run1, run2, run3) if r.status == "queued"
        )
        assert processed == 1
        assert queued == 2

    def test_max_runs_two_processes_two(self):
        """--max-runs 2 processes exactly two runs."""
        for i in range(4):
            _queue_admissions_run(parameters_json={
                "patient_record": f"X{i}", "intent": "admissions_only",
            })
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                max_runs=2,
            )

        succeeded = IngestionRun.objects.filter(status="succeeded").count()
        queued_admissions = IngestionRun.objects.filter(
            status="queued", intent="admissions_only"
        ).count()
        assert succeeded == 2
        # PSW-S15: each processed admissions_only run now enqueues a
        # demographics_only follow-up (batch=None) to match the current worker,
        # so total queued is inflated by those follow-ups. The cap is on the
        # remaining admissions_only runs.
        assert queued_admissions == 2


@pytest.mark.django_db
class TestRealHandleGuards:
    """--real-handle manual smoke guards (PSW-S10)."""

    def test_real_handle_without_run_id_raises_command_error(self):
        """--real-handle requires --run-id; without it the command aborts."""
        run = _queue_admissions_run()

        with pytest.raises(CommandError):
            call_command(
                "process_ingestion_runs_persistent_session",
                real_handle=True,
            )

        run.refresh_from_db()
        # No run mutated — guard fires before any claim.
        assert run.status == "queued"

    def test_real_handle_cannot_drain_arbitrary_queue(self):
        """With --real-handle the worker never processes runs it was not told
        about: missing --run-id aborts before claim."""
        run1 = _queue_admissions_run(parameters_json={
            "patient_record": "D1", "intent": "admissions_only",
        })
        run2 = _queue_admissions_run(parameters_json={
            "patient_record": "D2", "intent": "admissions_only",
        })

        with pytest.raises(CommandError):
            call_command(
                "process_ingestion_runs_persistent_session",
                real_handle=True,
                max_runs=1,
            )

        run1.refresh_from_db()
        run2.refresh_from_db()
        assert run1.status == "queued"
        assert run2.status == "queued"

    def test_real_handle_without_max_runs_aborts_before_claim(self):
        """--real-handle --run-id <id> without --max-runs aborts before claim."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ) as mock_create:
            with pytest.raises(CommandError) as exc_info:
                call_command(
                    "process_ingestion_runs_persistent_session",
                    real_handle=True,
                    run_id=run.pk,
                )

        assert "--max-runs" in str(exc_info.value)
        # Guard fires before adapter/browser creation and before any claim.
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"

    def test_real_handle_with_max_runs_not_one_aborts_before_claim(self):
        """--real-handle --run-id <id> --max-runs 2 aborts before claim."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ) as mock_create:
            with pytest.raises(CommandError) as exc_info:
                call_command(
                    "process_ingestion_runs_persistent_session",
                    real_handle=True,
                    run_id=run.pk,
                    max_runs=2,
                )

        assert "--max-runs" in str(exc_info.value)
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"

    def test_real_handle_with_run_id_and_max_runs_one_is_allowed(self):
        """--real-handle --run-id <id> --max-runs 1 passes the guard and proceeds."""
        run = _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ) as mock_create:
            call_command(
                "process_ingestion_runs_persistent_session",
                real_handle=True,
                run_id=run.pk,
                max_runs=1,
            )

        # Guard passed: adapter created and the run was processed.
        mock_create.assert_called_once()
        run.refresh_from_db()
        assert run.status == "succeeded"

    # ==================================================================
    # PSW-S12: URL templates no longer required for --real-handle
    # ==================================================================

    def test_real_handle_no_admissions_template_starts_successfully(
        self, monkeypatch
    ):
        """PSW-S12: Missing admissions URL template no longer blocks --real-handle.

        The real legacy system uses action-based UI navigation, not reloadable
        deep-link URL templates. The manual smoke must proceed with only
        source URL, username, password, and safe_renewal_url.
        """
        _clear_source_credentials_env(monkeypatch)

        run = _queue_admissions_run()
        mock_handle = MagicMock()
        mock_handle.ensure_current_page.return_value = MagicMock()

        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="https://legacy.test/safe",
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.RealHandleBridge"
        ) as mock_bridge_cls:
            mock_bridge = MagicMock()
            mock_bridge.is_connected.return_value = True
            mock_bridge.get_page_html.return_value = (
                '<html><body><div id="tempoSessao">'
                '<span>00</span>:<span>29</span>:<span>01</span>'
                '</div>'
                '<div id="admission-snapshot-data">[]</div>'
                '</body></html>'
            )
            mock_bridge.get_tab_classes.return_value = [
                "tabs-first tabs-last tabs-selected",
            ]
            mock_bridge.navigate_to_admissions.return_value = True
            mock_bridge_cls.return_value = mock_bridge

            # Should NOT raise CommandError about missing templates.
            call_command(
                "process_ingestion_runs_persistent_session",
                real_handle=True,
                run_id=run.pk,
                max_runs=1,
            )

        run.refresh_from_db()
        # Run was processed despite missing URL templates.
        assert run.status == "succeeded"

    def test_real_handle_no_admissions_template_and_no_renewal_starts(
        self, monkeypatch
    ):
        """PSW-S12: Even without safe_renewal_url, the smoke path must start
        (conservative: safe_renewal_url is optional, not required).
        """
        _clear_source_credentials_env(monkeypatch)

        run = _queue_admissions_run()
        mock_handle = MagicMock()
        mock_handle.ensure_current_page.return_value = MagicMock()

        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="",
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.RealHandleBridge"
        ) as mock_bridge_cls:
            mock_bridge = MagicMock()
            mock_bridge.is_connected.return_value = True
            mock_bridge.get_page_html.return_value = (
                '<html><body><div id="tempoSessao">'
                '<span>00</span>:<span>29</span>:<span>01</span>'
                '</div>'
                '<div id="admission-snapshot-data">[]</div>'
                '</body></html>'
            )
            mock_bridge.get_tab_classes.return_value = [
                "tabs-first tabs-last tabs-selected",
            ]
            mock_bridge.navigate_to_admissions.return_value = True
            mock_bridge_cls.return_value = mock_bridge

            # Should NOT raise CommandError — URL templates are optional.
            call_command(
                "process_ingestion_runs_persistent_session",
                real_handle=True,
                run_id=run.pk,
                max_runs=1,
            )

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_real_handle_missing_source_url_still_fails_before_claim(
        self, monkeypatch
    ):
        """Missing SOURCE_SYSTEM_URL still fails before any claim (PSW-S12)."""
        _clear_source_credentials_env(monkeypatch)

        run = _queue_admissions_run()

        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="",
            SOURCE_SYSTEM_URL="",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ):
            with pytest.raises(CommandError) as exc_info:
                call_command(
                    "process_ingestion_runs_persistent_session",
                    real_handle=True,
                    run_id=run.pk,
                    max_runs=1,
                )

        assert "credential" in str(exc_info.value).lower()
        run.refresh_from_db()
        assert run.status == "queued"

    def test_real_handle_missing_credentials_still_fails_before_claim(
        self, monkeypatch
    ):
        """Missing source credentials still abort before any run is claimed (PSW-S12)."""
        run = _queue_admissions_run()
        _clear_source_credentials_env(monkeypatch)

        # URL templates present, but no credentials.
        with override_settings(**_REAL_URL_OVERRIDES), override_settings(
            SOURCE_SYSTEM_URL="",
            SOURCE_SYSTEM_USERNAME="",
            SOURCE_SYSTEM_PASSWORD="",
        ):
            with pytest.raises(CommandError) as exc_info:
                call_command(
                    "process_ingestion_runs_persistent_session",
                    real_handle=True,
                    run_id=run.pk,
                    max_runs=1,
                )

        msg = str(exc_info.value)
        assert "credential" in msg.lower() or "SOURCE_SYSTEM_" in msg
        # No password value leaked.
        run.refresh_from_db()
        assert run.status == "queued"

    def test_real_handle_creates_and_bootstraps_handle(self, monkeypatch):
        """The real-handle path starts the handle and bootstraps the session."""
        _clear_source_credentials_env(monkeypatch)

        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_handle.ensure_current_page.return_value = mock_page

        with override_settings(**_REAL_URL_OVERRIDES), override_settings(
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session"
        ) as mock_bootstrap, patch(
            "apps.ingestion.extractors.real_handle_bridge.RealHandleBridge"
        ) as mock_bridge_cls:
            cmd = PersistentWorkerCommand()
            cmd._use_real_handle = True
            result = cmd._create_session_handle()

        # Handle started and page exposed for bootstrap.
        mock_handle.start.assert_called_once()
        mock_handle.ensure_current_page.assert_called_once()
        # Bootstrap invoked with the handle's page and credentials.
        mock_bootstrap.assert_called_once()
        bootstrap_args, bootstrap_kwargs = mock_bootstrap.call_args
        assert bootstrap_args[0] is mock_page
        creds = bootstrap_kwargs["credentials"]
        assert creds.username == "operador"
        assert creds.url == "https://legacy.test/login"
        # Bridge wraps the started handle.
        mock_bridge_cls.assert_called_once_with(mock_handle)
        assert result is mock_bridge_cls.return_value

    def test_real_handle_configures_adapter_with_real_url_templates(
        self, monkeypatch
    ):
        """The adapter receives the resolved real URL templates."""
        _clear_source_credentials_env(monkeypatch)
        mock_handle = MagicMock()

        with override_settings(**_REAL_URL_OVERRIDES), override_settings(
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.RealHandleBridge"
        ) as mock_bridge_cls:
            captured = {}
            real_adapter_cls = PersistentWorkerCommand.adapter_class

            class _CapturingAdapter(real_adapter_cls):  # type: ignore[misc, valid-type]
                def __init__(self, session, config=None):
                    captured["config"] = config
                    captured["session"] = session
                    super().__init__(session=session, config=config)

            cmd = PersistentWorkerCommand()
            cmd._use_real_handle = True
            cmd.adapter_class = _CapturingAdapter  # type: ignore[assignment]
            cmd._create_adapter()

        config = captured["config"]
        assert (
            config.base_admissions_url
            == "https://legacy.test/admissions/{patient_record}"
        )
        assert (
            config.base_evolutions_url
            == "https://legacy.test/evolutions/{patient_record}"
        )
        assert config.safe_renewal_tab_url == "https://legacy.test/safe-renewal"
        assert captured["session"] is mock_bridge_cls.return_value

    def test_bootstrap_failure_converts_to_command_error_and_shuts_down(
        self, monkeypatch
    ):
        """A bootstrap failure surfaces as CommandError and tears down the browser."""
        from apps.ingestion.extractors.legacy_session_bootstrap import (
            LegacyBootstrapError,
        )

        _clear_source_credentials_env(monkeypatch)
        mock_handle = MagicMock()

        with override_settings(**_REAL_URL_OVERRIDES), override_settings(
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session",
            side_effect=LegacyBootstrapError("boom sanitized"),
        ):
            cmd = PersistentWorkerCommand()
            cmd._use_real_handle = True
            with pytest.raises(CommandError):
                cmd._create_session_handle()

        mock_handle.shutdown.assert_called_once()


@pytest.mark.django_db
class TestPersistentCommandRawExceptionSanitization:
    """PSW-S17 post-cbf50c1 (D18/R2): no arbitrary ``str(exc)``, dynamic
    exception class, or cause/context chain may reach command stdout/stderr,
    ``CommandError`` text, or ``__cause__``/``__context__`` at sanitized
    boundaries."""

    _TEARDOWN_SENTINEL = "SENSITIVE_COOKIE_FROM_TEARDOWN"
    _CRED_SENTINEL = "SENSITIVE_CRED_VALUE_xyz"
    _BOOTSTRAP_SENTINEL = "SENSITIVE_BOOTSTRAP_detail"
    _DB_SENTINEL = "SENSITIVE_DB_MSG_xyz"

    def test_teardown_failure_does_not_leak_raw_exception_to_stderr(
        self, capsys
    ) -> None:
        """_shutdown_adapter must emit a constant sanitized warning; the raw
        exception (e.g. a leaked cookie) must NOT reach stderr."""
        cmd = PersistentWorkerCommand()
        adapter = MagicMock()
        adapter.session.shutdown.side_effect = RuntimeError(self._TEARDOWN_SENTINEL)

        cmd._shutdown_adapter(adapter)

        captured = capsys.readouterr()
        assert self._TEARDOWN_SENTINEL not in captured.err
        assert self._TEARDOWN_SENTINEL not in captured.out

    def test_credential_failure_command_error_is_constant_and_no_cause_chain(
        self, monkeypatch
    ) -> None:
        """resolve_source_credentials failure surfaces as a CONSTANT
        CommandError raised ``from None``; no sentinel or cause chain."""
        _clear_source_credentials_env(monkeypatch)

        with override_settings(**_REAL_URL_OVERRIDES), patch(
            "apps.ingestion.historical_extraction.resolve_source_credentials",
            side_effect=ValueError(self._CRED_SENTINEL),
        ), patch(
            "apps.ingestion.extractors.browser_profile.ExclusiveBrowserProfile"
        ) as mock_profile_cls:
            cmd = PersistentWorkerCommand()
            cmd._use_real_handle = True
            with pytest.raises(CommandError) as exc_info:
                cmd._create_session_handle()

        msg = str(exc_info.value)
        assert self._CRED_SENTINEL not in msg
        # No cause chain at the sanitized boundary.
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None or not str(
            exc_info.value.__context__
        ).strip()
        # Browser profile must NOT be created when credential resolution
        # fails first (fail fast before launching Chromium).
        mock_profile_cls.assert_not_called()

    def test_bootstrap_failure_command_error_is_constant_and_no_cause_chain(
        self, monkeypatch
    ) -> None:
        """A LegacyBootstrapError surfaces as a CONSTANT CommandError raised
        ``from None``; no sentinel or cause chain leaks."""
        from apps.ingestion.extractors.legacy_session_bootstrap import (
            LegacyBootstrapError,
        )

        _clear_source_credentials_env(monkeypatch)
        mock_handle = MagicMock()

        with override_settings(**_REAL_URL_OVERRIDES), override_settings(
            SOURCE_SYSTEM_URL="https://legacy.test/login",
            SOURCE_SYSTEM_USERNAME="operador",
            SOURCE_SYSTEM_PASSWORD="super-secret",
        ), patch(
            "apps.ingestion.extractors.playwright_session_handle"
            ".PlaywrightSessionHandle",
            return_value=mock_handle,
        ), patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session",
            side_effect=LegacyBootstrapError(self._BOOTSTRAP_SENTINEL),
        ) as mock_bootstrap:
            cmd = PersistentWorkerCommand()
            cmd._use_real_handle = True
            with pytest.raises(CommandError) as exc_info:
                cmd._create_session_handle()

        msg = str(exc_info.value)
        assert self._BOOTSTRAP_SENTINEL not in msg
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None or not str(
            exc_info.value.__context__
        ).strip()
        # Bootstrap was reached (browser started) then torn down on failure.
        mock_handle.start.assert_called_once()
        mock_handle.shutdown.assert_called_once()
        mock_bootstrap.assert_called_once()

    def test_startup_db_retry_warning_is_constant_and_no_raw_exception(
        self, capsys
    ) -> None:
        """The startup DB retry warning must be constant; the raw DB exception
        (class name + message) must NOT reach stderr."""
        from django.db.utils import OperationalError

        mock_adapter = _make_adapter_mock(snapshot_result=[])
        cmd_path = (
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session"
        )

        failing_qs = MagicMock()
        failing_qs.count.side_effect = OperationalError(self._DB_SENTINEL)

        with (
            patch(f"{cmd_path}.IngestionRun.objects.filter", return_value=failing_qs),
            patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
            ),
            patch(f"{cmd_path}.time.sleep", side_effect=[None, KeyboardInterrupt]),
        ):
            with pytest.raises(KeyboardInterrupt):
                call_command(
                    "process_ingestion_runs_persistent_session",
                    loop=True,
                    sleep_seconds=1,
                )

        captured = capsys.readouterr()
        assert self._DB_SENTINEL not in captured.err
        assert self._DB_SENTINEL not in captured.out
        # The dynamic exception class name must not be echoed either.
        assert "OperationalError" not in captured.err


@pytest.mark.django_db
class TestDefaultStubBackwardCompat:
    """Default stub behavior remains backward compatible (PSW-S10)."""

    def test_stub_drains_eligible_queue_by_default(self):
        """Without --max-runs/--run-id, the stub path drains all eligible runs."""
        for i in range(3):
            _queue_admissions_run(parameters_json={
                "patient_record": f"S{i}", "intent": "admissions_only",
            })
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        # Demographics follow-ups (S0/S1/S2) must return a payload whose
        # prontuario matches each requested patient (R3 identity invariant).
        mock_adapter.get_demographics.side_effect = (
            lambda *, patient_record, timeout=120: {
                "prontuario": patient_record,
                "nome": f"PACIENTE {patient_record}",
            }
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        succeeded = IngestionRun.objects.filter(status="succeeded").count()
        queued_admissions = IngestionRun.objects.filter(
            status="queued", intent="admissions_only"
        ).count()
        # PSW-S16: each admissions_only run enqueues a demographics_only
        # follow-up (detached from any batch). demographics_only is now an
        # enabled intent, so those follow-ups are claimed and processed in
        # the same default (unbounded) pass — 3 admissions + 3 demographics.
        assert succeeded == 6
        assert queued_admissions == 0
        demographics = IngestionRun.objects.filter(
            status="queued", intent="demographics_only"
        ).count()
        assert demographics == 0

    def test_stub_with_run_id_still_works(self):
        """--run-id works on the stub path too (claims only the selected run)."""
        run1 = _queue_admissions_run(parameters_json={
            "patient_record": "T1", "intent": "admissions_only",
        })
        run2 = _queue_admissions_run(parameters_json={
            "patient_record": "T2", "intent": "admissions_only",
        })
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run1.pk,
            )

        run1.refresh_from_db()
        run2.refresh_from_db()
        assert run1.status == "succeeded"
        assert run2.status == "queued"

    def test_timeout_values_reach_navigation_call(self):
        """Timeout values still reach the adapter snapshot call (regression)."""
        _queue_admissions_run()
        mock_adapter = _make_adapter_mock(snapshot_result=[])

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        _, kwargs = mock_adapter.get_admission_snapshot.call_args
        assert kwargs["timeout"] > 0


@pytest.mark.django_db(transaction=True)
def test_loop_mode_exits_when_max_runs_reached():
    """In loop mode, --max-runs caps total processed runs and exits.

    Uses ``transaction=True`` because ``_run_loop`` calls
    ``close_old_connections()`` before its queue poll, which is incompatible
    with the per-test savepoint used by plain ``django_db``. In production the
    connection auto-reconnects; the transactional fixture models that here.
    """
    for i in range(3):
        _queue_admissions_run(parameters_json={
            "patient_record": f"L{i}", "intent": "admissions_only",
        })
    mock_adapter = _make_adapter_mock(snapshot_result=[])
    cmd_path = (
        "apps.ingestion.management.commands"
        ".process_ingestion_runs_persistent_session"
    )

    with patch.object(
        PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
    ), patch(f"{cmd_path}.time.sleep"):
        call_command(
            "process_ingestion_runs_persistent_session",
            loop=True,
            sleep_seconds=1,
            max_runs=2,
        )

    succeeded = IngestionRun.objects.filter(status="succeeded").count()
    queued_admissions = IngestionRun.objects.filter(
        status="queued", intent="admissions_only"
    ).count()
    assert succeeded == 2
    # PSW-S15: each processed admissions_only run now enqueues a
    # demographics_only follow-up, so total queued grows by those. The cap is
    # on the remaining admissions_only runs.
    assert queued_admissions == 1


# ===========================================================================
# PSW-S11: persistent real evolution PDF flow wiring
# ===========================================================================


class _PdfBridgeSession:
    """Bridge-like fake that produces adapter containers AND exposes
    ``extract_evolutions_pdf`` so a REAL ``PersistentExtractionAdapter`` can
    exercise the PSW-S11 PDF fallback end-to-end through the command.

    Mirrors what ``RealHandleBridge`` would produce: a session counter on every
    page (so controller checkpoints pass), an admissions container on
    admissions URLs, and an EMPTY evolution container on evolution URLs (so the
    fast path yields no events and the adapter delegates to the PDF flow).
    """

    _COUNTER = (
        '<div id="tempoSessao" class="tempo-sessao">'
        'Tempo: <span>00</span>:<span>29</span>:<span>01</span>'
        "</div>"
    )
    _ADMISSIONS_JSON = (
        '[{"admissionKey":"ADM-001","admissionStart":"2024-01-15",'
        '"admissionEnd":"2024-01-20","ward":"Enfermaria A","bed":"1"}]'
    )

    def __init__(self) -> None:
        self._connected = True
        self._last_url = ""
        self._closed = 0
        self.pdf_calls: list[dict] = []
        self.pdf_return: list[dict] = []
        self.pdf_error: Exception | None = None

    # --- SessionHandle protocol ---

    def is_connected(self) -> bool:
        return self._connected

    def click_selector(self, selector: str) -> None:  # noqa: ARG002
        pass

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:  # noqa: ARG002
        self._last_url = url
        return True

    def get_page_html(self) -> str:
        html = f"<html><body>{self._COUNTER}"
        low = self._last_url.lower()
        if "admissions" in low or "consultarinternacoes" in low:
            html += f'<div id="admission-snapshot-data">{self._ADMISSIONS_JSON}</div>'
        elif "evolutions" in low or "relatorio" in low or "evolucao" in low:
            html += '<div id="evolution-data">[]</div>'
        return html + "</body></html>"

    def get_tab_classes(self) -> list[str]:
        return ["tabs-first tabs-last tabs-selected", "tabs-last"]

    def close_last_non_root_tab(self) -> None:
        self._closed += 1

    def restart_browser(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    # --- PSW-S11 PDF capability ---

    def extract_evolutions_pdf(self, **kwargs) -> list[dict]:
        self.pdf_calls.append(kwargs)
        if self.pdf_error is not None:
            raise self.pdf_error
        return self.pdf_return


_PDF_EVENT = [
    {
        "admission_key": "ADM-001",
        "happened_at": "2024-01-16T10:30:00",
        "event_type": "medical",
        "content": "Evolução extraída do PDF via sessão persistente.",
        "profession": "Dr. PDF",
    }
]


@pytest.mark.django_db
class TestFullSyncPdfFallback:
    """PSW-S11: full_sync falls back to the persistent PDF flow and persists
    events through the shared ingestion service — no subprocess, no new
    browser."""

    def test_full_sync_uses_pdf_fallback_and_persists_events(self) -> None:
        from apps.clinical_docs.models import ClinicalEvent
        from apps.patients.models import Patient

        run = _queue_full_sync_run()
        session = _PdfBridgeSession()
        session.pdf_return = list(_PDF_EVENT)

        adapter = PersistentExtractionAdapter(session)

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        # The PDF fallback was actually invoked (fast path was empty).
        assert len(session.pdf_calls) >= 1
        # Events flowed through the shared ingestion service.
        assert run.events_processed >= 1
        assert run.events_created >= 1

        stages = {
            s.stage_name: s.status
            for s in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages["evolution_extraction"] == "succeeded"
        assert stages["ingestion_persistence"] == "succeeded"

        # PSW-S11 fix: PDF events MUST reach persistence with the schema the
        # shared service reads (content_text / profession_type / author_name /
        # correct patient), not the empty fields the raw 5-key contract would
        # produce.
        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="FS001"
        )
        event = ClinicalEvent.objects.get(patient=patient)
        assert event.content_text == _PDF_EVENT[0]["content"]
        assert event.profession_type == "medica"  # canonical for 'medical'
        assert event.author_name == "Dr. PDF"
        assert event.patient_id == patient.pk
        assert event.patient.patient_source_key == "FS001"

    def test_full_sync_pdf_failure_is_recoverable_and_cleans_tab(self) -> None:
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )

        run = _queue_full_sync_run(max_attempts=2)
        session = _PdfBridgeSession()
        session.pdf_error = EvolutionPdfError(
            "Evolution report PDF could not be located on the page"
        )

        adapter = PersistentExtractionAdapter(session)

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        # Recoverable data-level failure: requeued for retry (attempts remain).
        assert run.status == "queued"
        assert run.failure_reason == "invalid_payload"
        # Sanitized: no secrets or raw payloads leaked into the error message.
        lowered = (run.error_message or "").lower()
        for secret in ("password", "cookie", "jsessionid", "authorization"):
            assert secret not in lowered


# ===========================================================================
# PSW-S14: Explicit supported-intent contract
# ===========================================================================


@pytest.mark.django_db
class TestEnabledIntents:
    """PSW-S14: Explicit enabled-intent contract for claim and dispatch."""

    def _make_run(self, intent="", params=None, max_attempts=1):
        return IngestionRun.objects.create(
            status="queued",
            intent=intent,
            max_attempts=max_attempts,
            parameters_json=params or {},
        )

    def test_enabled_intents_derived_from_dispatch_map(self):
        """R1: Enabled intents are derived from the dispatch declaration
        and cannot drift."""
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
            _DISPATCH_MAP,
            _ENABLED_INTENTS,
        )
        assert set(_ENABLED_INTENTS) == set(_DISPATCH_MAP.keys()), (
            "_ENABLED_INTENTS must be derived from _DISPATCH_MAP keys"
        )

    def test_normal_poll_processes_demographics_only(self):
        """PSW-S16: Normal polling now CLAIMS and processes demographics_only
        runs through the persistent session (atomic enablement)."""
        demo = self._make_run(
            intent="demographics_only",
            params={"patient_record": "E2", "intent": "demographics_only"},
        )
        mock_adapter = _make_adapter_mock(
            demographics_result={"prontuario": "E2", "nome": "PACIENTE TESTE"},
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        demo.refresh_from_db()
        assert demo.status == "succeeded"
        mock_adapter.get_demographics.assert_called_once()

    def test_normal_poll_skips_empty_intent(self):
        """R4: Normal polling does NOT claim runs with empty intent."""
        empty = self._make_run(intent="", params={"patient_record": "E3", "intent": ""})
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        empty.refresh_from_db()
        assert empty.status == "queued"

    def test_normal_poll_skips_unknown_intent(self):
        """R4: Normal polling does NOT claim runs with unknown intent."""
        unknown = self._make_run(
            intent="unknown_purpose",
            params={"patient_record": "E4", "intent": "unknown_purpose"},
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        unknown.refresh_from_db()
        assert unknown.status == "queued"

    def test_full_admission_sync_dispatched_to_full_sync(self):
        """R2: full_admission_sync dispatches explicitly to full-sync."""
        run = self._make_run(
            intent="full_admission_sync",
            params={
                "patient_record": "E5",
                "intent": "full_admission_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed >= 1

    def test_strict_dispatch_no_fallback(self):
        """R1R2: Strict dispatch has no unknown-to-full-sync fallback.
        Uses _DISPATCH_MAP[intent] (not .get with fallback)."""
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
            _DISPATCH_MAP,
        )
        with pytest.raises(KeyError):
            _DISPATCH_MAP["nonexistent_intent"]

    def test_selected_unsupported_does_not_call_adapter(self):
        """R3R5: Unsupported --run-id does NOT call _create_adapter()."""
        run = self._make_run(
            intent="invalid",
            max_attempts=3,
            params={"patient_record": "E6", "intent": "invalid"},
        )
        with patch.object(PersistentWorkerCommand, "_create_adapter") as mock_create:
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 0

    def test_selected_empty_does_not_call_adapter(self):
        """R3R5: Empty selected intent does NOT call _create_adapter()."""
        run = self._make_run(intent="", params={"patient_record": "E9", "intent": ""})
        with patch.object(PersistentWorkerCommand, "_create_adapter") as mock_create:
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"

    def test_selected_demographics_only_calls_adapter_and_processes(self):
        """PSW-S16: demographics_only selected via --run-id now creates the
        adapter and processes the run (atomic enablement)."""
        run = self._make_run(
            intent="demographics_only",
            params={"patient_record": "E10", "intent": "demographics_only"},
        )
        mock_adapter = _make_adapter_mock(
            demographics_result={"prontuario": "E10", "nome": "PACIENTE TESTE"},
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )
        run.refresh_from_db()
        assert run.status == "succeeded"
        mock_adapter.get_demographics.assert_called_once()

    def test_conflicting_model_json_intents_rejected(self):
        """R3R5: Conflicting model/JSON intents rejected before adapter creation."""
        run = self._make_run(
            intent="admissions_only",
            params={"patient_record": "E11", "intent": "full_sync"},
        )
        with patch.object(PersistentWorkerCommand, "_create_adapter") as mock_create:
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"

    def _loop_sleep_test(self, mock_adapter):
        """Helper: assert loop with ineligible-only work sleeps
        and does not call ensure_session_ready."""
        with (
            patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
            ),
            patch(
                "apps.ingestion.management.commands.process_ingestion_runs_persistent_session.time.sleep",
                side_effect=[None, KeyboardInterrupt],
            ),
        ):
            with pytest.raises(KeyboardInterrupt):
                call_command(
                    "process_ingestion_runs_persistent_session",
                    loop=True,
                    sleep_seconds=10,
                )
        mock_adapter.ensure_session_ready.assert_not_called()

    def test_loop_with_only_demographics_retry_not_due_sleeps(self):
        """PSW-S16: demographics_only is now eligible; a retry-not-due
        demographics run still makes the loop sleep."""
        import datetime
        self._make_run(
            intent="demographics_only",
            max_attempts=3,
            params={"patient_record": "L1", "intent": "demographics_only"},
        )
        run = IngestionRun.objects.get(parameters_json__patient_record="L1")
        run.next_retry_at = timezone.now() + datetime.timedelta(hours=1)
        run.save(update_fields=["next_retry_at"])
        self._loop_sleep_test(_make_adapter_mock(demographics_result={}))

    def test_loop_with_only_empty_intents_sleeps(self):
        """R4: Loop with only empty/unknown intents sleeps."""
        self._make_run(intent="", params={"patient_record": "L2", "intent": ""})
        self._loop_sleep_test(_make_adapter_mock(snapshot_result=[]))

    def test_loop_with_only_retry_not_due_sleeps(self):
        """R4: Loop with only retry-not-due enabled work sleeps."""
        import datetime
        self._make_run(
            intent="admissions_only",
            max_attempts=3,
            params={"patient_record": "L3", "intent": "admissions_only"},
        )
        run = IngestionRun.objects.get(parameters_json__patient_record="L3")
        run.next_retry_at = timezone.now() + datetime.timedelta(hours=1)
        run.save(update_fields=["next_retry_at"])
        self._loop_sleep_test(_make_adapter_mock(snapshot_result=[]))

    def test_eligible_enabled_run_still_processed(self):
        """R2: An eligible enabled run is still processed normally."""
        run = self._make_run(
            intent="admissions_only",
            params={"patient_record": "E12", "intent": "admissions_only"},
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_unsupported_unknown_remains_unclaimed_alongside_enabled(self):
        """PSW-S16: An unknown-intent run remains untouched while an enabled
        run is processed. (demographics_only is now enabled in PSW-S16, so a
        truly unknown intent is used as the disabled example.)"""
        enabled = self._make_run(
            intent="admissions_only",
            params={"patient_record": "E7", "intent": "admissions_only"},
        )
        disabled = self._make_run(
            intent="unknown_purpose",
            params={"patient_record": "E8", "intent": "unknown_purpose"},
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")
        enabled.refresh_from_db()
        disabled.refresh_from_db()
        assert enabled.status == "succeeded"
        assert disabled.status == "queued"

    def test_unsupported_selected_no_adapter_no_browser(self):
        """R5: Unsupported selected run — zero adapter calls, no state mutation."""
        run = self._make_run(
            intent="invalid",
            max_attempts=3,
            params={"patient_record": "E13", "intent": "invalid"},
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
            )
        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 0
        mock_adapter.get_admission_snapshot.assert_not_called()
        mock_adapter.extract_evolutions.assert_not_called()
        mock_adapter.get_demographics.assert_not_called()


# ===========================================================================
# PSW-S14: Production producer explicit intent contract
# ===========================================================================


def _make_queued_run(
    intent: str = "",
    parameters: dict | None = None,
    max_attempts: int = 1,
) -> IngestionRun:
    """Create a queued IngestionRun with given intent and parameters."""
    return IngestionRun.objects.create(
        status="queued",
        intent=intent,
        max_attempts=max_attempts,
        parameters_json=parameters or {},
    )


@pytest.mark.django_db
class TestProductionProducerIntents:
    """PSW-S14-R6: Production enqueue helpers create explicit non-empty intents."""

    def test_queue_admissions_only_run_creates_explicit_intent(self):
        """queue_admissions_only_run creates intent='admissions_only'."""
        from apps.ingestion.services import queue_admissions_only_run
        run = queue_admissions_only_run(patient_record="P-PROD")
        assert run.intent == "admissions_only"
        assert run.parameters_json.get("intent") == "admissions_only"

    def test_queue_demographics_only_run_creates_explicit_intent(self):
        """queue_demographics_only_run creates intent='demographics_only'."""
        from apps.ingestion.services import queue_demographics_only_run
        run = queue_demographics_only_run(patient_record="P-PROD")
        assert run.intent == "demographics_only"
        assert run.parameters_json.get("intent") == "demographics_only"

    def test_queue_ingestion_run_creates_explicit_intent(self):
        """queue_ingestion_run creates runs with the supplied intent."""
        from apps.ingestion.services import queue_ingestion_run
        for intent in ("full_sync", "full_admission_sync", "admissions_only"):
            run = queue_ingestion_run(
                patient_record="P-PROD", start_date="2024-01-01",
                end_date="2024-12-31", intent=intent,
            )
            assert run.intent == intent
            assert run.parameters_json.get("intent") == intent

    def test_current_worker_enqueue_most_recent_full_sync_creates_full_sync(self):
        """Current worker's _enqueue_most_recent_full_sync creates intent='full_sync'."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command as CurrentWorkerCommand,
        )
        from apps.patients.models import Admission, Patient
        patient = Patient.objects.create(
            source_system="tasy", patient_source_key="P-FS", name="FS Patient",
        )
        Admission.objects.create(
            patient=patient, source_system="tasy",
            source_admission_key="ADM-FS", admission_date=timezone.now(),
        )
        run = CurrentWorkerCommand._enqueue_most_recent_full_sync(patient)
        assert run is not None and run.intent == "full_sync"

    def test_no_producer_creates_empty_intent(self):
        """No production enqueue helper creates an empty/blank intent."""
        from apps.ingestion.services import (
            queue_admissions_only_run,
            queue_demographics_only_run,
            queue_ingestion_run,
        )
        runs = [
            queue_admissions_only_run(patient_record="P-E1"),
            queue_demographics_only_run(patient_record="P-E2"),
            queue_ingestion_run(
                patient_record="P-E3", start_date="2024-01-01",
                end_date="2024-12-31", intent="full_sync",
            ),
            queue_ingestion_run(
                patient_record="P-E4", start_date="2024-01-01",
                end_date="2024-12-31", intent="full_admission_sync",
            ),
        ]
        for r in runs:
            assert r.intent, f"Run #{r.pk} has empty intent"
            assert r.parameters_json.get("intent"), (
                f"Run #{r.pk} parameters_json has no intent"
            )

    def test_current_worker_handles_demographics(self):
        """R7: The current worker remains executable and continues
        handling demographics until PSW-S16.

        This test proves the current worker picks up demographics_only runs
        (the persistent worker skips them), even though the full subprocess
        extraction may not complete in this test context.
        """
        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={
                "patient_record": "CWD", "intent": "demographics_only",
            },
        )
        # The current worker claims demographics_only runs and attempts
        # processing. We patch the full subprocess pipeline to verify the
        # intent dispatch works (demographics_only branch is reached).
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
        ) as mock_ext_cls:
            mock_ext = MagicMock()
            mock_ext.get_admission_snapshot.return_value = []
            mock_ext_cls.return_value = mock_ext
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        # The current worker attempted to process the run (attempt_count
        # was incremented). It may have failed due to subprocess issues,
        # but the key point is that the current worker CLAIMED the
        # demographics_only run (persistent worker skips it).
        assert run.attempt_count >= 1, (
            "Current worker must claim demographics_only runs"
        )
        # The run was marked 'running' at some point (proof of claim)
        assert run.worker_label != "", (
            "Current worker must assign a worker label"
        )


# =========================================================================
# PSW-S15: Admissions-only persistence parity
# =========================================================================

_ADMISSION_SNAPSHOT_PARITY = [
    {
        "admission_key": "ADM-PARITY",
        "admission_start": "2024-03-10",
        "admission_end": "2024-03-15",
        "ward": "Enfermaria B",
        "bed": "010",
    },
]


@pytest.mark.django_db
class TestAdmissionsOnlyPersistenceParity:
    """PSW-S15: persistent admissions_only must persist like the current worker.

    Asserts the persistent worker produces the same clinical and operational
    effects as ``process_ingestion_runs``: Patient/Admission rows,
    database-derived counters (never list-length fabrication), demographics +
    full-sync follow-ups under the same conditions, stages, attempts, and
    batch semantics. Expected values mirror the current worker's documented
    behavior (``tests/integration/test_worker_lifecycle.py``
    ``TestAdmissionsOnlyWorker``).
    """

    def test_persists_patient_and_admission_rows(self):
        from apps.patients.models import Admission, Patient

        run = _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-1",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        patient = Patient.objects.get(patient_source_key="PAR-1")
        assert Admission.objects.filter(
            patient=patient, source_admission_key="ADM-PARITY"
        ).exists()

    def test_counters_reflect_database_outcomes_not_list_length(self):
        """Update path: pre-existing admission -> created=0, updated=1.

        Exposes the fabricated ``admissions_created = admissions_seen``
        counter that ignored database outcomes.
        """
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="tasy", patient_source_key="PAR-2", name="",
        )
        Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM-PARITY",
            admission_date=timezone.make_aware(
                datetime.datetime(2024, 3, 10, 0, 0, 0)
            ),
        )
        run = _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-2",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 1
        assert run.admissions_created == 0
        assert run.admissions_updated == 1

    def test_enqueues_demographics_only_followup_with_no_batch(self):
        _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-3",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        demos = IngestionRun.objects.filter(
            intent="demographics_only",
            parameters_json__patient_record="PAR-3",
        )
        assert demos.count() == 1
        demo = demos.first()
        assert demo.status == "queued"
        # Demographics follow-up is deliberately detached from the batch.
        assert demo.batch_id is None

    def test_enqueues_most_recent_full_sync_followup(self):
        run = _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-4",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        fs_runs = (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="PAR-4",
            )
            .exclude(pk=run.pk)
        )
        assert fs_runs.count() == 1
        fs = fs_runs.first()
        assert fs.status == "queued"
        # Same batch relationship as the current worker.
        assert fs.batch_id == run.batch_id
        assert fs.parameters_json["intent"] == "full_sync"
        assert fs.parameters_json["admission_source_key"] == "ADM-PARITY"
        assert "admission_id" in fs.parameters_json

    def test_empty_snapshot_no_fabricated_counters_or_full_sync(self):
        """Zero admissions must not fabricate created rows or full-sync work."""
        run = _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-5",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 0
        assert run.admissions_created == 0
        assert run.admissions_updated == 0
        # PSW-S15 R4: empty snapshot still creates the Patient (traceability)
        # and enqueues exactly one demographics_only follow-up detached from
        # any batch, matching the current worker.
        from apps.patients.models import Patient

        assert Patient.objects.filter(patient_source_key="PAR-5").exists()
        demos = IngestionRun.objects.filter(
            intent="demographics_only",
            parameters_json__patient_record="PAR-5",
        )
        assert demos.count() == 1
        assert demos.first().batch_id is None
        # No full-sync work fabricated when no admission exists.
        assert not (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="PAR-5",
            )
            .exclude(pk=run.pk)
            .exists()
        )

    def test_persistence_failure_fails_run_without_admission(self):
        from apps.patients.models import Admission

        run = _queue_admissions_run(
            max_attempts=1,
            parameters_json={
                "patient_record": "PAR-6",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".persist_admissions_snapshot",
            side_effect=ValueError("DB write failed"),
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "failed"
        assert not Admission.objects.filter(
            source_admission_key="ADM-PARITY",
        ).exists()
        stage = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="admissions_capture"
        ).first()
        assert stage is not None
        assert stage.status == "failed"

    def test_stages_and_attempt_succeeded_on_success(self):
        run = _queue_admissions_run(
            parameters_json={
                "patient_record": "PAR-7",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        stage = IngestionRunStageMetric.objects.filter(
            run=run, stage_name="admissions_capture"
        ).first()
        assert stage is not None and stage.status == "succeeded"
        attempt = IngestionRunAttempt.objects.filter(run=run).first()
        assert attempt is not None and attempt.status == "succeeded"

    def test_full_sync_followup_inherits_real_non_null_batch(self):
        """PSW-S15 R2: persistent full_sync follow-up inherits a real batch.

        Characterization: the persistent path attaches the full_sync follow-up
        to the source run's batch (not ``None``), the demographics follow-up
        stays detached, and the batch remains open while its full_sync child is
        queued.
        """
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _queue_admissions_run(
            batch=batch,
            parameters_json={
                "patient_record": "BATCH-P",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=[
                {
                    "admission_key": "ADM-BATCH",
                    "admission_start": "2024-03-10",
                    "admission_end": "2024-03-15",
                    "ward": "Enfermaria B",
                    "bed": "010",
                }
            ],
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )

        run.refresh_from_db()
        assert run.status == "succeeded"

        demos = IngestionRun.objects.filter(
            intent="demographics_only",
            parameters_json__patient_record="BATCH-P",
        )
        assert demos.count() == 1
        assert demos.first().batch_id is None

        fs = (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="BATCH-P",
            )
            .exclude(pk=run.pk)
        )
        assert fs.count() == 1
        f = fs.first()
        # Real non-null batch inheritance (not None == None).
        assert f.batch_id == batch.pk
        assert f.parameters_json["intent"] == "full_sync"
        assert f.parameters_json["admission_source_key"] == "ADM-BATCH"
        assert "admission_id" in f.parameters_json
        assert f.parameters_json["patient_record"] == "BATCH-P"
        # PSW-S15 R2: both dates are propagated from the captured admission.
        assert f.parameters_json["start_date"] == "2024-03-10"
        assert f.parameters_json["end_date"] == "2024-03-15"

        # Batch stays open/running while its full_sync child is queued.
        batch.refresh_from_db()
        assert batch.status == "running"
        assert batch.finished_at is None

    def test_retry_then_success_does_not_duplicate_followups(self):
        """PSW-S15 R3: failed attempt creates no follow-ups; successful retry
        creates exactly one of each; a later invocation does not duplicate.
        """
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _queue_admissions_run(
            max_attempts=3,
            batch=batch,
            parameters_json={
                "patient_record": "RETRY-P",
                "intent": "admissions_only",
            },
        )

        # Attempt 1: source failure -> requeued, no follow-ups.
        mock_fail = _make_adapter_mock(fail_mode="session_not_ready")
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_fail
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )
        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 1
        assert not IngestionRun.objects.filter(
            intent="demographics_only",
            parameters_json__patient_record="RETRY-P",
        ).exists()
        assert not (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="RETRY-P",
            )
            .exclude(pk=run.pk)
            .exists()
        )

        # Make the retry due.
        run.next_retry_at = timezone.now() - datetime.timedelta(seconds=1)
        run.save(update_fields=["next_retry_at"])

        # Attempt 2: success -> exactly one of each follow-up.
        mock_ok = _make_adapter_mock(
            snapshot_result=[
                {
                    "admission_key": "ADM-RETRY",
                    "admission_start": "2024-03-10",
                    "admission_end": "2024-03-15",
                    "ward": "Enfermaria B",
                    "bed": "010",
                }
            ],
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_ok
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.attempt_count == 2

        attempts = IngestionRunAttempt.objects.filter(run=run).order_by(
            "attempt_number"
        )
        assert [a.status for a in attempts] == ["failed", "succeeded"]

        assert (
            IngestionRun.objects.filter(
                intent="demographics_only",
                parameters_json__patient_record="RETRY-P",
            ).count()
            == 1
        )
        fs = (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="RETRY-P",
            )
            .exclude(pk=run.pk)
        )
        assert fs.count() == 1
        assert fs.first().batch_id == batch.pk

        # Later invocation: source run already succeeded -> preflight rejects
        # -> no reprocessing -> no duplicate follow-ups.
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_ok
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )
        assert (
            IngestionRun.objects.filter(
                intent="demographics_only",
                parameters_json__patient_record="RETRY-P",
            ).count()
            == 1
        )
        assert (
            IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record="RETRY-P",
            )
            .exclude(pk=run.pk)
            .count()
            == 1
        )


@pytest.mark.django_db
class TestPersistAdmissionsSnapshotService:
    """PSW-S15 R1: the shared service propagates one source system.

    Pure service-level tests for ``persist_admissions_snapshot`` so Patient and
    Admission receive the same ``source_system`` and never diverge.
    """

    def test_propagates_non_default_source_system_to_patient_and_admission(self):
        from apps.ingestion.services import persist_admissions_snapshot
        from apps.patients.models import Admission, Patient

        snapshot = [
            {
                "admission_key": "ADM-SS",
                "admission_start": "2024-05-01",
                "admission_end": "2024-05-05",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        patient, metrics = persist_admissions_snapshot(
            patient_source_key="SS-1",
            admissions_snapshot=snapshot,
            source_system="synthetic-system",
        )

        assert patient.source_system == "synthetic-system"
        adm = Admission.objects.get(source_admission_key="ADM-SS")
        assert adm.source_system == "synthetic-system"
        assert adm.patient_id == patient.id
        assert Patient.objects.filter(
            source_system="synthetic-system", patient_source_key="SS-1"
        ).exists()
        assert metrics["seen"] == 1
        assert metrics["created"] == 1
        assert metrics["updated"] == 0

    def test_conflicting_item_source_system_raises_sanitized_error(self):
        """A conflicting per-item source_system is rejected before any write."""
        import pytest

        from apps.ingestion.services import persist_admissions_snapshot
        from apps.patients.models import Admission

        snapshot = [
            {
                "admission_key": "ADM-CONFLICT",
                "admission_start": "2024-05-01",
                "admission_end": "2024-05-05",
                "ward": "UTI",
                "bed": "01",
                "source_system": "source-b",
            }
        ]
        with pytest.raises(ValueError) as exc_info:
            persist_admissions_snapshot(
                patient_source_key="CONF-1",
                admissions_snapshot=snapshot,
                source_system="source-a",
            )

        message = str(exc_info.value)
        # Sanitized: no patient/admission identifiers, clinical text, or creds.
        assert "CONF-1" not in message
        assert "ADM-CONFLICT" not in message

        # No Admission from that snapshot was created or updated.
        assert not Admission.objects.filter(
            source_admission_key="ADM-CONFLICT"
        ).exists()
        # No Admission linked to the resolved patient carries a different source.
        from apps.patients.models import Patient

        patient = Patient.objects.get(
            source_system="source-a", patient_source_key="CONF-1"
        )
        assert not Admission.objects.filter(patient=patient).exists()

    def test_conflict_in_later_item_prevents_partial_admission_writes(self):
        """A conflict in item two must not leave item one persisted."""
        import pytest

        from apps.ingestion.services import persist_admissions_snapshot
        from apps.patients.models import Admission, Patient

        snapshot = [
            {
                "admission_key": "ADM-FIRST",
                "admission_start": "2024-06-01",
                "admission_end": "2024-06-05",
                "ward": "UTI",
                "bed": "01",
            },
            {
                "admission_key": "ADM-SECOND",
                "admission_start": "2024-07-01",
                "admission_end": "2024-07-05",
                "ward": "UTI",
                "bed": "02",
                "source_system": "source-b",
            },
        ]
        with pytest.raises(ValueError):
            persist_admissions_snapshot(
                patient_source_key="CONF-2",
                admissions_snapshot=snapshot,
                source_system="source-a",
            )

        # Pre-validation runs before the mutation loop, so neither admission is
        # written (no partial write of item one).
        assert not Admission.objects.filter(source_admission_key="ADM-FIRST").exists()
        assert not Admission.objects.filter(source_admission_key="ADM-SECOND").exists()
        patient = Patient.objects.get(
            source_system="source-a", patient_source_key="CONF-2"
        )
        assert patient.admissions.count() == 0

    def test_absent_item_source_system_uses_authoritative_source(self):
        """An item without source_system uses the authoritative source."""
        from apps.ingestion.services import persist_admissions_snapshot
        from apps.patients.models import Admission

        snapshot = [
            {
                "admission_key": "ADM-ABS",
                "admission_start": "2024-05-10",
                "admission_end": "2024-05-12",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        patient, _ = persist_admissions_snapshot(
            patient_source_key="ABS-1",
            admissions_snapshot=snapshot,
            source_system="source-a",
        )
        adm = Admission.objects.get(source_admission_key="ADM-ABS")
        assert adm.source_system == "source-a"
        assert adm.source_system == patient.source_system

    def test_matching_item_source_system_is_accepted(self):
        """An item whose source_system equals the authoritative source is accepted."""
        from apps.ingestion.services import persist_admissions_snapshot
        from apps.patients.models import Admission

        snapshot = [
            {
                "admission_key": "ADM-MATCH",
                "admission_start": "2024-05-20",
                "admission_end": "2024-05-22",
                "ward": "UTI",
                "bed": "01",
                "source_system": "source-a",
            }
        ]
        persist_admissions_snapshot(
            patient_source_key="MATCH-1",
            admissions_snapshot=snapshot,
            source_system="source-a",
        )
        adm = Admission.objects.get(source_admission_key="ADM-MATCH")
        assert adm.source_system == "source-a"

    def test_default_tasy_direct_caller_remains_unchanged(self):
        """Direct callers without source_system keep default Tasy behavior."""
        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="tasy", patient_source_key="TASY-1", name=""
        )
        snapshot = [
            {
                "admission_key": "ADM-TASY",
                "admission_start": "2024-08-01",
                "admission_end": "2024-08-03",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        result = upsert_admission_snapshot(patient, snapshot)
        assert result["created"] == 1
        adm = Admission.objects.get(source_admission_key="ADM-TASY")
        assert adm.source_system == "tasy"
        assert adm.source_system == patient.source_system

    def test_explicit_argument_divergent_from_patient_source_raises(self):
        """A caller argument that differs from patient.source_system is rejected."""
        import pytest

        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="source-a",
            patient_source_key="ARG-1",
            name="",
        )
        snapshot = [
            {
                "admission_key": "ADM-ARG",
                "admission_start": "2024-09-01",
                "admission_end": "2024-09-03",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        with pytest.raises(ValueError) as exc_info:
            upsert_admission_snapshot(
                patient, snapshot, source_system="source-b"
            )

        message = str(exc_info.value)
        # Sanitized: no identifiers, clinical text, or the conflicting values.
        assert "ARG-1" not in message
        assert "ADM-ARG" not in message
        assert "source-a" not in message
        assert "source-b" not in message

        # Zero Admissions created or updated.
        assert not Admission.objects.filter(
            source_admission_key="ADM-ARG"
        ).exists()
        assert Admission.objects.filter(patient=patient).count() == 0

    def test_non_string_item_source_raises_value_error_not_attribute_error(
        self,
    ):
        """A non-string per-item source_system raises ValueError, not
        AttributeError, before any Admission mutation."""
        import pytest

        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Admission, Patient

        for index, bad_value in enumerate((123, True, False), start=1):
            patient = Patient.objects.create(
                source_system="source-a",
                patient_source_key=f"TYP-{index}",
                name="",
            )
            snapshot = [
                {
                    "admission_key": f"ADM-TYP-{index}",
                    "admission_start": "2024-09-01",
                    "admission_end": "2024-09-03",
                    "ward": "UTI",
                    "bed": "01",
                    "source_system": bad_value,
                }
            ]
            with pytest.raises(ValueError) as exc_info:
                upsert_admission_snapshot(patient, snapshot)

            message = str(exc_info.value)
            assert f"TYP-{index}" not in message
            assert f"ADM-TYP-{index}" not in message
            assert str(bad_value) not in message
            assert not Admission.objects.filter(
                source_admission_key=f"ADM-TYP-{index}"
            ).exists()

    def test_omitted_argument_uses_patient_source_non_default(self):
        """Omitting the argument uses patient.source_system (non-default)."""
        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="source-a",
            patient_source_key="OMIT-1",
            name="",
        )
        snapshot = [
            {
                "admission_key": "ADM-OMIT",
                "admission_start": "2024-10-01",
                "admission_end": "2024-10-03",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        result = upsert_admission_snapshot(patient, snapshot)
        assert result["created"] == 1
        adm = Admission.objects.get(source_admission_key="ADM-OMIT")
        assert adm.source_system == "source-a"
        assert adm.source_system == patient.source_system

    def test_matching_explicit_argument_is_accepted_direct_call(self):
        """An explicit argument equal to patient.source_system is accepted."""
        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            source_system="source-a",
            patient_source_key="MTCH-1",
            name="",
        )
        snapshot = [
            {
                "admission_key": "ADM-MTCH",
                "admission_start": "2024-11-01",
                "admission_end": "2024-11-03",
                "ward": "UTI",
                "bed": "01",
            }
        ]
        result = upsert_admission_snapshot(
            patient, snapshot, source_system="source-a"
        )
        assert result["created"] == 1
        adm = Admission.objects.get(source_admission_key="ADM-MTCH")
        assert adm.source_system == "source-a"
        assert adm.source_system == patient.source_system


@pytest.mark.django_db
class TestAdmissionsOnlyCrossWorkerParity:
    """PSW-S15-R8: both workers use the same admissions business rule.

    Runs equivalent synthetic snapshots (distinct admission keys per worker to
    avoid the global ``source_admission_key`` lookup colliding across patients)
    through both workers and asserts equivalent Patient/Admission rows,
    counters, demographics/full-sync follow-ups, and batch relationships.
    """

    def _snapshot(self, admission_key):
        return [
            {
                "admission_key": admission_key,
                "admission_start": "2024-03-10",
                "admission_end": "2024-03-15",
                "ward": "Enfermaria B",
                "bed": "010",
            }
        ]

    def _run_current_worker(self, patient_record, admission_key):
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command as CurrentCommand,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            max_attempts=1,
            parameters_json={
                "patient_record": patient_record,
                "intent": "admissions_only",
            },
        )
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.return_value = self._snapshot(admission_key)
        mock_ext.extract_evolutions.return_value = []

        counter = {"n": 0}

        def fake_claim(*args, **kwargs):
            counter["n"] += 1
            return run if counter["n"] == 1 else None

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs"
            ".PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch.object(
            CurrentCommand, "_claim_eligible_run", fake_claim
        ):
            call_command("process_ingestion_runs")
        return run

    def _run_persistent_worker(self, patient_record, admission_key):
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            max_attempts=1,
            parameters_json={
                "patient_record": patient_record,
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(
            snapshot_result=self._snapshot(admission_key),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            # Target the specific run so an unrelated full_sync follow-up
            # enqueued by the current worker (same DB) is not claimed.
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run.pk,
                max_runs=1,
            )
        return run

    def test_both_workers_persist_equivalent_patient_admission_counters(self):
        from apps.patients.models import Admission, Patient

        current_run = self._run_current_worker("CW-CURR", "ADM-CURR")
        persistent_run = self._run_persistent_worker("CW-PERS", "ADM-PERS")

        assert Patient.objects.filter(patient_source_key="CW-CURR").exists()
        assert Patient.objects.filter(patient_source_key="CW-PERS").exists()
        assert Admission.objects.filter(source_admission_key="ADM-CURR").count() == 1
        assert Admission.objects.filter(source_admission_key="ADM-PERS").count() == 1

        # PSW-S15 R5: production-parity fixtures set BOTH model and JSON intent.
        for src in (current_run, persistent_run):
            assert src.intent == "admissions_only"
            assert src.parameters_json.get("intent") == "admissions_only"

        current_run.refresh_from_db()
        persistent_run.refresh_from_db()
        assert current_run.admissions_seen == persistent_run.admissions_seen == 1
        assert current_run.admissions_created == persistent_run.admissions_created == 1
        assert current_run.admissions_updated == persistent_run.admissions_updated == 0
        assert current_run.status == persistent_run.status == "succeeded"

    def test_both_workers_enqueue_equivalent_followups(self):
        current_run = self._run_current_worker("FW-CURR", "ADM-CURR")
        persistent_run = self._run_persistent_worker("FW-PERS", "ADM-PERS")

        for pr, src, key in (
            ("FW-CURR", current_run, "ADM-CURR"),
            ("FW-PERS", persistent_run, "ADM-PERS"),
        ):
            demos = IngestionRun.objects.filter(
                intent="demographics_only",
                parameters_json__patient_record=pr,
            )
            assert demos.count() == 1, f"demographics follow-up mismatch for {pr}"
            assert demos.first().batch_id is None

            fs = (
                IngestionRun.objects.filter(
                    intent="full_sync",
                    parameters_json__patient_record=pr,
                )
                .exclude(pk=src.pk)
            )
            assert fs.count() == 1, f"full_sync follow-up mismatch for {pr}"
            f = fs.first()
            assert f.batch_id == src.batch_id
            assert f.parameters_json["admission_source_key"] == key
            assert f.parameters_json["intent"] == "full_sync"


# ===========================================================================
# PSW-S16: Persistent demographics-only end-to-end
# ===========================================================================


_DEMOGRAPHICS_EXTRACT = {
    "prontuario": "DEMO-1",
    "nome": "MARIA DE FATIMA SILVA",
    "nome_social": "",
    "data_nascimento": "15/03/1965",
    "sexo": "Feminino",
    "genero": "Cisgênero",
    "nome_mae": "JOSEFA SILVA",
    "nome_pai": "JOAO SILVA",
    "raca_cor": "Branca",
    "naturalidade": "Sao Paulo",
    "nacionalidade": "Brasileira",
    "estado_civil": "Casado",
    "grau_instrucao": "Ensino Medio Completo",
    "profissao": "Motorista",
    "ddd_fone_residencial": "11",
    "fone_residencial": "12345678",
    "ddd_fone_celular": "11",
    "fone_celular": "987654321",
    "ddd_fone_recado": "",
    "fone_recado": "",
    "cns": "898001234567890",
    "cpf": "12345678900",
    "logradouro": "Rua das Flores",
    "numero": "123",
    "complemento": "Apto 2",
    "bairro": "Centro",
    "cep": "01001000",
    "cidade": "Sao Paulo",
    "uf": "SP",
}


def _demo_demographics(patient_record: str) -> dict:
    """Return a demographics payload whose prontuario matches the requested
    patient record (so the identity check passes)."""
    data = dict(_DEMOGRAPHICS_EXTRACT)
    data["prontuario"] = patient_record
    return data



@pytest.mark.django_db
class TestDemographicsOnlyEndToEnd:
    """PSW-S16: persistent demographics_only end-to-end through the
    already-authenticated session and ``upsert_patient_demographics``.

    All success-path mocks return a payload whose ``prontuario`` matches the
    requested patient record (R3 identity invariant)."""

    def _queue_demo_run(self, patient_record="DEMO-1", **kwargs):
        defaults = {
            "status": "queued",
            "intent": "demographics_only",
            "max_attempts": 1,
            "parameters_json": {
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def test_persists_demographics_via_upsert_patient_demographics(self):
        from apps.patients.models import Patient

        run = self._queue_demo_run(patient_record="DEMO-1")
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-1"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        patient = Patient.objects.get(patient_source_key="DEMO-1")
        assert patient.name == "MARIA DE FATIMA SILVA"
        assert patient.cns == "898001234567890"
        assert patient.cpf == "12345678900"
        assert patient.gender == "Feminino"
        # Phone combines DDD + number (matches current worker/service).
        assert patient.phone_cellular == "11987654321"

    def test_records_both_demographics_stages(self):
        run = self._queue_demo_run(patient_record="DEMO-2")
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-2"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        stages = {
            m.stage_name: m.status
            for m in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages.get("demographics_extraction") == "succeeded"
        assert stages.get("demographics_persistence") == "succeeded"

    def test_field_count_metric_matches_current_worker(self):
        from apps.patients.models import Patient

        run = self._queue_demo_run(patient_record="DEMO-3")
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-3"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        patient = Patient.objects.get(patient_source_key="DEMO-3")
        # Mirror the current worker's exact field list/count logic.
        expected_count = sum(
            1
            for field_name in [
                "name", "social_name", "date_of_birth", "gender",
                "gender_identity", "mother_name", "father_name",
                "race_color", "birthplace", "nationality",
                "marital_status", "education_level", "profession",
                "cns", "cpf", "phone_home", "phone_cellular",
                "phone_contact", "street", "address_number",
                "address_complement", "neighborhood", "city",
                "state", "postal_code",
            ]
            if getattr(patient, field_name, None)
        )
        assert (
            run.parameters_json["demographics_fields_extracted"]
            == expected_count
        )
        assert expected_count > 0

    def test_missing_patient_record_fails_before_source_actions(self):
        """R6: empty patient_record fails immediately without calling the
        adapter (no source actions)."""
        run = self._queue_demo_run(
            patient_record="",
            parameters_json={
                "patient_record": "",
                "intent": "demographics_only",
            },
        )
        mock_adapter = _make_adapter_mock(demographics_result={})
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "failed"
        mock_adapter.get_demographics.assert_not_called()

    def test_extraction_failure_preserves_retry_taxonomy(self):
        run = self._queue_demo_run(
            patient_record="DEMO-4",
            max_attempts=3,
        )
        mock_adapter = _make_adapter_mock(
            demographics_fail_mode="extraction_error",
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "queued"  # requeued (attempts remain)
        assert run.attempt_count == 1
        stages = {
            m.stage_name: m.status
            for m in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages.get("demographics_extraction") == "failed"
        # Persistence stage must NOT have run.
        assert "demographics_persistence" not in stages

    def test_persistence_failure_marks_run_failed_without_stage_success(self):
        run = self._queue_demo_run(
            patient_record="DEMO-5",
            max_attempts=1,
        )
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-5"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".upsert_patient_demographics",
            side_effect=ValueError("DB write failed"),
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "failed"
        stages = {
            m.stage_name: m.status
            for m in IngestionRunStageMetric.objects.filter(run=run)
        }
        # Extraction succeeded but persistence failed.
        assert stages.get("demographics_extraction") == "succeeded"
        assert stages.get("demographics_persistence") == "failed"

    def test_demographics_only_closes_batch(self):
        from apps.ingestion.models import CensusExecutionBatch

        batch = CensusExecutionBatch.objects.create()
        run = self._queue_demo_run(
            patient_record="DEMO-6",
            batch=batch,
        )
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-6"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        batch.refresh_from_db()
        # try_close_batch marks a drained batch "succeeded" (no failures).
        assert batch.status == "succeeded"
        assert batch.finished_at is not None

    def test_no_subprocess_no_new_browser_on_demographics(self):
        """R7: demographics dispatch performs no subprocess, temp dir/JSON,
        sync_playwright, browser/context launch, or second login."""
        run = self._queue_demo_run(patient_record="DEMO-7")
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-7"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch("subprocess.run") as mock_run, patch(
            "subprocess.Popen"
        ) as mock_popen, patch(
            "playwright.sync_api.sync_playwright"
        ) as mock_sync, patch(
            "tempfile.TemporaryDirectory"
        ) as mock_tmpdir, patch(
            "apps.ingestion.extractors.legacy_session_bootstrap"
            ".bootstrap_legacy_session"
        ) as mock_bootstrap:
            call_command(
                "process_ingestion_runs_persistent_session", max_runs=1
            )

        run.refresh_from_db()
        assert run.status == "succeeded"
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_sync.assert_not_called()
        mock_tmpdir.assert_not_called()
        mock_bootstrap.assert_not_called()

    def test_admissions_then_demographics_reuse_one_handle(self):
        """R9: an admissions job followed by a demographics job reuse the
        same adapter/handle (one ``_create_adapter`` call) and one login."""
        from apps.ingestion.extractors import legacy_session_bootstrap

        adm_run = _queue_admissions_run(
            parameters_json={
                "patient_record": "DEMO-8",
                "intent": "admissions_only",
            },
        )
        demo_run = self._queue_demo_run(patient_record="DEMO-8")
        mock_adapter = _make_adapter_mock(
            snapshot_result=_ADMISSION_SNAPSHOT_PARITY,
            demographics_result=_demo_demographics("DEMO-8"),
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ) as mock_create, patch.object(
            legacy_session_bootstrap, "bootstrap_legacy_session"
        ) as mock_bootstrap:
            call_command(
                "process_ingestion_runs_persistent_session", max_runs=2
            )

        adm_run.refresh_from_db()
        demo_run.refresh_from_db()
        assert adm_run.status == "succeeded"
        assert demo_run.status == "succeeded"
        # One adapter/handle created for both jobs.
        mock_create.assert_called_once()
        # No additional login/bootstrap during dispatch (stub path).
        mock_bootstrap.assert_not_called()


@pytest.mark.django_db
class TestDemographicsIdentityDefense:
    """R3/R4: command-level fail-closed defense so a mocked/regressed adapter
    cannot turn an empty or mismatched payload into persistence success."""

    def _queue_demo_run(self, patient_record, **kwargs):
        defaults = {
            "status": "queued",
            "intent": "demographics_only",
            "max_attempts": 3,
            "parameters_json": {
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def _stages(self, run):
        return {
            m.stage_name: m.status
            for m in IngestionRunStageMetric.objects.filter(run=run)
        }

    def test_empty_payload_cannot_succeed_or_persist(self):
        run = self._queue_demo_run("DEMO-ID-1")
        mock_adapter = _make_adapter_mock(demographics_result={})
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".upsert_patient_demographics"
        ) as mock_upsert:
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "queued"  # requeued (attempts remain)
        stages = self._stages(run)
        assert stages.get("demographics_extraction") == "failed"
        assert "demographics_persistence" not in stages
        mock_upsert.assert_not_called()
        # No clinical writes for the failed run.
        from apps.patients.models import Patient

        assert not Patient.objects.filter(patient_source_key="DEMO-ID-1").exists()

    def test_all_empty_mapping_cannot_succeed(self):
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
        )

        run = self._queue_demo_run("DEMO-ID-2")
        empty_all = {key: "" for key in DEMOGRAPHIC_FIELD_SELECTORS}
        mock_adapter = _make_adapter_mock(demographics_result=empty_all)
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "queued"
        stages = self._stages(run)
        assert stages.get("demographics_extraction") == "failed"
        assert "demographics_persistence" not in stages

    @pytest.mark.parametrize("bad_prontuario", ["", "   ", None, 14160147])
    def test_invalid_prontuario_cannot_persist(self, bad_prontuario):
        run = self._queue_demo_run("DEMO-ID-3")
        payload = {"prontuario": bad_prontuario, "nome": "X"}
        mock_adapter = _make_adapter_mock(demographics_result=payload)
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "queued"  # retryable
        stages = self._stages(run)
        assert stages.get("demographics_extraction") == "failed"
        assert "demographics_persistence" not in stages
        # Sanitized: no extracted value leaks into the run error field.
        assert "MARIA" not in (run.error_message or "")

    def test_mismatched_identity_fails_before_persistence(self):
        from apps.patients.models import Patient

        run = self._queue_demo_run("DEMO-2")
        mock_adapter = _make_adapter_mock(
            demographics_result=_demo_demographics("DEMO-1"),  # mismatch
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"
            ".upsert_patient_demographics"
        ) as mock_upsert:
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "queued"
        stages = self._stages(run)
        assert stages.get("demographics_extraction") == "failed"
        assert "demographics_persistence" not in stages
        mock_upsert.assert_not_called()
        # No Patient written for the requested or extracted identity.
        assert not Patient.objects.filter(patient_source_key="DEMO-2").exists()
        assert not Patient.objects.filter(patient_source_key="DEMO-1").exists()
        # Sanitized error message.
        assert "DEMO-1" not in (run.error_message or "")
        assert "DEMO-2" not in (run.error_message or "")

    def test_normalized_equivalents_accepted(self):
        """Punctuation/whitespace vs digits normalize to the same record."""
        from apps.patients.models import Patient

        run = self._queue_demo_run("141/60147-A")
        payload = _demo_demographics(" 14160147 ")
        mock_adapter = _make_adapter_mock(demographics_result=payload)
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert Patient.objects.filter(patient_source_key="141/60147-A").exists()

    def test_valid_matching_with_sparse_optional_fields_accepted(self):
        from apps.patients.models import Patient

        run = self._queue_demo_run("DEMO-ID-4")
        payload = {"prontuario": "DEMO-ID-4", "nome": "SPARSE"}
        mock_adapter = _make_adapter_mock(demographics_result=payload)
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "succeeded"
        patient = Patient.objects.get(patient_source_key="DEMO-ID-4")
        assert patient.name == "SPARSE"


@pytest.mark.django_db
class TestDemographicsFailureLifecycle:
    """R4: source failures reach the existing extraction-failure lifecycle."""

    def _queue(self, patient_record, max_attempts):
        return IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            max_attempts=max_attempts,
            parameters_json={
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        )

    def test_retryable_failure_requeues_and_keeps_batch_open(self):
        from apps.ingestion.models import CensusExecutionBatch

        batch = CensusExecutionBatch.objects.create()
        run = self._queue("DEMO-LC-1", max_attempts=3)
        run.batch = batch
        run.save(update_fields=["batch"])
        mock_adapter = _make_adapter_mock(
            demographics_fail_mode="extraction_error",
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "queued"  # requeued (attempts remain)
        assert run.attempt_count == 1
        assert run.next_retry_at is not None
        # Batch stays open while a retry remains.
        assert batch.status != "succeeded"
        assert batch.finished_at is None

    def test_terminal_failure_marks_run_failed_and_closes_batch_failed(self):
        from apps.ingestion.models import CensusExecutionBatch
        from apps.patients.models import Patient

        batch = CensusExecutionBatch.objects.create()
        run = self._queue("DEMO-LC-2", max_attempts=1)
        run.batch = batch
        run.save(update_fields=["batch"])
        mock_adapter = _make_adapter_mock(
            demographics_fail_mode="extraction_error",
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"  # terminal
        assert run.attempt_count == 1
        attempt = run.attempts.order_by("-attempt_number").first()
        assert attempt.status == "failed"
        # A terminal failure drains the batch and marks it failed.
        assert batch.status == "failed"
        assert batch.finished_at is not None
        # No clinical write and no persistence stage for the failed run.
        assert not Patient.objects.filter(
            patient_source_key="DEMO-LC-2"
        ).exists()
        stages = {
            m.stage_name
            for m in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert "demographics_persistence" not in stages


class _ReadyFailingStubSession:
    """Minimal ready SessionHandle whose open_tab always fails.

    Used to drive the REAL adapter stub path through the command so the
    sanitized stub-navigation error is observable end to end.
    """

    def get_page_html(self) -> str:
        return (
            "<html><body>"
            '<div id="tempoSessao" class="tempo-sessao">'
            "Tempo: <span>00</span>:<span>29</span>:<span>01</span>"
            "</div></body></html>"
        )

    def is_connected(self) -> bool:
        return True

    def click_selector(self, selector: str) -> None:  # noqa: ARG002
        pass

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:  # noqa: ARG002
        return False

    def get_tab_classes(self) -> list[str]:
        return ["tabs-first tabs-last tabs-selected"]

    def close_last_non_root_tab(self) -> None:
        pass

    def restart_browser(self) -> None:
        pass


@pytest.mark.django_db
class TestDemographicsStubSanitizationDispatch:
    """R5: a stub navigation failure exposes no URL or patient record in any
    command-level error field when tested through dispatch."""

    def test_stub_nav_failure_no_patient_in_run_or_stage_errors(self):
        sentinel = "SENTINEL-REC-9000"
        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            max_attempts=1,
            parameters_json={
                "patient_record": sentinel,
                "intent": "demographics_only",
            },
        )
        # Drive the REAL adapter (do not mock _create_adapter); inject a
        # ready session whose open_tab fails so the stub path raises.
        with patch.object(
            PersistentWorkerCommand,
            "_create_session_handle",
            return_value=_ReadyFailingStubSession(),
        ):
            call_command("process_ingestion_runs_persistent_session", max_runs=1)

        run.refresh_from_db()
        assert run.status == "failed"
        # The sentinel patient record and any URL must be absent from every
        # persisted error surface.
        assert sentinel not in (run.error_message or "")
        attempt = run.attempts.order_by("-attempt_number").first()
        assert attempt is not None
        assert sentinel not in (attempt.error_message or "")
        for metric in IngestionRunStageMetric.objects.filter(run=run):
            blob = str(metric.details_json or "")
            assert sentinel not in blob
            assert "/demographics/" not in blob
