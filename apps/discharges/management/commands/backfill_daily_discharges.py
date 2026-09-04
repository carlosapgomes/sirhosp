"""Deprecated PDF-based aggregate backfill (inactive compatibility stub).

RPSA-S3 retirement: ``backfill_daily_discharges`` is inactive. It was
the last executable caller of the dedicated PDF helper and a PDF-driven
writer of the operational ``DailyDischargeCount`` aggregate. Every
invocation fails with a safe deprecation error BEFORE any file access or
state change. The operational aggregate is rebuilt from canonical
effective exits (``saida_em``), never from PDFs.

Removal candidate after one release cycle without static or operational
callers, together with ``process_discharge_pdf`` and the dedicated
helper ``automation/source_system/discharges/pdf_utils.py``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "DEPRECATED and inactive: the PDF-based aggregate backfill fails "
        "safely before reading any PDF or changing any state. "
        "DailyDischargeCount is rebuilt from canonical effective exits."
    )

    def add_arguments(self, parser):
        # Kept for interface compatibility during the deprecation cycle;
        # every invocation fails in handle() before any argument use.
        parser.add_argument("pdf_dir", type=str, nargs="?", default="")

    def handle(self, *args, **options):
        raise CommandError(
            "backfill_daily_discharges is deprecated and inactive: the "
            "PDF-based aggregate backfill must not read PDFs or change "
            "aggregate or clinical state. This command is a removal "
            "candidate after the deprecation cycle."
        )
