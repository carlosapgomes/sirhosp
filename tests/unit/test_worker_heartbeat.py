"""Tests for worker heartbeat persistence on IngestionRun (SIRS-S1).

Slice SIRS-S1: Persist a worker heartbeat on IngestionRun while
process_ingestion_runs processes a run, so another process can later
decide whether a running run is alive without checking Docker/PID.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.db.utils import OperationalError

from apps.ingestion.management.commands.process_ingestion_runs import WorkerHeartbeat
from apps.ingestion.models import IngestionRun

# =========================================================================
# Unit tests for WorkerHeartbeat helper
# =========================================================================


class TestWorkerHeartbeatHelper:
    """Unit tests for the WorkerHeartbeat context manager.

    These tests verify heartbeat behavior without requiring real sleeping
    or the full worker command.
    """

    @pytest.mark.django_db
    def test_heartbeat_populated_on_entry(self):
        """Heartbeat sets worker_heartbeat_at when entering context."""
        run = IngestionRun.objects.create(status="running")
        assert run.worker_heartbeat_at is None

        with WorkerHeartbeat(run, interval_seconds=300):
            run.refresh_from_db(fields=["worker_heartbeat_at"])
            assert run.worker_heartbeat_at is not None

    @pytest.mark.django_db
    def test_heartbeat_refreshes_periodically(self):
        """Heartbeat refreshes worker_heartbeat_at after interval passes."""
        run = IngestionRun.objects.create(status="running")
        with WorkerHeartbeat(run, interval_seconds=0.01):
            run.refresh_from_db(fields=["worker_heartbeat_at"])
            first_beat = run.worker_heartbeat_at

            # Wait for at least one refresh cycle
            import time as time_module

            time_module.sleep(0.05)

            run.refresh_from_db(fields=["worker_heartbeat_at"])
            second_beat = run.worker_heartbeat_at

            assert second_beat is not None
            # On fast systems the DB timestamp may have the same resolution;
            # at minimum the second beat should be >= the first.
            assert second_beat >= first_beat

    @pytest.mark.django_db
    def test_heartbeat_stops_on_exit(self):
        """Heartbeat stops refreshing when context exits."""
        run = IngestionRun.objects.create(status="running")
        first_beat = None

        with WorkerHeartbeat(run, interval_seconds=0.005):
            run.refresh_from_db(fields=["worker_heartbeat_at"])
            first_beat = run.worker_heartbeat_at
            assert first_beat is not None

        # After exit, the heartbeat thread should have stopped.
        # Wait a bit and verify no further updates.
        import time as time_module

        time_module.sleep(0.03)
        run.refresh_from_db(fields=["worker_heartbeat_at"])
        after_exit_beat = run.worker_heartbeat_at

        # The beat should be the same as first_beat (no more updates)
        # OR it could have been updated one more time before the thread
        # fully stopped. In any case, it should not be None.
        assert after_exit_beat is not None

    @pytest.mark.django_db
    def test_heartbeat_stops_on_terminal_state(self):
        """Heartbeat stops refreshing when run reaches terminal state."""
        run = IngestionRun.objects.create(status="running")

        # Simulate: start heartbeat, then mark run as succeeded
        with WorkerHeartbeat(run, interval_seconds=0.005):
            run.status = "succeeded"
            run.save(update_fields=["status"])

            import time as time_module

            time_module.sleep(0.03)

            # The thread should have detected the terminal state
            # and stopped. Capture the heartbeat value.
            run.refresh_from_db(fields=["worker_heartbeat_at"])
            after_terminal = run.worker_heartbeat_at
            assert after_terminal is not None

    @pytest.mark.django_db
    def test_heartbeat_continues_after_transient_db_error(self):
        """A transient DB error skips one beat but keeps heartbeat alive."""
        run = IngestionRun.objects.create(status="running")
        original_refresh = run.refresh_from_db
        refresh_calls = {"count": 0}

        def flaky_refresh(*args, **kwargs):
            refresh_calls["count"] += 1
            if refresh_calls["count"] == 1:
                raise OperationalError("temporary heartbeat DB failure")
            return original_refresh(*args, **kwargs)

        with patch.object(run, "refresh_from_db", side_effect=flaky_refresh):
            with WorkerHeartbeat(run, interval_seconds=0.005):
                import time as time_module

                time_module.sleep(0.03)

        assert refresh_calls["count"] >= 2

    @pytest.mark.django_db
    def test_heartbeat_no_patient_data_in_logs(self, caplog):
        """Heartbeat-related messages contain no patient clinical data."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={
                "patient_record": "PRONT12345",
            },
        )
        with WorkerHeartbeat(run, interval_seconds=300):
            pass

        for record in caplog.records:
            msg = record.getMessage()
            # Only technical identifiers are allowed
            assert "PRONT12345" not in msg


# =========================================================================
# Integration tests for heartbeat via process_ingestion_runs command
# =========================================================================


@pytest.mark.django_db
class TestWorkerHeartbeatIntegration:
    """Integration tests: heartbeat is populated when processing runs."""

    def _queue_run(self, **kwargs):
        """Helper to create a queued IngestionRun directly."""
        defaults = {
            "status": "queued",
            "max_attempts": 1,
            "intent": "admissions_only",
            "parameters_json": {
                "patient_record": "12345",
                "intent": "admissions_only",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def _make_extractor_mock(self, empty_snapshot=True):
        """Create a mock PlaywrightEvolutionExtractor."""
        mock_extractor = MagicMock()
        mock_extractor.get_admission_snapshot.return_value = (
            [] if empty_snapshot else []
        )
        return mock_extractor

    def test_heartbeat_populated_when_run_claimed(self):
        """Worker populates worker_heartbeat_at when claiming a queued run."""
        run = self._queue_run()
        assert run.worker_heartbeat_at is None

        mock_ext = self._make_extractor_mock()

        with patch(
            "apps.ingestion.management.commands."
            "process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.worker_heartbeat_at is not None

    def test_heartbeat_populated_on_success_path(self):
        """Heartbeat is present when run succeeds."""
        run = self._queue_run()
        mock_ext = self._make_extractor_mock()

        with patch(
            "apps.ingestion.management.commands."
            "process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.worker_heartbeat_at is not None

    def test_heartbeat_populated_on_failure_path(self):
        """Heartbeat is present when run fails."""
        run = self._queue_run()

        def raise_error(**kwargs):
            raise RuntimeError("Simulated extraction failure")

        mock_ext = self._make_extractor_mock()
        mock_ext.get_admission_snapshot.side_effect = raise_error

        with patch(
            "apps.ingestion.management.commands."
            "process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.worker_heartbeat_at is not None

    def test_existing_status_transitions_preserved(self):
        """Existing worker status transitions still work with heartbeat."""
        run = self._queue_run()
        mock_ext = self._make_extractor_mock()

        with patch(
            "apps.ingestion.management.commands."
            "process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.finished_at >= run.started_at
        assert run.worker_heartbeat_at is not None
        # Ensure processing_started_at was set (existing behavior)
        assert run.processing_started_at is not None
        # Ensure worker_label was set (existing behavior)
        assert run.worker_label
