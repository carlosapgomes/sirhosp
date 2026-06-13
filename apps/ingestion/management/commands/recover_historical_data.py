"""Management command for historical data recovery.

A thin wrapper around the orchestrator in
``apps.ingestion.historical_recovery``. Parses CLI arguments, builds a
``RecoveryPlan``, delegates execution to
``execute_recovery_plan``, prints deterministic operator output,
and exits with a non-zero code when step failures occur.

Usage::

    python manage.py recover_historical_data --date DD/MM/AAAA
    python manage.py recover_historical_data --start-date DD/MM/AAAA --end-date DD/MM/AAAA
    python manage.py recover_historical_data --date DD/MM/AAAA
        --extractor admissions --extractor deaths
    python manage.py recover_historical_data --date DD/MM/AAAA --dry-run
    python manage.py recover_historical_data --date DD/MM/AAAA --fail-fast
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryPlan,
    _date_to_str,
    _parse_date,
    build_date_range,
    execute_recovery_plan,
    validate_extractors,
)

# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Recover historical operational data for a date or inclusive date range."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Single date for recovery in DD/MM/AAAA format.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            dest="start_date",
            help="Inclusive start date for date range in DD/MM/AAAA format.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            dest="end_date",
            help="Inclusive end date for date range in DD/MM/AAAA format.",
        )
        parser.add_argument(
            "--extractor",
            type=str,
            action="append",
            default=None,
            dest="extractors",
            help=(
                "Extractor to run (repeatable). "
                f"Valid values: {', '.join(DEFAULT_EXTRACTOR_ORDER)}. "
                "Default: all extractors."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            dest="dry_run",
            help="Print planned steps without executing extractors.",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            default=False,
            dest="fail_fast",
            help="Stop after the first failed extraction.",
        )

    def handle(self, *args, **options):
        # -- Resolve date arguments -------------------------------------------
        date_arg = options.get("date")
        start_date_arg = options.get("start_date")
        end_date_arg = options.get("end_date")

        if date_arg and (start_date_arg or end_date_arg):
            raise CommandError(
                "--date cannot be combined with --start-date or --end-date."
            )

        if not date_arg and not (start_date_arg and end_date_arg):
            raise CommandError(
                "Provide --date DD/MM/AAAA or both --start-date and --end-date."
            )

        if date_arg:
            try:
                parsed_date = _parse_date(date_arg)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            days = [parsed_date]
        else:
            if not start_date_arg:
                raise CommandError("--start-date is required when using date range.")
            if not end_date_arg:
                raise CommandError("--end-date is required when using date range.")
            try:
                parsed_start = _parse_date(start_date_arg)
                parsed_end = _parse_date(end_date_arg)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            try:
                days = build_date_range(parsed_start, parsed_end)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        # -- Resolve extractors -----------------------------------------------
        raw_extractors = options.get("extractors")
        try:
            extractors = validate_extractors(raw_extractors)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        # -- Build plan -------------------------------------------------------
        dry_run = bool(options.get("dry_run", False))
        fail_fast = bool(options.get("fail_fast", False))

        plan = RecoveryPlan(
            dates=days,
            extractors=extractors,
            dry_run=dry_run,
            fail_fast=fail_fast,
        )

        # -- Print header -----------------------------------------------------
        self._print_header(plan)

        # -- Execute plan -----------------------------------------------------
        result = execute_recovery_plan(plan)

        # -- Print steps ------------------------------------------------------
        for step in result.steps:
            if step.skipped:
                status = "SKIPPED (dry-run)"
            elif step.success:
                status = "OK"
            else:
                status = f"FAILED ({step.failure_reason})"
            self.stdout.write(
                f"  {step.date_label} - {step.extractor:<20s} {status}"
            )

        # -- Print summary ----------------------------------------------------
        self.stdout.write("")
        self.stdout.write(result.summary)

        # -- Final exit status ------------------------------------------------
        if not result.success:
            self.stdout.write("Recovery completed with failures.")
            sys.exit(1)

    def _print_header(self, plan: RecoveryPlan) -> None:
        """Print the planning header to stdout."""
        start_label = _date_to_str(plan.dates[0]) if plan.dates else "?"
        end_label = _date_to_str(plan.dates[-1]) if plan.dates else "?"
        label = plan.date_count_label

        mode = " [DRY RUN]" if plan.dry_run else ""
        self.stdout.write(
            f"{mode}Recovering data for period: "
            f"{start_label} to {end_label} ({label})"
        )
        self.stdout.write(
            f"Extractors: {', '.join(plan.extractors)}"
        )
        self.stdout.write("")
