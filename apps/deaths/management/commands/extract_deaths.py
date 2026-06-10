"""Management command for death extraction (thin CLI wrapper).

This command delegates the actual extraction orchestration to the
``run_death_extraction`` service. The service returns a structured
``ExtractionResult`` which the command translates to user-facing output
and exit codes.

CLI arguments are preserved exactly:
  --date DD/MM/AAAA         Target date (default: today)
  --start-date DD/MM/AAAA   Start date for period
  --end-date DD/MM/AAAA     End date for period
  --headless / --no-headless  Run Playwright in headless mode (default: headless)
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.deaths.services import run_death_extraction


class Command(BaseCommand):
    help = "Extract deaths report from source system for a specific date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run Playwright in headless mode.",
        )
        parser.add_argument(
            "--no-headless",
            dest="headless",
            action="store_false",
            help="Run Playwright with visible browser.",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Target date in DD/MM/AAAA format (default: today).",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Start date for period in DD/MM/AAAA format.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="End date for period in DD/MM/AAAA format.",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        raw_date: str | None = options.get("date")
        raw_start: str | None = options.get("start_date")
        raw_end: str | None = options.get("end_date")

        # Resolve dates (same logic as before)
        today = timezone.localdate()
        date_value = today.strftime("%d/%m/%Y")
        start_date: str
        end_date: str

        if raw_start and raw_end:
            start_date = raw_start
            end_date = raw_end
        elif raw_date:
            start_date = raw_date
            end_date = raw_date
        else:
            start_date = date_value
            end_date = date_value

        self.stdout.write(f"Extracting deaths from {start_date} to {end_date}...")

        # Delegate to the service
        result = run_death_extraction(
            start_date=start_date,
            end_date=end_date,
            headless=headless,
        )

        if result.success:
            count = result.metrics.get("total_records", 0)
            if count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Death extraction complete. "
                        f"{count} records persisted."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("No deaths found for the period.")
                )
        else:
            self.stderr.write(
                f"Death extraction failed: {result.error_message}"
            )
            sys.exit(1)
