"""Adaptive census orchestrator — operational state computation (Slice ACO-S1)
and single-cycle execution (Slice ACO-S2).

This module provides:

- ``compute_orchestrator_state``: pure read-only evaluation of whether a new
  census cycle can safely start (S1).
- ``acquire_orchestrator_lock`` / ``release_orchestrator_lock``: PostgreSQL
  advisory lock for orchestrator coordination (S2).
- ``run_single_cycle``: executes exactly one safe census cycle when the system
  is eligible (S2).

Design decisions (per design.md):
- Queue is eligible when no IngestionRun has status queued or running and no
  open CensusExecutionBatch exists.
- Cooldown is based on started_at of the latest successful census_extraction.
- Stale running runs are detected but never mutated.
- All output is credential-safe and patient-data-safe.
- Single-cycle uses PG advisory lock to prevent concurrent orchestrators.
"""

from __future__ import annotations

import logging
import time as time_module
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from django.core.management import call_command
from django.db import close_old_connections, connection
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.ingestion.stale_recovery import recover_stale_ingestion_runs

logger = logging.getLogger(__name__)

# Unique PostgreSQL advisory lock key for census orchestrator coordination.
ADVISORY_LOCK_KEY = 31082024


def acquire_orchestrator_lock() -> bool:
    """Try to acquire the orchestrator coordination lock.

    Uses PostgreSQL ``pg_try_advisory_lock`` for non-blocking acquisition.

    Returns:
        True if the lock was acquired, False if it is already held.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY]
        )
        (acquired,) = cursor.fetchone()
    return bool(acquired)


def release_orchestrator_lock() -> bool:
    """Release the orchestrator coordination lock.

    Returns:
        True if the lock was released, False if it was not held.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY]
        )
        (released,) = cursor.fetchone()
    return bool(released)


# ---------------------------------------------------------------------------
# S1 — Operational state
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorDecision:
    """Read-only evaluation of whether a census cycle can start.

    Fields:
        eligible: True if a cycle would start right now.
        blocked_reason: Human-readable explanation when not eligible.
        active_queued: Count of IngestionRun with status='queued'.
        active_running: Count of IngestionRun with status='running'.
        open_batch_exists: Whether an unfinished CensusExecutionBatch exists.
        cooldown_remaining_minutes: Minutes remaining until cooldown ends, or None.
        stale_running_count: Count of running runs older than stale threshold.
    """

    eligible: bool = True
    blocked_reason: str = ""
    active_queued: int = 0
    active_running: int = 0
    open_batch_exists: bool = False
    cooldown_remaining_minutes: float | None = None
    stale_running_count: int = 0


def compute_orchestrator_state(
    min_interval_minutes: int = 30,
    stale_running_minutes: int = 180,
) -> OrchestratorDecision:
    """Evaluate whether the system is eligible for a new census cycle.

    This function is pure read-only: it queries the database but never
    creates, updates, or deletes records.

    Args:
        min_interval_minutes: Minimum minutes between successful census
            extraction runs.
        stale_running_minutes: Age in minutes after which a running run
            is considered stale.

    Returns:
        An OrchestratorDecision with the evaluation result.
    """
    now = timezone.now()
    reasons: list[str] = []
    decision = OrchestratorDecision()

    # 1. Check for active IngestionRun records (queued or running)
    active_queued = IngestionRun.objects.filter(status="queued").count()
    active_running = IngestionRun.objects.filter(status="running").count()

    decision.active_queued = active_queued
    decision.active_running = active_running

    if active_queued > 0 or active_running > 0:
        parts = []
        if active_queued > 0:
            parts.append(f"{active_queued} queued")
        if active_running > 0:
            parts.append(f"{active_running} running")
        reasons.append(f"Active runs: {', '.join(parts)}.")

    # 2. Check for open CensusExecutionBatch
    open_batch_exists = CensusExecutionBatch.objects.filter(
        finished_at__isnull=True
    ).exists()
    decision.open_batch_exists = open_batch_exists
    if open_batch_exists:
        reasons.append("Open batch exists.")

    # 3. Check cooldown based on latest successful census_extraction
    latest_census = (
        IngestionRun.objects.filter(
            status="succeeded",
            intent="census_extraction",
        )
        .order_by("-started_at")
        .first()
    )

    if latest_census is not None:
        elapsed = now - latest_census.started_at
        cooldown = timedelta(minutes=min_interval_minutes)
        if elapsed < cooldown:
            remaining = cooldown - elapsed
            remaining_minutes = remaining.total_seconds() / 60.0
            decision.cooldown_remaining_minutes = remaining_minutes
            reasons.append(
                f"Cooldown ({remaining_minutes:.0f} min remaining)."
            )

    # 4. Check for stale running runs (without mutation)
    stale_threshold = now - timedelta(minutes=stale_running_minutes)
    stale_runs = (
        IngestionRun.objects
        .filter(status="running")
        .annotate(
            effective_started_at=Coalesce("processing_started_at", "queued_at")
        )
        .filter(effective_started_at__lt=stale_threshold)
    )
    stale_count = stale_runs.count()
    decision.stale_running_count = stale_count

    if stale_count > 0:
        reasons.append(
            f"{stale_count} stale running run(s) detected (>{stale_running_minutes} min)."
        )

    # 5. Build final decision
    if reasons:
        decision.eligible = False
        decision.blocked_reason = " ".join(reasons)
    else:
        decision.eligible = True
        decision.blocked_reason = ""

    return decision


# ---------------------------------------------------------------------------
# S2 — Single-cycle execution
# ---------------------------------------------------------------------------


def _count_successful_census_runs() -> int:
    """Count succeeded census_extraction IngestionRun records."""
    return IngestionRun.objects.filter(
        status="succeeded",
        intent="census_extraction",
    ).count()


def _get_newest_succeeded_census_run() -> IngestionRun | None:
    """Return the most recent succeeded census_extraction run, or None."""
    return (
        IngestionRun.objects.filter(
            status="succeeded",
            intent="census_extraction",
        )
        .order_by("-started_at")
        .first()
    )


def run_single_cycle(
    min_interval_minutes: int = 30,
    stale_running_minutes: int = 180,
) -> dict[str, Any]:
    """Execute exactly one adaptive census cycle.

    Steps:
    1. Acquire PostgreSQL advisory lock.
    2. Evaluate eligibility via ``compute_orchestrator_state``.
    3. If blocked, release lock and return blocked outcome.
    4. Record the count of census_extraction runs before extraction.
    5. Run ``extract_census`` via management command.
    6. Count new census_extraction runs created during the cycle.
    7. If exactly one new succeeded run, call ``process_census_snapshot``
       with that ``run_id``.
    8. If zero or multiple new runs, fail safe without processing.
    9. Release the advisory lock.
    10. Return a structured result dict.

    Args:
        min_interval_minutes: Forwarded to ``compute_orchestrator_state``.
        stale_running_minutes: Forwarded to ``compute_orchestrator_state``.

    Returns:
        Dict with keys:
            cycle_executed: True if extraction was attempted.
            outcome: One of ``blocked``, ``lock_held``, ``success``,
                ``extraction_failed``, ``ambiguous_runs``.
            extraction_run_id: PK of the new extraction run, or None.
            batch_id: PK of the created CensusExecutionBatch, or None.
            message: Human-readable summary.
            error: Error detail when outcome is failure.
            blocked_reason: Reason when outcome is ``blocked``.
    """
    result: dict[str, Any] = {
        "cycle_executed": False,
        "outcome": "",
        "extraction_run_id": None,
        "batch_id": None,
        "message": "",
        "error": "",
        "blocked_reason": "",
    }

    # Step 1: Acquire the advisory lock
    if not acquire_orchestrator_lock():
        result["outcome"] = "lock_held"
        result["message"] = (
            "Another orchestrator instance holds the coordination lock. "
            "Cycle skipped."
        )
        logger.info("Orchestrator lock held by another instance. Skipping.")
        return result

    try:
        # Step 2: Evaluate eligibility
        decision = compute_orchestrator_state(
            min_interval_minutes=min_interval_minutes,
            stale_running_minutes=stale_running_minutes,
        )

        # Step 3: If blocked, return early
        if not decision.eligible:
            result["outcome"] = "blocked"
            result["blocked_reason"] = decision.blocked_reason
            result["message"] = f"System blocked: {decision.blocked_reason}"
            logger.info("Census cycle blocked: %s", decision.blocked_reason)
            return result

        # Step 4: Record census_extraction run count before extraction
        runs_before = _count_successful_census_runs()

        # Step 5: Run extract_census
        # NOTE: the real extract_census command signals failure via sys.exit(1),
        # which raises SystemExit (a BaseException, not an Exception subclass).
        # We must capture it too, otherwise it escapes run_single_cycle and
        # crashes the orchestrator process without reporting the outcome.
        logger.info("Starting census extraction cycle...")
        try:
            call_command("extract_census")
        except (Exception, SystemExit) as exc:
            result["cycle_executed"] = True
            result["outcome"] = "extraction_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["message"] = "Census extraction failed."
            logger.error("Census extraction failed: %s", exc)
            return result

        # Step 6: Identify new census_extraction runs
        runs_after = _count_successful_census_runs()
        new_runs_count = runs_after - runs_before

        result["cycle_executed"] = True

        if new_runs_count == 0:
            result["outcome"] = "ambiguous_runs"
            result["message"] = (
                "No new succeeded census_extraction run found after extraction. "
                "Snapshot processing skipped."
            )
            logger.warning("Zero new census extraction runs detected.")
            return result

        if new_runs_count > 1:
            result["outcome"] = "ambiguous_runs"
            result["message"] = (
                f"{new_runs_count} new census_extraction runs detected "
                f"(expected exactly 1). Snapshot processing skipped."
            )
            logger.warning(
                "Multiple new census extraction runs detected: %d", new_runs_count
            )
            return result

        # Exactly one new run — find it
        new_run = _get_newest_succeeded_census_run()
        if new_run is None:
            # Should not happen if new_runs_count == 1, but be defensive
            result["outcome"] = "ambiguous_runs"
            result["message"] = (
                "Could not locate the newly created census extraction run."
            )
            logger.warning("New run count is 1 but lookup returned None.")
            return result

        result["extraction_run_id"] = new_run.pk

        # Step 7: Call process_census_snapshot with the detected run_id
        logger.info(
            "Calling process_census_snapshot with run_id=%s", new_run.pk
        )
        try:
            call_command(
                "process_census_snapshot", run_id=new_run.pk
            )
        except Exception as exc:
            result["outcome"] = "processing_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["message"] = (
                "Census extraction succeeded but snapshot processing failed."
            )
            logger.error("Snapshot processing failed: %s", exc)
            return result

        # Step 8: Success
        result["outcome"] = "success"
        result["message"] = (
            f"Census cycle completed successfully. "
            f"Extraction run: {new_run.pk}."
        )
        logger.info("Census cycle completed. Extraction run: %s", new_run.pk)

        return result

    finally:
        # Step 9: Always release the lock
        release_orchestrator_lock()


# ---------------------------------------------------------------------------
# S3 — Continuous loop behavior
# ---------------------------------------------------------------------------


def run_loop(
    *,
    sleep_seconds: int = 60,
    min_interval_minutes: int = 30,
    failure_backoff_minutes: int = 30,
    stale_running_minutes: int = 180,
    enable_stale_recovery: bool = True,
    sleep_fn: Callable[[int | float], None] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Run the adaptive census orchestrator in continuous loop mode.

    The loop:
    1. Closes stale DB connections.
    2. Evaluates eligibility via ``compute_orchestrator_state``.
    3. While blocked (active queue, open batch, cooldown, stale running):
       logs the blocking reason and sleeps for ``sleep_seconds``.
    4. When eligible, runs a single cycle via ``run_single_cycle``.
    5. If the cycle fails (extraction_failed, ambiguous_runs,
       processing_failed, or unexpected outcome), sleeps for
       ``failure_backoff_minutes`` before retrying.
    6. Checks ``should_stop`` at the top of each iteration to support
       graceful shutdown via SIGTERM/SIGINT.

    Args:
        sleep_seconds: Seconds to sleep when blocked (default 60).
        min_interval_minutes: Forwarded to ``compute_orchestrator_state``.
        failure_backoff_minutes: Minutes to sleep after a failed cycle
            before retrying (default 30).
        stale_running_minutes: Forwarded to ``compute_orchestrator_state``.
        sleep_fn: Callable for sleeping (default ``time.sleep``);
            injected in tests to avoid real waiting.
        should_stop: Callable returning True when the loop should exit;
            set by signal handlers in production (default ``lambda: False``).
    """
    failure_outcomes: set[str] = {
        "extraction_failed",
        "processing_failed",
        "ambiguous_runs",
    }

    logger.info(
        "Orchestrator loop started "
        "(sleep=%ds, min_interval=%dmin, backoff=%dmin, stale=%dmin, "
        "recovery=%s).",
        sleep_seconds,
        min_interval_minutes,
        failure_backoff_minutes,
        stale_running_minutes,
        "enabled" if enable_stale_recovery else "disabled",
    )

    _sleep: Callable[[int | float], None] = sleep_fn or time_module.sleep

    while not should_stop():
        # 1. Keep database connections healthy
        close_old_connections()

        # SIRS-S3: Run stale recovery before eligibility check
        if enable_stale_recovery:
            recovery_result = recover_stale_ingestion_runs(apply=True)
            if recovery_result.aborted:
                logger.warning(
                    "Stale recovery circuit breaker blocked: %s "
                    "(sleep %ds).",
                    recovery_result.abort_reason,
                    sleep_seconds,
                )
                _sleep(sleep_seconds)
                continue
            if recovery_result.marked_failed_run_ids:
                logger.info(
                    "Stale recovery: marked %d run(s) failed, "
                    "closed %d batch(es).",
                    len(recovery_result.marked_failed_run_ids),
                    len(recovery_result.closed_batch_ids),
                )

        # 2. Evaluate eligibility
        decision = compute_orchestrator_state(
            min_interval_minutes=min_interval_minutes,
            stale_running_minutes=stale_running_minutes,
        )

        # 3. Blocked — log and sleep
        if not decision.eligible:
            logger.info(
                "Cycle blocked: %s (sleep %ds).",
                decision.blocked_reason,
                sleep_seconds,
            )
            _sleep(sleep_seconds)
            continue

        # 4. Eligible — run one cycle
        logger.info("System eligible, running single cycle.")
        result = run_single_cycle(
            min_interval_minutes=min_interval_minutes,
            stale_running_minutes=stale_running_minutes,
        )

        outcome = result.get("outcome", "")

        # 5. Handle cycle outcomes
        if outcome in failure_outcomes:
            error = result.get("error", "")
            message = result.get("message", "")
            logger.error(
                "Cycle failed (outcome=%s): %s %s",
                outcome,
                message,
                error,
            )
            backoff_seconds = failure_backoff_minutes * 60
            logger.info(
                "Backoff %dmin before retry.",
                failure_backoff_minutes,
            )
            _sleep(backoff_seconds)
        elif outcome == "lock_held":
            logger.info(
                "Lock held by another instance (sleep %ds).",
                sleep_seconds,
            )
            _sleep(sleep_seconds)
        elif outcome == "blocked":
            # Race condition: state changed between check and cycle
            logger.info(
                "System became blocked during cycle: %s (sleep %ds).",
                result.get("blocked_reason", ""),
                sleep_seconds,
            )
            _sleep(sleep_seconds)
        elif outcome == "success":
            run_id = result.get("extraction_run_id")
            logger.info(
                "Cycle succeeded, extraction run %s. Next check after cooldown.",
                run_id,
            )
            # No sleep — next iteration will check cooldown and wait if needed
        else:
            logger.warning(
                "Unexpected cycle outcome '%s': %s",
                outcome,
                result.get("message", ""),
            )
            backoff_seconds = failure_backoff_minutes * 60
            _sleep(backoff_seconds)

    logger.info("Orchestrator loop stopped.")
