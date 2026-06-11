"""Management command for official census extraction (thin CLI wrapper).

This command delegates the actual extraction orchestration to the
``run_official_census_extraction`` service. The service returns a structured
``ExtractionResult`` which the command translates to user-facing output
and exit codes.

CLI arguments are preserved exactly:
  --date DD/MM/AAAA         Target date (default: today)
  --headless / --no-headless  Run Playwright in headless mode (default: headless)
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.census.services import run_official_census_extraction


class Command(BaseCommand):
    help = "Extract official daily census (ZIP) from source system."

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

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        raw_date: str | None = options.get("date")

        # Resolve date (same logic as before)
        today = timezone.localdate()
        date_value = today.strftime("%d/%m/%Y")
        if raw_date:
            date_value = raw_date

        self.stdout.write(f"Extracting official census for {date_value}...")

        # Delegate to the service
        result = run_official_census_extraction(
            date=date_value,
            headless=headless,
        )

        if result.success:
            count = result.metrics.get("total_records", 0)
            if count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Official census extraction complete. "
                        f"{count} records persisted."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        "No official census data found for the date."
                    )
                )
        else:
            self.stderr.write(
                f"Official census extraction failed: {result.error_message}"
            )
            sys.exit(1)
