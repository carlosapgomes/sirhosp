"""Management command for discharge extraction (thin CLI wrapper).

This command delegates extraction orchestration to the
``run_discharge_extraction`` service. The service returns a structured
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

from apps.discharges.extraction_service import run_discharge_extraction


class Command(BaseCommand):
    help = (
        "Extract discharge XLS from source system and upsert DischargeRecord. "
        "Use --date DD/MM/AAAA for historical dates."
    )

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

        # Resolve default date (today)
        today = timezone.localdate()
        if raw_date:
            date_value = raw_date
        else:
            date_value = today.strftime("%d/%m/%Y")

        self.stdout.write(f"Extracting discharges for {date_value}...")

        # Delegate to the service
        result = run_discharge_extraction(
            date=date_value,
            headless=headless,
        )

        if result.success:
            count = result.metrics.get("total_records", 0)
            if count > 0:
                created = result.metrics.get("created", 0)
                updated = result.metrics.get("updated", 0)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Discharge extraction complete. "
                        f"{count} records persisted "
                        f"({created} created, {updated} updated)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("No discharges found for the date.")
                )
        else:
            self.stderr.write(
                f"Discharge extraction failed: {result.error_message}"
            )
            sys.exit(1)
