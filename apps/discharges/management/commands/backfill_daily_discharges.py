"""One-shot management command to backfill DailyDischargeCount from PDF files.

Usage:
    uv run python manage.py backfill_daily_discharges /path/to/pdf/dir

Reads PDFs named altas-DD-MM-YYYY.pdf, extracts patient count from each,
and upserts into DailyDischargeCount.

This is a one-shot script — not intended for production scheduling.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.discharges.models import DailyDischargeCount


class Command(BaseCommand):
    help = (
        "Backfill DailyDischargeCount from historical discharge PDFs. "
        "One-shot script: point it at a directory of altas-DD-MM-YYYY.pdf files."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "pdf_dir",
            type=str,
            help="Directory containing altas-DD-MM-YYYY.pdf files",
        )

    def handle(self, *args, **options):
        pdf_dir = Path(options["pdf_dir"])
        if not pdf_dir.is_dir():
            self.stderr.write(f"Not a directory: {pdf_dir}")
            sys.exit(1)

        pdf_pattern = re.compile(r"altas-(\d{2})-(\d{2})-(\d{4})\.pdf$")
        pdfs = sorted(
            p for p in pdf_dir.iterdir()
            if p.is_file() and pdf_pattern.match(p.name)
        )

        if not pdfs:
            self.stderr.write(f"No altas-DD-MM-YYYY.pdf files found in {pdf_dir}")
            sys.exit(1)

        self.stdout.write(f"Found {len(pdfs)} PDF(s) to process.\n")

        for pdf_path in pdfs:
            match = pdf_pattern.match(pdf_path.name)
            assert match
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            pdf_date = date(year, month, day)

            try:
                count = self._count_patients(pdf_path)
            except Exception as exc:
                self.stderr.write(f"  ERROR {pdf_path.name}: {exc}")
                continue

            DailyDischargeCount.objects.update_or_create(
                date=pdf_date,
                defaults={"count": count},
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  {pdf_date} → {count} altas"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {len(pdfs)} PDF(s) processed."
            )
        )

    @staticmethod
    def _count_patients(pdf_path: Path) -> int:
        """Count patients in a discharge PDF using the existing extraction code.

        We import extract_patients_from_pdf from the automation module.
        Fallback: count prontuario patterns directly via PyMuPDF if the
        extraction module is not importable.
        """
        try:
            # Try to use the full extraction pipeline
            sys.path.insert(
                0,
                str(Path(__file__).resolve().parents[4] / "automation" / "source_system" / "discharges"),
            )
            from extract_discharges import extract_patients_from_pdf  # type: ignore[import-not-found]

            patients = extract_patients_from_pdf(pdf_path)
            return len(patients)
        except Exception:
            # Fallback: count prontuario patterns directly
            import pymupdf  # type: ignore[import-untyped]

            pront_re = re.compile(r"^\d{2,7}/\d$")
            count = 0

            with pymupdf.open(pdf_path) as doc:
                for page in doc:
                    words = page.get_text("words")
                    for word in words:
                        if len(word) >= 5 and pront_re.match(str(word[4])):
                            count += 1

            return count
