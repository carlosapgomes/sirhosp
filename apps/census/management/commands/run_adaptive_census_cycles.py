"""Adaptive census cycle orchestrator.

Modes:
    --dry-run   Evaluate and report eligibility without mutating data (S1).
    --once      Execute exactly one safe census cycle (S2, default).
    --loop      Run continuously with cooldown, backoff and signals (S3).

Usage:
    python manage.py run_adaptive_census_cycles
    python manage.py run_adaptive_census_cycles --dry-run
    python manage.py run_adaptive_census_cycles --once
    python manage.py run_adaptive_census_cycles --loop
    python manage.py run_adaptive_census_cycles --loop \\
        --sleep-seconds 60 --min-interval-minutes 30 \\
        --failure-backoff-minutes 30 --stale-running-minutes 180
"""

from __future__ import annotations

import logging
import signal

from django.core.management.base import BaseCommand

from apps.census.orchestration import (
    compute_orchestrator_state,
    run_loop,
    run_single_cycle,
)

# Module-level flag for graceful shutdown
_should_stop = False


def _signal_handler(signum, frame):
    """Set the stop flag and log shutdown intent."""
    global _should_stop
    if not _should_stop:
        logging.getLogger(__name__).info(
            "Received signal %d, shutting down gracefully...", signum
        )
    _should_stop = True


class Command(BaseCommand):
    help = "Orchestrate adaptive census cycles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Evaluate and report the decision without mutating data.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            default=False,
            help="Execute exactly one safe census cycle (default behavior).",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            default=False,
            help="Run continuously with cooldown, backoff and signals.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=60,
            help="Seconds to sleep when blocked (default: 60).",
        )
        parser.add_argument(
            "--min-interval-minutes",
            type=int,
            default=30,
            help="Minimum minutes between successful census extraction runs.",
        )
        parser.add_argument(
            "--failure-backoff-minutes",
            type=int,
            default=30,
            help="Minutes to sleep after a failed cycle before retry (default: 30).",
        )
        parser.add_argument(
            "--stale-running-minutes",
            type=int,
            default=180,
            help="Age in minutes after which a running run is considered stale.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]
        min_interval: int = options["min_interval_minutes"]
        failure_backoff: int = options["failure_backoff_minutes"]
        stale_running: int = options["stale_running_minutes"]

        if dry_run:
            self._handle_dry_run(min_interval, stale_running)
        elif loop:
            self._handle_loop(
                sleep_seconds=sleep_seconds,
                min_interval=min_interval,
                failure_backoff=failure_backoff,
                stale_running=stale_running,
            )
        else:
            # --once (default, also when neither --dry-run nor --loop)
            self._handle_once(min_interval, stale_running)

    def _handle_dry_run(
        self, min_interval: int, stale_running: int
    ) -> None:
        """Evaluate and report the decision without mutating data."""
        decision = compute_orchestrator_state(
            min_interval_minutes=min_interval,
            stale_running_minutes=stale_running,
        )

        if decision.eligible:
            self.stdout.write(
                self.style.SUCCESS(
                    "SYSTEM ELIGIBLE: a new census cycle would start."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"SYSTEM BLOCKED: {decision.blocked_reason}"
                )
            )

        parts = [
            f"  Active queued runs:     {decision.active_queued}",
            f"  Active running runs:    {decision.active_running}",
            f"  Open batch exists:      {decision.open_batch_exists}",
        ]

        if decision.cooldown_remaining_minutes is not None:
            parts.append(
                f"  Cooldown remaining:     "
                f"{decision.cooldown_remaining_minutes:.0f} min"
            )

        parts.append(
            f"  Stale running runs:     {decision.stale_running_count}"
        )

        self.stdout.write("\n".join(parts))

    def _handle_once(self, min_interval: int, stale_running: int) -> None:
        """Execute exactly one safe census cycle."""
        result = run_single_cycle(
            min_interval_minutes=min_interval,
            stale_running_minutes=stale_running,
        )

        outcome = result["outcome"]

        if outcome == "blocked":
            self.stdout.write(
                self.style.WARNING(
                    f"SYSTEM BLOCKED: {result.get('blocked_reason', '')}"
                )
            )
        elif outcome == "lock_held":
            self.stdout.write(
                self.style.WARNING(
                    f"LOCK HELD: {result.get('message', '')}"
                )
            )
        elif outcome == "success":
            run_id = result.get("extraction_run_id")
            batch_id = result.get("batch_id")
            msg = (
                f"CYCLE SUCCESS: extraction run {run_id} completed."
            )
            if batch_id:
                msg += f" Batch: {batch_id}."
            self.stdout.write(self.style.SUCCESS(msg))
        elif outcome == "extraction_failed":
            self.stdout.write(
                self.style.ERROR(
                    f"EXTRACTION FAILED: {result.get('error', '')}"
                )
            )
        elif outcome == "ambiguous_runs":
            self.stdout.write(
                self.style.WARNING(
                    f"AMBIGUOUS RUNS: {result.get('message', '')}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"UNEXPECTED OUTCOME: {result.get('message', outcome)}"
                )
            )

    def _handle_loop(
        self,
        sleep_seconds: int,
        min_interval: int,
        failure_backoff: int,
        stale_running: int,
    ) -> None:
        """Run the orchestrator in continuous loop mode.

        Registers SIGTERM/SIGINT handlers for graceful shutdown and
        delegates to ``run_loop``.
        """
        global _should_stop
        _should_stop = False

        # Register signal handlers
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                "Orchestrator loop started "
                f"(sleep={sleep_seconds}s, "
                f"min_interval={min_interval}min, "
                f"backoff={failure_backoff}min, "
                f"stale={stale_running}min). "
                "Send SIGTERM or SIGINT to stop."
            )
        )

        run_loop(
            sleep_seconds=sleep_seconds,
            min_interval_minutes=min_interval,
            failure_backoff_minutes=failure_backoff,
            stale_running_minutes=stale_running,
            should_stop=lambda: _should_stop,
        )

        self.stdout.write(
            self.style.SUCCESS("Orchestrator loop stopped.")
        )
