"""Deprecated legacy PDF discharge command (inactive compatibility stub).

RPSA-S3 retirement: ``process_discharge_pdf`` is inactive. Every
invocation fails with a safe deprecation error BEFORE any file access,
identity output, evidence persistence, work enqueueing or change to
aggregate or clinical state. Layered discharge coverage is provided by
the XLS extraction (``extract_discharges``), admissions snapshots, death
extraction and census-triggered source confirmation.

Removal candidate after one release cycle without static or operational
callers, together with ``backfill_daily_discharges`` and the dedicated
helper ``automation/source_system/discharges/pdf_utils.py``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "DEPRECATED and inactive: the legacy PDF discharge flow fails "
        "safely before reading any PDF or changing any state. Use "
        "extract_discharges (XLS) instead."
    )

    def add_arguments(self, parser):
        # Kept for interface compatibility during the deprecation cycle;
        # every invocation fails in handle() before any argument use.
        parser.add_argument("pdf_path", type=str, nargs="?", default="")
        parser.add_argument("--discharge-date", type=str, default=None)

    def handle(self, *args, **options):
        raise CommandError(
            "process_discharge_pdf is deprecated and inactive: the legacy "
            "PDF discharge flow must not read PDFs, print patient data, "
            "persist evidence, enqueue work or change aggregate or "
            "clinical state. Use extract_discharges (XLS) instead. This "
            "command is a removal candidate after the deprecation cycle."
        )
