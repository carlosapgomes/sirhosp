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
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.census.stale_admissions import observe_accepted_census_run
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.ingestion.stale_recovery import recover_stale_ingestion_runs
from apps.statistics_reports.models import (
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
)

logger = logging.getLogger(__name__)

# Unique PostgreSQL advisory lock key for census orchestrator coordination.
ADVISORY_LOCK_KEY = 31082024

# America/Bahia literal — never an inherited default timezone (ADR-0010).
BAHIA_TZ = ZoneInfo("America/Bahia")

# Quiet-window in-process D-1 exit recovery (ADR-0010): at most one
# previous-day recovery attempt per local Bahia date inside
# [D1_QUIET_START_HOUR, D1_QUIET_END_HOUR).
D1_QUIET_START_HOUR = 1
D1_QUIET_END_HOUR = 5

# Daily statistics finalization (OASF-S2). The canonical aggregate markers
# below are the only success evidence the read-only activation preflight parses
# from this container's logs; each is emitted only after the matching
# ``call_command`` returned successfully.
D1_RECOVERY_SUCCESS_MARKER = (
    "mode=d1-recovery result=success source=adaptive-orchestrator"
)
HOURLY_DISCHARGES_SUCCESS_MARKER = (
    "mode=hourly-discharges result=success source=adaptive-orchestrator"
)

# Operational quality codes the adaptive loop may attach to a degraded
# revision. They belong to the closed allowlist enforced by the materializer.
D1_RECOVERY_INCOMPLETE_WARNING = "d1_recovery_incomplete"
D1_RECOVERY_NOT_CONFIRMED_WARNING = "d1_recovery_not_confirmed"


@dataclass
class _PendingStatisticsFinalization:
    """One America/Bahia local date awaiting the first drain-safe iteration.

    The pending state lives only in this process: a restart is recovered
    through the durable absence of a ready ``DailyStatisticsReport`` rather
    than through additional persistence.
    """

    local_date: date
    quality_warning: str | None = None


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

        # Step 7.5 (RPSA-S5): best-effort stale-admission observation for
        # the accepted run. Observation failure is logged structurally and
        # never fails the census cycle; the orchestrator lock is released
        # by the surrounding finally on every exit path.
        try:
            observation = observe_accepted_census_run(run_id=new_run.pk)
        except Exception as exc:
            logger.error(
                "Stale-admission observation failed for census run %s: %s",
                new_run.pk,
                type(exc).__name__,
            )
            result["absence_observation"] = {
                "observed": False,
                "error_type": type(exc).__name__,
            }
        else:
            # Aggregate case counters only; never patient identity.
            result["absence_observation"] = observation

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
# S4 — Adaptive statistics finalization
# ---------------------------------------------------------------------------


def _drain_is_safe(decision: OrchestratorDecision) -> bool:
    """True when no ingestion run is queued/running and no batch is open.

    Drainage is deliberately independent from the census cooldown: a pending
    statistics date may be published while cooldown still prevents a new
    census cycle (design D1).
    """
    return (
        decision.active_queued == 0
        and decision.active_running == 0
        and not decision.open_batch_exists
    )


def _statistics_date_is_eligible(local_date: date) -> bool:
    """True when the date is at or after the declared activation boundary."""
    activation_date = settings.STATISTICS_ACTIVATION_DATE
    if activation_date is None:
        return False
    return local_date >= activation_date


def _daily_statistics_report_ready(local_date: date) -> bool:
    """True when the date already has a ready statistics revision."""
    return DailyStatisticsReport.objects.filter(
        local_date=local_date,
        status=DailyStatisticsReportStatus.READY,
    ).exists()


def _materialize_daily_statistics(
    pending: _PendingStatisticsFinalization,
) -> bool:
    """Materialize one pending date; return True only on command success.

    The failure branch records the target date and the technical exception
    class only, so no nominal command output or clinical value is logged.
    """
    args = [
        "materialize_daily_statistics",
        "--date",
        pending.local_date.isoformat(),
    ]
    if pending.quality_warning is not None:
        args += ["--quality-warning", pending.quality_warning]
    started = time_module.monotonic()
    try:
        call_command(*args)
    except (Exception, SystemExit) as exc:
        logger.error(
            "Daily statistics finalization failed: local date %s, %s.",
            pending.local_date.isoformat(),
            type(exc).__name__,
        )
        return False
    logger.info(
        "Daily statistics finalization finished: local date %s, "
        "duration %.0f seconds.",
        pending.local_date.isoformat(),
        time_module.monotonic() - started,
    )
    return True


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
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    """Run the adaptive census orchestrator in continuous loop mode.

    The loop:
    1. Closes stale DB connections.
    2. Evaluates eligibility via ``compute_orchestrator_state``.
    3. When eligible inside the quiet window [01:00, 05:00) America/Bahia
       with no D-1 attempt yet for the current local date, runs the
       previous-day exit recovery in-process via ``call_command``
       (ADR-0010); a failure is logged and never blocks the cycle.
    4. Captures the previous America/Bahia local date as a pending daily
       statistics finalization (OASF-S2) when it is at or after the declared
       activation boundary. After 05:00, a process that lost its pending
       state to a restart recovers it once through the durable absence of a
       ready revision.
    5. On the first iteration whose queue is drained and without an open
       batch, materializes the pending date in-process via ``call_command``
       (``materialize_daily_statistics --date``), before the intraday
       recovery and the next census cycle. A failure is aggregated and never
       blocks the loop.
    6. When eligible in a new America/Bahia local hour (no hourly attempt
       yet in this process for that hour), runs the intraday discharge
       recovery in-process via ``call_command`` (``--mode hourly``); a
       failure is logged and never blocks the cycle.
    7. When eligible, runs a single cycle via ``run_single_cycle``.
    8. If the cycle fails (extraction_failed, ambiguous_runs,
       processing_failed, or unexpected outcome), sleeps for
       ``failure_backoff_minutes`` before retrying.
    9. Checks ``should_stop`` at the top of each iteration to support
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
        now_fn: Callable returning an aware ``datetime`` used to evaluate
            the quiet window, the local Bahia date/hour for the
            in-process D-1 and intraday hourly steps (default
            ``timezone.now``); injected in tests to freeze the clock.
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

    # Quiet-window D-1 exit-recovery state (ADR-0010): an in-memory flag
    # records the last local Bahia date for which an attempt was made so
    # there is at most one attempt per date in this process run.
    _now_fn: Callable[[], datetime] = now_fn or timezone.now
    last_d1_run_date: date | None = None

    # Intraday hourly exit-recovery state: an in-memory flag records the
    # last local Bahia hour for which an attempt was made so there is at
    # most one hourly attempt per hour in this process run.
    last_hourly_run_hour: int | None = None

    # Statistics finalization state (OASF-S2): the pending previous local
    # date captured after the D-1 attempt (or reconstructed once after a
    # post-05:00 restart) and the dates already attempted in this process.
    pending_statistics: _PendingStatisticsFinalization | None = None
    attempted_statistics_dates: set[date] = set()

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

        # 3. Drain-safe state is evaluated from the same decision aggregates
        # (queue drained and no open batch). Cooldown may block a new census
        # without blocking the statistics publication.
        drained = _drain_is_safe(decision)

        # 4. Quiet-window D-1 exit recovery (ADR-0010). Being eligible
        # means the queue is drained and no census batch is open — exactly
        # the preconditions the D-1 runtime requires. Run it in-process
        # once per local Bahia date inside the quiet window, before the
        # next census cycle opens a new batch. A failure is logged and
        # never blocks the census cycle.
        local_now = _now_fn().astimezone(BAHIA_TZ)
        local_date = local_now.date()
        if (
            decision.eligible
            and D1_QUIET_START_HOUR <= local_now.hour < D1_QUIET_END_HOUR
            and local_date != last_d1_run_date
        ):
            last_d1_run_date = local_date
            logger.info(
                "Quiet-window D-1 recovery start: local date %s "
                "(America/Bahia), queue drained and batch closed.",
                local_date,
            )
            _d1_started = time_module.monotonic()
            d1_succeeded = False
            try:
                call_command(
                    "run_exit_reconciliation_runtime", "--mode", "d1"
                )
            except (Exception, SystemExit) as exc:
                # Design D4 (ADR-0010): even an unexpected exit-75
                # contention race must never abort the orchestrator loop;
                # log the aggregate-safe exception type and continue.
                logger.error(
                    "quiet-window D-1 recovery failed: %s",
                    type(exc).__name__,
                )
            else:
                d1_succeeded = True
                # Canonical aggregate evidence for the read-only preflight
                # (OASF-S2): emitted only after a successful return.
                logger.info(D1_RECOVERY_SUCCESS_MARKER)
            _d1_elapsed = time_module.monotonic() - _d1_started
            logger.info(
                "Quiet-window D-1 recovery finished: local date %s, "
                "duration %.0f seconds.",
                local_date,
                _d1_elapsed,
            )

            # 4.0 Capture the statistics date (OASF-S2, design D1). Only a
            # configured boundary at or before D-1 creates the pending
            # finalization; a failed D-1 attempt still finalizes but records
            # the allowlisted degradation warning.
            statistics_target = local_date - timedelta(days=1)
            if _statistics_date_is_eligible(statistics_target):
                pending_statistics = _PendingStatisticsFinalization(
                    local_date=statistics_target,
                    quality_warning=(
                        None
                        if d1_succeeded
                        else D1_RECOVERY_INCOMPLETE_WARNING
                    ),
                )

            # 4.0.1 Re-evaluate after the D-1 attempt: if it occupied the
            # queue or left a batch open, hourly and the next census cycle
            # must wait for a later drained iteration.
            decision = compute_orchestrator_state(
                min_interval_minutes=min_interval_minutes,
                stale_running_minutes=stale_running_minutes,
            )
            drained = _drain_is_safe(decision)

        # 4.0.2 Post-05:00 restart recovery (OASF-S2, design D1). A process
        # that lost its in-memory pending to a restart uses the durable
        # absence of a ready revision as the marker of a missed D-1
        # finalization. Only the previous local date is inspected; the
        # attempted set prevents any repeat and D-1 is never re-run outside
        # its window.
        if (
            pending_statistics is None
            and local_now.hour >= D1_QUIET_END_HOUR
        ):
            statistics_target = local_date - timedelta(days=1)
            if (
                statistics_target not in attempted_statistics_dates
                and _statistics_date_is_eligible(statistics_target)
                and not _daily_statistics_report_ready(statistics_target)
            ):
                pending_statistics = _PendingStatisticsFinalization(
                    local_date=statistics_target,
                    quality_warning=D1_RECOVERY_NOT_CONFIRMED_WARNING,
                )

        # 4.1 Finalize the pending statistics date on the first drain-safe
        # iteration, before the intraday recovery and the next census cycle.
        # The logical attempt is consumed before the call, so a failure is
        # never retried in this process; a restart is safe through the
        # materializer idempotency.
        if (
            pending_statistics is not None
            and drained
            and pending_statistics.local_date not in attempted_statistics_dates
        ):
            attempted_statistics_dates.add(pending_statistics.local_date)
            _materialize_daily_statistics(pending_statistics)
            pending_statistics = None

        # 4.2 A blocked loop observes and waits. A pending statistics date
        # was already published above when the queue was drained, so a
        # census cooldown never suppresses a confirmed publication.
        if not decision.eligible:
            logger.info(
                "Cycle blocked: %s (sleep %ds).",
                decision.blocked_reason,
                sleep_seconds,
            )
            _sleep(sleep_seconds)
            continue

        # 4.3 Intraday hourly exit recovery. Being eligible means the
        # queue is drained and no census batch is open — exactly the
        # preconditions the hourly runtime requires. Run it in-process
        # once per local Bahia hour, after the D-1 step (when both fire,
        # D-1 covers the previous day and hourly the current day) and
        # before the next census cycle opens a new batch. A failure is
        # logged and never blocks the census cycle. The flag is advanced
        # BEFORE the attempt so a failure still consumes the hour.
        if local_now.hour != last_hourly_run_hour:
            last_hourly_run_hour = local_now.hour
            logger.info(
                "Intraday hourly recovery start: local time %s "
                "(America/Bahia), queue drained and batch closed.",
                local_now.strftime("%Y-%m-%d %H:%M:%S"),
            )
            _hourly_started = time_module.monotonic()
            try:
                call_command(
                    "run_exit_reconciliation_runtime", "--mode", "hourly"
                )
            except (Exception, SystemExit) as exc:
                # Same isolation as the D-1 step (ADR-0010): an unexpected
                # SystemExit contention race must never abort the
                # orchestrator loop; log the aggregate-safe exception type
                # and continue.
                logger.error(
                    "intraday hourly recovery failed: %s",
                    type(exc).__name__,
                )
            else:
                # Canonical aggregate evidence for the read-only preflight
                # (OASF-S2): only a successful return emits the marker.
                logger.info(HOURLY_DISCHARGES_SUCCESS_MARKER)
            _hourly_elapsed = time_module.monotonic() - _hourly_started
            logger.info(
                "Intraday hourly recovery finished: local time %s, "
                "duration %.0f seconds.",
                local_now.strftime("%Y-%m-%d %H:%M:%S"),
                _hourly_elapsed,
            )

        # 5. Eligible — run one cycle
        logger.info("System eligible, running single cycle.")
        result = run_single_cycle(
            min_interval_minutes=min_interval_minutes,
            stale_running_minutes=stale_running_minutes,
        )

        outcome = result.get("outcome", "")

        # 6. Handle cycle outcomes
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
