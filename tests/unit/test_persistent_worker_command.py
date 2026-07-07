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
        """The --real-handle flag docs acknowledge the bridge but keep
        guarded rollout status."""
        import inspect
        source = inspect.getsource(PersistentWorkerCommand)
        assert "--real-handle" in source
        assert "RealHandleBridge" in source
        assert "NOT production-validated" in source \
            or "integration experiment" in source
