"""Process a single discharge PDF and set discharge_date on admissions.

Usage:
    # Date auto-detected from filename (altas-DD-MM-YYYY.pdf)
    uv run python manage.py process_discharge_pdf downloads/altas-01-05-2026.pdf

    # Explicit date override
    uv run python manage.py process_discharge_pdf downloads/altas.pdf \\
        --discharge-date 2026-05-01

Extracts patients from the PDF, matches them to Admissions by
prontuario + data_internacao, and sets discharge_date.
"""

from __future__ import annotations

import importlib
import re
import sys
from datetime import date, datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.discharges.services import process_discharges

_FILENAME_DATE_RE = re.compile(r"altas-(\d{2})-(\d{2})-(\d{4})\.pdf$")


class Command(BaseCommand):
    help = (
        "Process a single discharge PDF: extract patients and set "
        "discharge_date on matching Admissions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "pdf_path",
            type=str,
            help="Path to the discharge PDF file (e.g. downloads/altas-01-05-2026.pdf)",
        )
        parser.add_argument(
            "--discharge-date",
            type=str,
            default=None,
            help=(
                "Discharge date in YYYY-MM-DD format. "
                "If not provided, auto-detected from filename "
                "(altas-DD-MM-YYYY.pdf). Falls back to today."
            ),
        )

    def handle(self, *args, **options):
        pdf_path = Path(options["pdf_path"])
        if not pdf_path.is_file():
            self.stderr.write(f"PDF not found: {pdf_path}")
            sys.exit(1)

        # Determine discharge date
        discharge_date = self._resolve_discharge_date(
            options.get("discharge_date"), pdf_path
        )
        self.stdout.write(
            f"Using discharge date: {discharge_date.strftime('%Y-%m-%d %H:%M')}"
        )

        # Import the PDF extraction function from automation
        automation_discharges_dir = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "discharges"
        )
        sys.path.insert(0, str(automation_discharges_dir))
        extract_discharges = importlib.import_module("extract_discharges")

        self.stdout.write(f"Extracting patients from {pdf_path}...")
        try:
            patients = extract_discharges.extract_patients_from_pdf(pdf_path)
        except Exception as exc:
            self.stderr.write(f"Failed to extract patients: {exc}")
            sys.exit(1)

        if not patients:
            self.stdout.write("No patients found in PDF.")
            return

        self.stdout.write(f"Patients found in PDF: {len(patients)}")
        for p in patients:
            self.stdout.write(
                f"  {p.get('prontuario', '?')} — {p.get('nome', '?')}"
                f" ({p.get('data_internacao', '?')})"
            )

        self.stdout.write("\nProcessing discharges...")
        metrics = process_discharges(
            patients, discharge_date=discharge_date
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nResults:\n"
                f"  Discharge set:        {metrics['discharge_set']}\n"
                f"  Already discharged:   {metrics['already_discharged']}\n"
                f"  Patient not found:    {metrics['patient_not_found']}\n"
                f"  Admission not found:  {metrics['admission_not_found']}"
            )
        )

    @staticmethod
    def _resolve_discharge_date(
        cli_date: str | None, pdf_path: Path
    ) -> datetime:
        """Resolve the discharge date from CLI arg, filename, or fallback."""
        if cli_date:
            try:
                dt = datetime.strptime(cli_date.strip(), "%Y-%m-%d")
                return timezone.make_aware(
                    dt.replace(hour=12, minute=0, second=0)
                )
            except ValueError:
                raise SystemExit(
                    f"Invalid date format: {cli_date!r}. Use YYYY-MM-DD."
                ) from None

        match = _FILENAME_DATE_RE.match(pdf_path.name)
        if match:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            dt = datetime(year, month, day, 12, 0, 0)
            return timezone.make_aware(dt)

        # Fallback: today at noon
        today = date.today()
        dt = datetime.combine(today, time(12, 0, 0))
        return timezone.make_aware(dt)
