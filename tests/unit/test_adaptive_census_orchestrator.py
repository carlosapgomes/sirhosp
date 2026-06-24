"""Unit tests for the adaptive census orchestrator (Slice ACO-S1).

Covers:
- Drained queue → eligible
- Active queued/running runs → blocked with aggregate counts
- Open CensusExecutionBatch → blocked
- Cooldown → blocked when too soon
- Stale running runs → reported without mutation
- Dry-run management command → non-mutating output
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.census.orchestration import OrchestratorDecision, compute_orchestrator_state
from apps.ingestion.models import CensusExecutionBatch, IngestionRun

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    status: str = "queued",
    intent: str = "full_sync",
    **overrides,
) -> IngestionRun:
    defaults = dict(
        status=status,
        intent=intent,
        queued_at=timezone.now(),
        processing_started_at=timezone.now() if status == "running" else None,
    )
    defaults.update(overrides)
    run = IngestionRun.objects.create(**defaults)
    # Fields with auto_now_add=True (like started_at) must be updated
    # after creation via update() to override the auto-set value.
    if "started_at" in overrides:
        IngestionRun.objects.filter(pk=run.pk).update(started_at=overrides["started_at"])
        run.refresh_from_db()
    return run


def _make_open_batch() -> CensusExecutionBatch:
    return CensusExecutionBatch.objects.create(status="running")


def _make_closed_batch() -> CensusExecutionBatch:
    return CensusExecutionBatch.objects.create(
        status="succeeded",
        finished_at=timezone.now(),
    )


# ===========================================================================
# compute_orchestrator_state
# ===========================================================================


@pytest.mark.django_db
class TestComputeOrchestratorStateEligible:
    """Queue is eligible when empty and no open batch exists."""

    def test_no_runs_and_no_batch(self):
        """No IngestionRun and no open batch → eligible."""
        decision = compute_orchestrator_state()
        assert decision.eligible is True
        assert decision.blocked_reason == ""

    def test_only_succeeded_runs(self):
        """Only succeeded/failed runs → eligible."""
        _make_run(status="succeeded", intent="full_sync")
        _make_run(status="failed", intent="full_sync")
        decision = compute_orchestrator_state()
        assert decision.eligible is True
        assert decision.blocked_reason == ""

    def test_only_closed_batch(self):
        """Only closed batch → eligible."""
        _make_closed_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is True
        assert decision.blocked_reason == ""

    def test_no_runs_and_closed_batch(self):
        """No runs + closed batch → eligible."""
        _make_closed_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is True


# ---------------------------------------------------------------------------
# Blocked by active runs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeOrchestratorStateBlockedByActiveRuns:
    """Queue is blocked when active IngestionRun records exist."""

    def test_queued_run_blocks(self):
        """A single queued run blocks the cycle."""
        _make_run(status="queued")
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert "queued" in decision.blocked_reason.lower()
        assert decision.active_queued >= 1

    def test_running_run_blocks(self):
        """A single running run blocks the cycle."""
        _make_run(status="running")
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert "running" in decision.blocked_reason.lower()
        assert decision.active_running >= 1

    def test_multiple_active_runs_block_with_counts(self):
        """Multiple queued and running runs block with aggregate counts."""
        _make_run(status="queued")
        _make_run(status="queued")
        _make_run(status="running")
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert decision.active_queued == 2
        assert decision.active_running == 1

    def test_succeeded_run_ignored_in_active_count(self):
        """Succeeded runs are not counted as active."""
        _make_run(status="queued")
        _make_run(status="succeeded")
        _make_run(status="failed")
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert decision.active_queued == 1
        assert decision.active_running == 0


# ---------------------------------------------------------------------------
# Blocked by open batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeOrchestratorStateBlockedByOpenBatch:
    """An open CensusExecutionBatch blocks a new cycle."""

    def test_open_batch_blocks(self):
        """Open batch (no finished_at) blocks the cycle."""
        _make_open_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert "batch" in decision.blocked_reason.lower()
        assert decision.open_batch_exists is True

    def test_open_batch_even_without_runs(self):
        """Open batch blocks even when no runs exist."""
        _make_open_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert decision.open_batch_exists is True

    def test_closed_batch_does_not_block(self):
        """Closed batch does not block."""
        _make_closed_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is True
        assert decision.open_batch_exists is False

    def test_open_batch_takes_precedence(self):
        """Open batch blocks even when queue is idle."""
        _make_open_batch()
        decision = compute_orchestrator_state()
        assert decision.eligible is False
        assert decision.open_batch_exists is True
        assert decision.active_queued == 0
        assert decision.active_running == 0


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeOrchestratorStateCooldown:
    """Cooldown blocks when the latest successful census extraction is recent."""

    def test_cooldown_blocks_when_recent_census(self):
        """Latest successful census extraction is newer than min interval."""
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=10),
        )
        decision = compute_orchestrator_state(min_interval_minutes=30)
        assert decision.eligible is False
        assert "cooldown" in decision.blocked_reason.lower()
        assert decision.cooldown_remaining_minutes is not None
        assert decision.cooldown_remaining_minutes > 0

    def test_cooldown_allows_when_old_enough(self):
        """Latest successful census extraction is older than min interval."""
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=60),
        )
        decision = compute_orchestrator_state(min_interval_minutes=30)
        assert decision.eligible is True
        assert decision.cooldown_remaining_minutes is None

    def test_cooldown_ignored_when_no_census_run(self):
        """No previous census extraction → no cooldown, eligible."""
        decision = compute_orchestrator_state(min_interval_minutes=30)
        assert decision.eligible is True
        assert decision.cooldown_remaining_minutes is None

    def test_cooldown_only_considers_census_extraction(self):
        """Only census_extraction runs affect cooldown, not full_sync."""
        _make_run(
            status="succeeded",
            intent="full_sync",
            started_at=timezone.now() - timedelta(minutes=5),
        )
        decision = compute_orchestrator_state(min_interval_minutes=30)
        assert decision.eligible is True
        assert decision.cooldown_remaining_minutes is None

    def test_cooldown_checks_started_at_of_latest_successful(self):
        """Cooldown uses started_at of the latest successful census_extraction."""
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=45),
        )
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=5),
        )
        decision = compute_orchestrator_state(min_interval_minutes=30)
        # Latest is 5 min ago
        assert decision.eligible is False
        assert decision.cooldown_remaining_minutes is not None
        assert decision.cooldown_remaining_minutes > 0

    def test_failed_census_does_not_set_cooldown(self):
        """Failed census extraction does not affect cooldown."""
        _make_run(
            status="failed",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=5),
        )
        decision = compute_orchestrator_state(min_interval_minutes=30)
        assert decision.eligible is True
        assert decision.cooldown_remaining_minutes is None


# ---------------------------------------------------------------------------
# Stale running runs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeOrchestratorStateStaleRunning:
    """Stale running runs are detected without mutation."""

    def test_stale_running_detected(self):
        """Running run older than stale threshold is reported as stale."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        decision = compute_orchestrator_state(stale_running_minutes=180)
        assert decision.eligible is False
        assert decision.stale_running_count >= 1
        assert "stale" in decision.blocked_reason.lower()

    def test_fresh_running_not_stale(self):
        """Running run newer than stale threshold is not stale."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(minutes=10),
            processing_started_at=timezone.now() - timedelta(minutes=10),
        )
        decision = compute_orchestrator_state(stale_running_minutes=180)
        assert decision.eligible is False  # blocked by active run, but not stale
        assert decision.stale_running_count == 0

    def test_stale_running_uses_queued_at_when_processing_start_is_missing(self):
        """Running run with no processing start falls back to queued_at."""
        _make_run(
            status="running",
            queued_at=timezone.now() - timedelta(hours=4),
            processing_started_at=None,
        )
        decision = compute_orchestrator_state(stale_running_minutes=180)
        assert decision.eligible is False
        assert decision.stale_running_count == 1
        assert "stale" in decision.blocked_reason.lower()

    def test_stale_runs_reported_in_blocked_reason(self):
        """Stale runs appear in operator output."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        decision = compute_orchestrator_state(stale_running_minutes=180)
        assert "stale" in decision.blocked_reason.lower()
        assert decision.stale_running_count >= 1

    def test_multiple_stale_runs(self):
        """Multiple stale running runs are counted."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=5),
            processing_started_at=timezone.now() - timedelta(hours=5),
        )
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        decision = compute_orchestrator_state(stale_running_minutes=180)
        assert decision.stale_running_count == 2

    def test_stale_detection_no_mutation(self):
        """Stale detection does not modify any database rows."""
        run = _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        original_status = run.status
        compute_orchestrator_state(stale_running_minutes=180)
        run.refresh_from_db()
        assert run.status == original_status
        assert run.status == "running"


# ---------------------------------------------------------------------------
# Management command: run_adaptive_census_cycles --dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunAdaptiveCensusCyclesDryRun:
    """Dry-run prints a decision and creates no database rows."""

    def test_dry_run_no_runs(self):
        """Dry-run with clean state reports eligible and creates no rows."""
        run_count_before = IngestionRun.objects.count()
        batch_count_before = CensusExecutionBatch.objects.count()

        out = io.StringIO()
        call_command("run_adaptive_census_cycles", "--dry-run", stdout=out)
        output = out.getvalue()

        assert IngestionRun.objects.count() == run_count_before
        assert CensusExecutionBatch.objects.count() == batch_count_before
        assert "eligible" in output.lower() or "would start" in output.lower()

    def test_dry_run_blocked_by_active_run(self):
        """Dry-run with active run reports blocked and creates no rows."""
        _make_run(status="queued")
        run_count_before = IngestionRun.objects.count()
        batch_count_before = CensusExecutionBatch.objects.count()

        out = io.StringIO()
        call_command("run_adaptive_census_cycles", "--dry-run", stdout=out)
        output = out.getvalue()

        assert IngestionRun.objects.count() == run_count_before
        assert CensusExecutionBatch.objects.count() == batch_count_before
        assert "blocked" in output.lower() or "not start" in output.lower()

    def test_dry_run_blocked_by_open_batch(self):
        """Dry-run with open batch reports blocked and creates no rows."""
        _make_open_batch()
        run_count_before = IngestionRun.objects.count()
        batch_count_before = CensusExecutionBatch.objects.count()

        out = io.StringIO()
        call_command("run_adaptive_census_cycles", "--dry-run", stdout=out)
        output = out.getvalue()

        assert IngestionRun.objects.count() == run_count_before
        assert CensusExecutionBatch.objects.count() == batch_count_before
        assert "batch" in output.lower()

    def test_dry_run_cooldown(self):
        """Dry-run during cooldown reports blocked and creates no rows."""
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=5),
        )
        run_count_before = IngestionRun.objects.count()
        batch_count_before = CensusExecutionBatch.objects.count()

        out = io.StringIO()
        call_command(
            "run_adaptive_census_cycles",
            "--dry-run",
            "--min-interval-minutes",
            "30",
            stdout=out,
        )
        output = out.getvalue()

        assert IngestionRun.objects.count() == run_count_before
        assert CensusExecutionBatch.objects.count() == batch_count_before
        assert "cooldown" in output.lower()

    def test_dry_run_stale_running(self):
        """Dry-run with stale running reports blocked and creates no rows."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        run_count_before = IngestionRun.objects.count()
        batch_count_before = CensusExecutionBatch.objects.count()

        out = io.StringIO()
        call_command(
            "run_adaptive_census_cycles",
            "--dry-run",
            "--stale-running-minutes",
            "180",
            stdout=out,
        )
        output = out.getvalue()

        assert IngestionRun.objects.count() == run_count_before
        assert CensusExecutionBatch.objects.count() == batch_count_before
        assert "stale" in output.lower()

    def test_dry_run_no_mutation_of_stale_runs(self):
        """Dry-run does not change stale run status."""
        run = _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        call_command(
            "run_adaptive_census_cycles",
            "--dry-run",
            "--stale-running-minutes",
            "180",
        )
        run.refresh_from_db()
        assert run.status == "running"

    def test_dry_run_defaults_work(self):
        """Dry-run works with default parameters (no args needed)."""
        out = io.StringIO()
        # Should not raise
        call_command("run_adaptive_census_cycles", "--dry-run", stdout=out)
        assert len(out.getvalue()) > 0


# ---------------------------------------------------------------------------
# Decision dataclass output safety
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestratorDecisionSafety:
    """Decision output contains safe operational data only."""

    def test_decision_no_patient_data(self):
        """Blocked reason contains no patient names or clinical text."""
        _make_run(status="queued")
        decision = compute_orchestrator_state()
        unsafe_terms = ["nome", "patient", "prontuario", "diagnosis", "clinical"]
        for term in unsafe_terms:
            assert term.lower() not in decision.blocked_reason.lower()

    def test_decision_contains_aggregate_counts(self):
        """Decision includes aggregate counts when blocked."""
        _make_run(status="queued")
        _make_run(status="queued")
        _make_run(status="running")
        decision = compute_orchestrator_state()
        assert decision.active_queued == 2
        assert decision.active_running == 1


# ===========================================================================
# Slice ACO-S2: PG advisory lock
# ===========================================================================


@pytest.mark.django_db(transaction=True)
class TestAdvisoryLock:
    """PostgreSQL advisory lock for orchestrator coordination."""

    def test_acquire_lock_returns_true_when_free(self):
        """pg_try_advisory_lock returns True when lock is available."""
        from apps.census.orchestration import acquire_orchestrator_lock, release_orchestrator_lock

        acquired = acquire_orchestrator_lock()
        assert acquired is True
        release_orchestrator_lock()

    def test_acquire_lock_returns_false_when_held(self):
        """pg_try_advisory_lock returns False when another session holds lock."""
        import psycopg
        from django.db import connection

        from apps.census.orchestration import (
            ADVISORY_LOCK_KEY,
            acquire_orchestrator_lock,
        )

        settings = connection.settings_dict
        other_conn = psycopg.connect(
            host=settings["HOST"],
            port=settings["PORT"],
            dbname=settings["NAME"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        )
        other_conn.execute(
            "SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY]
        )
        try:
            acquired = acquire_orchestrator_lock()
            assert acquired is False
        finally:
            other_conn.execute(
                "SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY]
            )
            other_conn.close()

    def test_release_lock_returns_true(self):
        """pg_advisory_unlock returns True when lock was held."""
        from apps.census.orchestration import acquire_orchestrator_lock, release_orchestrator_lock

        acquire_orchestrator_lock()
        released = release_orchestrator_lock()
        assert released is True

    def test_double_release_returns_false(self):
        """pg_advisory_unlock returns False when no lock was held."""
        from apps.census.orchestration import release_orchestrator_lock

        released = release_orchestrator_lock()
        assert released is False


# ===========================================================================
# Slice ACO-S2: run_single_cycle
# ===========================================================================


@pytest.mark.django_db(transaction=True)
class TestRunSingleCycleBlocked:
    """--once mode skips safely when the system is blocked."""

    def test_skips_when_queue_has_active_runs(self):
        """Blocked by active runs -> no extraction, no processing."""
        _make_run(status="queued")
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            result = run_single_cycle()

        assert result["cycle_executed"] is False
        assert "blocked" in result["outcome"]
        mock_call.assert_not_called()

    def test_skips_when_open_batch_exists(self):
        """Blocked by open batch -> no extraction, no processing."""
        _make_open_batch()
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            result = run_single_cycle()

        assert result["cycle_executed"] is False
        assert "blocked" in result["outcome"]
        mock_call.assert_not_called()

    def test_skips_when_cooldown_active(self):
        """Blocked by cooldown -> no extraction, no processing."""
        _make_run(
            status="succeeded",
            intent="census_extraction",
            started_at=timezone.now() - timedelta(minutes=5),
        )
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            result = run_single_cycle(min_interval_minutes=30)

        assert result["cycle_executed"] is False
        assert "blocked" in result["outcome"]
        mock_call.assert_not_called()

    def test_skips_when_stale_running(self):
        """Blocked by stale running -> no extraction, no processing."""
        _make_run(
            status="running",
            started_at=timezone.now() - timedelta(hours=4),
            processing_started_at=timezone.now() - timedelta(hours=4),
        )
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            result = run_single_cycle(stale_running_minutes=180)

        assert result["cycle_executed"] is False
        assert "blocked" in result["outcome"]
        mock_call.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestRunSingleCycleLockRejected:
    """Lock already held -> does not run extraction."""

    def test_lock_held_does_not_run_extraction(self):
        """When PG advisory lock is held, the cycle is skipped."""
        import psycopg
        from django.db import connection

        from apps.census.orchestration import (
            ADVISORY_LOCK_KEY,
            run_single_cycle,
        )

        settings = connection.settings_dict
        other_conn = psycopg.connect(
            host=settings["HOST"],
            port=settings["PORT"],
            dbname=settings["NAME"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        )
        other_conn.execute(
            "SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY]
        )
        try:
            with mock.patch("apps.census.orchestration.call_command") as mock_call:
                result = run_single_cycle()

            assert result["cycle_executed"] is False
            assert "lock" in result["outcome"].lower()
            mock_call.assert_not_called()
        finally:
            other_conn.execute(
                "SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY]
            )
            other_conn.close()


@pytest.mark.django_db(transaction=True)
class TestRunSingleCycleSuccessful:
    """Successful cycle calls extract_census, then process_census_snapshot with run id."""

    def _simulate_extraction(self):
        """Simulate what extract_census does: create a succeeded census_extraction run."""
        run = IngestionRun.objects.create(
            status="succeeded",
            intent="census_extraction",
            queued_at=timezone.now(),
            processing_started_at=timezone.now(),
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        return run

    def test_successful_cycle_calls_both_commands(self):
        """Eligible system -> extract_census called, then process_census_snapshot with run_id."""
        from apps.census.orchestration import run_single_cycle

        created_run = None

        def mock_extract_census(*args, **kwargs):
            nonlocal created_run
            created_run = self._simulate_extraction()

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            mock_call.side_effect = lambda *a, **kw: (
                mock_extract_census(*a, **kw)
                if "extract_census" in str(a)
                else None
            )
            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "success"
        assert result["extraction_run_id"] is not None

        process_calls = [
            c for c in mock_call.call_args_list
            if "process_census_snapshot" in str(c)
        ]
        assert len(process_calls) == 1

    def test_process_called_with_detected_run_id(self):
        """process_census_snapshot receives the exact run_id from extraction."""
        from apps.census.orchestration import run_single_cycle

        created_run = None

        def mock_extract(*args, **kwargs):
            nonlocal created_run
            created_run = self._simulate_extraction()

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    mock_extract()
                return None
            mock_call.side_effect = side_effect

            run_single_cycle()

        process_calls = [
            c for c in mock_call.call_args_list
            if c[0][0] == "process_census_snapshot"
        ]
        assert len(process_calls) == 1
        _, process_kwargs = process_calls[0]
        assert process_kwargs.get("run_id") == created_run.pk


@pytest.mark.django_db(transaction=True)
class TestRunSingleCycleExtractionFailure:
    """Extraction failure prevents snapshot processing."""

    def test_extraction_exception_skips_processing(self):
        """When extract_census raises, process_census_snapshot is not called."""
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    raise RuntimeError("Extraction failed")
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "extraction_failed"
        assert "error" in result

        process_calls = [c for c in mock_call.call_args_list if "process_census_snapshot" in str(c)]
        assert len(process_calls) == 0

    def test_extraction_failure_skips_processing(self):
        """When extract_census raises an exception, processing is skipped."""
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    raise RuntimeError("Extraction failed")
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "extraction_failed"

        process_calls = [c for c in mock_call.call_args_list if "process_census_snapshot" in str(c)]
        assert len(process_calls) == 0

    def test_no_succeeded_run_is_ambiguous(self):
        """When extract_census produces no succeeded run, outcome is ambiguous_runs."""
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    # Simulate extraction that creates only a failed run
                    IngestionRun.objects.create(
                        status="failed", intent="census_extraction",
                        queued_at=timezone.now(), processing_started_at=timezone.now(),
                        started_at=timezone.now(), finished_at=timezone.now(),
                    )
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "ambiguous_runs"

        process_calls = [c for c in mock_call.call_args_list if "process_census_snapshot" in str(c)]
        assert len(process_calls) == 0

    def test_extraction_systemexit_is_controlled(self):
        """The real extract_census signals failure via sys.exit(1) (SystemExit).

        SystemExit is a BaseException, not an Exception subclass, so a naive
        ``except Exception`` lets it escape and crashes the process instead of
        returning a structured ``extraction_failed`` outcome. The orchestrator
        must control it and report failure, not propagate the SystemExit.
        """
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    # Mirrors ``sys.exit(1)`` in the real extract_census command.
                    raise SystemExit(1)
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "extraction_failed"
        assert "error" in result

        process_calls = [
            c for c in mock_call.call_args_list
            if "process_census_snapshot" in str(c)
        ]
        assert len(process_calls) == 0


@pytest.mark.django_db(transaction=True)
class TestRunSingleCycleAmbiguousRuns:
    """Zero or multiple new extraction runs -> fail safe, no processing."""

    def test_zero_new_runs_aborts(self):
        """No new census_extraction run found after extraction -> fail safe."""
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    pass  # extract creates no run (e.g. silent failure)
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "ambiguous_runs"

        process_calls = [c for c in mock_call.call_args_list if "process_census_snapshot" in str(c)]
        assert len(process_calls) == 0

    def test_multiple_new_runs_aborts(self):
        """Multiple new census_extraction runs -> fail safe, no processing."""
        from apps.census.orchestration import run_single_cycle

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    IngestionRun.objects.create(
                        status="succeeded", intent="census_extraction",
                        queued_at=timezone.now(), processing_started_at=timezone.now(),
                        started_at=timezone.now(), finished_at=timezone.now(),
                    )
                    IngestionRun.objects.create(
                        status="succeeded", intent="census_extraction",
                        queued_at=timezone.now(), processing_started_at=timezone.now(),
                        started_at=timezone.now(), finished_at=timezone.now(),
                    )
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "ambiguous_runs"

        process_calls = [c for c in mock_call.call_args_list if "process_census_snapshot" in str(c)]
        assert len(process_calls) == 0

    def test_existing_runs_not_counted(self):
        """Runs created before this cycle are not counted as new."""
        _make_run(
            status="succeeded", intent="census_extraction",
            started_at=timezone.now() - timedelta(hours=2),
        )
        from apps.census.orchestration import run_single_cycle

        created_run = None

        def mock_extract(*args, **kwargs):
            nonlocal created_run
            created_run = IngestionRun.objects.create(
                status="succeeded", intent="census_extraction",
                queued_at=timezone.now(), processing_started_at=timezone.now(),
                started_at=timezone.now(), finished_at=timezone.now(),
            )

        with mock.patch("apps.census.orchestration.call_command") as mock_call:
            def side_effect(command, **kwargs):
                if command == "extract_census":
                    mock_extract()
                return None
            mock_call.side_effect = side_effect

            result = run_single_cycle()

        assert result["cycle_executed"] is True
        assert result["outcome"] == "success"
        assert result["extraction_run_id"] == created_run.pk


# ===========================================================================
# Slice ACO-S2: Management command --once mode
# ===========================================================================


@pytest.mark.django_db(transaction=True)
class TestCommandOnceMode:
    """run_adaptive_census_cycles without --dry-run executes a single cycle."""

    @staticmethod
    def _mock_cmd_module():
        import apps.census.management.commands.run_adaptive_census_cycles as m
        return m

    def test_once_mode_output_uses_mocked_result(self):
        """Output reflects the run_single_cycle result dict."""
        from io import StringIO

        cmd_module = self._mock_cmd_module()
        with mock.patch.object(
            cmd_module, "run_single_cycle",
            return_value={
                "cycle_executed": False,
                "outcome": "blocked",
                "blocked_reason": "Active runs: 1 queued.",
                "message": "System blocked: Active runs: 1 queued.",
            },
        ):
            out = StringIO()
            call_command("run_adaptive_census_cycles", stdout=out)
            output = out.getvalue()
            assert "blocked" in output.lower()

    def test_once_mode_extraction_failure_output(self):
        """Output reports extraction failure."""
        from io import StringIO

        cmd_module = self._mock_cmd_module()
        with mock.patch.object(
            cmd_module, "run_single_cycle",
            return_value={
                "cycle_executed": True,
                "outcome": "extraction_failed",
                "error": "RuntimeError: Extraction failed",
                "message": "Census extraction failed.",
            },
        ):
            out = StringIO()
            call_command("run_adaptive_census_cycles", stdout=out)
            output = out.getvalue()
            assert "fail" in output.lower()

    def test_once_mode_success_output(self):
        """Output reports successful cycle."""
        from io import StringIO

        cmd_module = self._mock_cmd_module()
        with mock.patch.object(
            cmd_module, "run_single_cycle",
            return_value={
                "cycle_executed": True,
                "outcome": "success",
                "extraction_run_id": 42,
                "batch_id": 99,
                "message": "Cycle completed successfully",
            },
        ):
            out = StringIO()
            call_command("run_adaptive_census_cycles", stdout=out)
            output = out.getvalue()
            assert "success" in output.lower()
            assert "42" in output

    def test_once_mode_with_lock_held_output(self):
        """Output reports lock held."""
        from io import StringIO

        cmd_module = self._mock_cmd_module()
        with mock.patch.object(
            cmd_module, "run_single_cycle",
            return_value={
                "cycle_executed": False,
                "outcome": "lock_held",
                "message": "Another orchestrator holds the lock.",
            },
        ):
            out = StringIO()
            call_command("run_adaptive_census_cycles", stdout=out)
            output = out.getvalue()
            assert "lock" in output.lower()


# ===========================================================================
# Slice ACO-S3: Continuous loop behavior
# ===========================================================================


class TestRunLoopBlockedWaits:
    """Loop waits while blocked, logging reason and sleeping."""

    def test_loop_waits_and_stops_after_one_blocked_iteration(self):
        """Loop waits once while blocked, then stops."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        decision_patch = mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=OrchestratorDecision(
                eligible=False,
                blocked_reason="Active runs: 1 queued.",
                active_queued=1,
            ),
        )

        with (
            decision_patch,
            mock.patch("apps.census.orchestration.run_single_cycle") as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_not_called()
        mock_sleep.assert_called_once_with(10)

    def test_loop_rechecks_after_sleep_when_blocked(self):
        """After sleeping while blocked, loop rechecks state."""
        from apps.census.orchestration import run_loop

        call_count = 0

        def controlled_stop():
            nonlocal call_count
            call_count += 1
            return call_count > 3

        decision_patch = mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=OrchestratorDecision(
                eligible=False,
                blocked_reason="Active runs: 1 queued.",
                active_queued=1,
            ),
        )

        with (
            decision_patch as mock_decision,
            mock.patch("apps.census.orchestration.run_single_cycle") as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        # compute_orchestrator_state called 3 times (iter 0, 1, 2)
        assert mock_decision.call_count >= 3
        mock_cycle.assert_not_called()
        assert mock_sleep.call_count >= 2

    def test_loop_waits_due_to_cooldown(self):
        """Blocked by cooldown -> logs, sleeps, does not cycle."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        decision_patch = mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=OrchestratorDecision(
                eligible=False,
                blocked_reason="Cooldown (15 min remaining).",
                cooldown_remaining_minutes=15.0,
            ),
        )

        with (
            decision_patch,
            mock.patch("apps.census.orchestration.run_single_cycle") as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_not_called()
        mock_sleep.assert_called_once_with(10)


@pytest.mark.django_db(transaction=True)
class TestRunLoopExecutesCycle:
    """Loop executes a cycle when eligible."""

    def test_loop_executes_cycle_when_eligible(self):
        """When eligible, run_single_cycle is called once."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        eligible_decision = OrchestratorDecision(
            eligible=True,
            blocked_reason="",
        )

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                return_value=eligible_decision,
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "success",
                    "extraction_run_id": 42,
                    "batch_id": 99,
                    "message": "Census cycle completed successfully.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_called_once()
        # After success, no sleep needed (cooldown handles next cycle timing)
        mock_sleep.assert_not_called()

    def test_loop_executes_cycle_and_then_waits(self):
        """After successful cycle, loop rechecks and waits if blocked."""
        from apps.census.orchestration import run_loop

        call_count = 0

        def controlled_stop():
            nonlocal call_count
            call_count += 1
            return call_count > 2

        # First call: eligible, second call: blocked
        decisions = iter([
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(
                eligible=False,
                blocked_reason="Cooldown (5 min remaining).",
                cooldown_remaining_minutes=5.0,
            ),
        ])

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(decisions),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "success",
                    "extraction_run_id": 42,
                    "message": "Success.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_called_once()
        assert mock_sleep.call_count == 1


class TestRunLoopFailureBackoff:
    """After cycle failure, loop applies failure backoff."""

    def test_failure_backoff_triggers_after_extraction_failure(self):
        """After extraction_failed outcome, sleeps failure_backoff_minutes."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        decisions = iter([
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(eligible=True, blocked_reason=""),
        ])

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(decisions),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "extraction_failed",
                    "error": "RuntimeError: connection refused",
                    "message": "Census extraction failed.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                failure_backoff_minutes=5,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_called_once()
        # After failure, should sleep failure_backoff_minutes (5 min = 300s)
        mock_sleep.assert_called_once_with(300)

    def test_failure_backoff_uses_default_minutes(self):
        """Default failure_backoff_minutes is 30."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        decisions = iter([
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(eligible=True, blocked_reason=""),
        ])

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(decisions),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "extraction_failed",
                    "error": "Error",
                    "message": "Census extraction failed.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_called_once()
        # Default failure_backoff_minutes = 30 -> 1800s
        mock_sleep.assert_called_once_with(1800)

    def test_failure_backoff_after_ambiguous_runs(self):
        """Ambiguous_runs outcome also triggers failure backoff."""
        from apps.census.orchestration import run_loop

        iteration_count = 0

        def controlled_stop():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count > 1

        decisions = iter([
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(eligible=True, blocked_reason=""),
        ])

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(decisions),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "ambiguous_runs",
                    "message": "No new runs detected.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                failure_backoff_minutes=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        mock_cycle.assert_called_once()
        mock_sleep.assert_called_once_with(600)

    def test_loop_retries_after_failure_backoff(self):
        """After failure backoff, loop retries."""
        from apps.census.orchestration import run_loop

        call_count = 0

        def controlled_stop():
            nonlocal call_count
            call_count += 1
            return call_count > 2

        decisions = iter([
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(eligible=True, blocked_reason=""),
            OrchestratorDecision(eligible=True, blocked_reason=""),
        ])

        cycle_results = iter([
            {
                "cycle_executed": True,
                "outcome": "extraction_failed",
                "error": "Error",
                "message": "Failed.",
            },
            {
                "cycle_executed": True,
                "outcome": "success",
                "extraction_run_id": 42,
                "message": "Success.",
            },
        ])

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(decisions),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                side_effect=lambda min_interval_minutes=30,
                    stale_running_minutes=180: next(cycle_results),
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                failure_backoff_minutes=5,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        # run_single_cycle called twice (first fails, second succeeds)
        assert mock_cycle.call_count == 2
        # First call sleeps 300s (backoff), second call doesn't sleep (success -> no-op)
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(300)


class TestRunLoopSignalHandling:
    """SIGTERM and SIGINT cause graceful shutdown."""

    def test_loop_exits_on_sigterm_via_should_stop(self):
        """When should_stop returns True, loop exits immediately after iteration."""
        from apps.census.orchestration import run_loop

        with (
            mock.patch("apps.census.orchestration.compute_orchestrator_state") as mock_decision,
            mock.MagicMock() as mock_sleep,
        ):
            # should_stop returns True immediately -> loop should not iterate
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=lambda: True,
            )

        mock_decision.assert_not_called()
        mock_sleep.assert_not_called()

    def test_loop_exits_after_current_iteration(self):
        """Loop completes current iteration before checking should_stop."""
        from apps.census.orchestration import run_loop

        # First iteration eligible (cycle runs), should_stop becomes True after
        call_count = [0]

        def controlled_stop():
            call_count[0] += 1
            return call_count[0] > 1

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                return_value=OrchestratorDecision(eligible=True, blocked_reason=""),
            ),
            mock.patch(
                "apps.census.orchestration.run_single_cycle",
                return_value={
                    "cycle_executed": True,
                    "outcome": "success",
                    "extraction_run_id": 42,
                    "message": "Success.",
                },
            ) as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        # Cycle was executed (completed iteration) before stop check
        mock_cycle.assert_called_once()

    def test_loop_exits_gracefully_during_sleep(self):
        """Loop checks should_stop after sleep and exits."""
        from apps.census.orchestration import run_loop

        call_count = [0]

        def controlled_stop():
            call_count[0] += 1
            return call_count[0] > 1

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                return_value=OrchestratorDecision(
                    eligible=False,
                    blocked_reason="Active runs: 1 queued.",
                    active_queued=1,
                ),
            ),
            mock.patch("apps.census.orchestration.run_single_cycle") as mock_cycle,
            mock.MagicMock() as mock_sleep,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        # Slept once (blocked), rechecked, then stopped
        mock_sleep.assert_called_once_with(10)
        mock_cycle.assert_not_called()


class TestRunLoopCloseOldConnections:
    """Database connections are kept healthy in long-running mode."""

    def test_close_old_connections_called_on_each_iteration(self):
        """close_old_connections is called each loop iteration."""

        from apps.census.orchestration import run_loop

        call_count = [0]

        def controlled_stop():
            call_count[0] += 1
            return call_count[0] > 2

        with (
            mock.patch(
                "apps.census.orchestration.compute_orchestrator_state",
                return_value=OrchestratorDecision(
                    eligible=False,
                    blocked_reason="Active runs: 1 queued.",
                    active_queued=1,
                ),
            ),
            mock.MagicMock() as mock_sleep,
            mock.patch("apps.census.orchestration.close_old_connections") as mock_close,
        ):
            run_loop(
                sleep_seconds=10,
                sleep_fn=mock_sleep,
                should_stop=controlled_stop,
            )

        # close_old_connections called at start of each iteration
        assert mock_close.call_count >= 2


class TestManagementCommandLoopMode:
    """Management command supports --loop with configurable params."""

    def test_command_loop_calls_run_loop_with_defaults(self):
        """run_adaptive_census_cycles --loop calls run_loop with defaults."""
        import apps.census.management.commands.run_adaptive_census_cycles as cmd_module

        with mock.patch.object(cmd_module, "run_loop") as mock_run_loop:
            out = io.StringIO()
            err = io.StringIO()
            call_command(
                "run_adaptive_census_cycles",
                "--loop",
                stdout=out,
                stderr=err,
            )

        mock_run_loop.assert_called_once()
        args, kwargs = mock_run_loop.call_args
        assert kwargs.get("sleep_seconds") == 60
        assert kwargs.get("min_interval_minutes") == 30
        assert kwargs.get("failure_backoff_minutes") == 30
        assert kwargs.get("stale_running_minutes") == 180

    def test_command_loop_with_custom_params(self):
        """Custom params are passed to run_loop."""
        import apps.census.management.commands.run_adaptive_census_cycles as cmd_module

        with mock.patch.object(cmd_module, "run_loop") as mock_run_loop:
            out = io.StringIO()
            call_command(
                "run_adaptive_census_cycles",
                "--loop",
                "--sleep-seconds", "120",
                "--min-interval-minutes", "60",
                "--failure-backoff-minutes", "15",
                "--stale-running-minutes", "240",
                stdout=out,
            )

        mock_run_loop.assert_called_once()
        args, kwargs = mock_run_loop.call_args
        assert kwargs["sleep_seconds"] == 120
        assert kwargs["min_interval_minutes"] == 60
        assert kwargs["failure_backoff_minutes"] == 15
        assert kwargs["stale_running_minutes"] == 240

    def test_command_loop_calls_run_loop_not_run_single_cycle(self):
        """--loop dispatches to run_loop, not _handle_once."""
        import apps.census.management.commands.run_adaptive_census_cycles as cmd_module

        with (
            mock.patch.object(cmd_module, "run_loop") as mock_run_loop,
            mock.patch.object(cmd_module.Command, "_handle_once") as mock_once,
        ):
            out = io.StringIO()
            call_command("run_adaptive_census_cycles", "--loop", stdout=out)

        mock_run_loop.assert_called_once()
        mock_once.assert_not_called()

    def test_loop_configurable_params_test_defaults(self):
        """Default values for loop params are documented."""
        import inspect

        from apps.census.orchestration import run_loop
        sig = inspect.signature(run_loop)
        assert sig.parameters["sleep_seconds"].default == 60
        assert sig.parameters["min_interval_minutes"].default == 30
        assert sig.parameters["failure_backoff_minutes"].default == 30
        assert sig.parameters["stale_running_minutes"].default == 180
