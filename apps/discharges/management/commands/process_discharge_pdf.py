"""Process a single discharge PDF and set discharge_date on admissions.

Usage:
    uv run python manage.py process_discharge_pdf downloads/altas-01-05-2026.pdf

Extracts patients from the PDF, matches them to Admissions by
prontuario + data_internacao, and sets discharge_date = now().
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.discharges.services import process_discharges


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

    def handle(self, *args, **options):
        pdf_path = Path(options["pdf_path"])
        if not pdf_path.is_file():
            self.stderr.write(f"PDF not found: {pdf_path}")
            sys.exit(1)

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
        metrics = process_discharges(patients)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nResults:\n"
                f"  Discharge set:        {metrics['discharge_set']}\n"
                f"  Already discharged:   {metrics['already_discharged']}\n"
                f"  Patient not found:    {metrics['patient_not_found']}\n"
                f"  Admission not found:  {metrics['admission_not_found']}"
            )
        )
