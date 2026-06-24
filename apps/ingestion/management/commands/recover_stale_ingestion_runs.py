"""Management command for stale IngestionRun recovery."""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.stale_recovery import (
    DEFAULT_HEARTBEAT_GRACE,
    DEFAULT_INTENT_LIMITS,
    DEFAULT_MAX_RUNS_PER_SWEEP,
    DEFAULT_STALE_LIMIT,
    recover_stale_ingestion_runs,
)


class Command(BaseCommand):
    """Inspect or apply terminal recovery for abandoned running runs."""

    help = "Inspect or fail abandoned running ingestion runs using heartbeat."
    stealth_options = ("now",)

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            help="Report stale candidates without mutating any run (default).",
        )
        mode.add_argument(
            "--apply",
            action="store_true",
            help="Mark stale candidates as terminal failed without requeue.",
        )
        parser.add_argument(
            "--max-runs-per-sweep",
            type=int,
            default=DEFAULT_MAX_RUNS_PER_SWEEP,
            help="Abort apply mode if more candidates than this are found.",
        )
        parser.add_argument(
            "--heartbeat-grace-minutes",
            type=int,
            default=int(DEFAULT_HEARTBEAT_GRACE.total_seconds() // 60),
            help="Heartbeat age, in minutes, after which a heartbeat is stale.",
        )
        parser.add_argument(
            "--admissions-only-limit-minutes",
            type=int,
            default=int(DEFAULT_INTENT_LIMITS["admissions_only"].total_seconds() // 60),
            help="Stale age limit for admissions_only runs.",
        )
        parser.add_argument(
            "--demographics-only-limit-minutes",
            type=int,
            default=int(DEFAULT_INTENT_LIMITS["demographics_only"].total_seconds() // 60),
            help="Stale age limit for demographics_only runs.",
        )
        parser.add_argument(
            "--full-sync-limit-minutes",
            type=int,
            default=int(DEFAULT_INTENT_LIMITS["full_sync"].total_seconds() // 60),
            help="Stale age limit for full_sync runs.",
        )
        parser.add_argument(
            "--census-extraction-limit-minutes",
            type=int,
            default=int(DEFAULT_INTENT_LIMITS["census_extraction"].total_seconds() // 60),
            help="Stale age limit for census_extraction runs.",
        )
        parser.add_argument(
            "--default-limit-minutes",
            type=int,
            default=int(DEFAULT_STALE_LIMIT.total_seconds() // 60),
            help="Stale age limit for empty or unknown intents.",
        )

    def handle(self, *args, **options):
        if options["max_runs_per_sweep"] < 1:
            raise CommandError("--max-runs-per-sweep must be >= 1")

        apply = bool(options["apply"])
        intent_limits = {
            "admissions_only": timedelta(minutes=options["admissions_only_limit_minutes"]),
            "demographics_only": timedelta(minutes=options["demographics_only_limit_minutes"]),
            "full_sync": timedelta(minutes=options["full_sync_limit_minutes"]),
            "census_extraction": timedelta(minutes=options["census_extraction_limit_minutes"]),
        }
        result = recover_stale_ingestion_runs(
            apply=apply,
            now=options.get("now"),
            heartbeat_grace=timedelta(minutes=options["heartbeat_grace_minutes"]),
            intent_limits=intent_limits,
            default_limit=timedelta(minutes=options["default_limit_minutes"]),
            max_runs_per_sweep=options["max_runs_per_sweep"],
        )

        mode_label = "apply" if apply else "dry-run"
        self.stdout.write(
            f"stale recovery {mode_label}: candidates={len(result.candidates)} "
            f"max_runs_per_sweep={result.max_runs_per_sweep}"
        )
        for candidate in result.candidates:
            age_minutes = candidate.age_seconds // 60
            heartbeat = (
                candidate.worker_heartbeat_at.isoformat()
                if candidate.worker_heartbeat_at is not None
                else "none"
            )
            reference = candidate.reference_at.isoformat()
            self.stdout.write(
                f"candidate run_id={candidate.run_id} batch_id={candidate.batch_id} "
                f"intent={candidate.intent or 'unknown'} status={candidate.status} "
                f"worker_label={candidate.worker_label or 'unknown'} "
                f"reference_at={reference} heartbeat_at={heartbeat} "
                f"age_minutes={age_minutes}"
            )

        if result.aborted:
            self.stdout.write(
                self.style.WARNING(
                    "stale recovery aborted: circuit breaker prevented mutation "
                    f"reason={result.abort_reason}"
                )
            )
            return

        if apply:
            self.stdout.write(
                "stale recovery applied: "
                f"marked_failed={len(result.marked_failed_run_ids)} "
                f"skipped={len(result.skipped_run_ids)} "
                f"closed_batches={len(result.closed_batch_ids)}"
            )
        else:
            self.stdout.write("stale recovery dry-run complete: no mutations applied")
