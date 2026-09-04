"""Hourly bounded stale-admission safety sweep (RPSA-S5).

Orchestration-only management command: evaluates open stale-admission
cases and conflict evidence through the shared bounded pass and enqueues
at most ``--limit`` deduplicated ``admissions_only`` confirmation runs.
Absence never closes admissions; output is aggregate-safe (counts only,
never patient identity). Guarded by a PostgreSQL advisory lock distinct
from the census orchestrator's, released on every exit path.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.census.stale_admissions import (
    MAX_ENQUEUES_PER_CYCLE,
    acquire_stale_admission_sweep_lock,
    evaluate_and_enqueue_stale_admission_cases,
    release_stale_admission_sweep_lock,
)


class Command(BaseCommand):
    help = (
        "Bounded, aggregate-safe stale-admission safety sweep: evaluates "
        "open reconciliation cases plus conflict evidence and enqueues at "
        "most --limit deduplicated admissions_only confirmation runs. "
        "Never writes clinical exit state."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=MAX_ENQUEUES_PER_CYCLE,
            help=(
                "Maximum admissions_only confirmation runs to enqueue in "
                "this sweep (default: 100)."
            ),
        )

    def handle(self, *args, **options) -> None:
        limit: int = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be a positive integer.")

        if not acquire_stale_admission_sweep_lock():
            self.stdout.write(
                "Stale-admission safety sweep lock already held; skipping."
            )
            return
        try:
            result = evaluate_and_enqueue_stale_admission_cases(
                max_enqueues=limit
            )
        finally:
            release_stale_admission_sweep_lock()

        enqueued = result["enqueued_cases"] + result["enqueued_conflict"]
        self.stdout.write(
            self.style.SUCCESS(
                "Stale-admission safety sweep completed: "
                f"open_cases={result['open_cases']} "
                f"enqueued={enqueued} "
                f"enqueued_cases={result['enqueued_cases']} "
                f"enqueued_conflict={result['enqueued_conflict']} "
                f"skipped_active_run={result['skipped_active_run']} "
                f"skipped_cooldown={result['skipped_cooldown']} "
                f"deferred_over_cap={result['deferred_over_cap']} "
                f"limit={limit}"
            )
        )
