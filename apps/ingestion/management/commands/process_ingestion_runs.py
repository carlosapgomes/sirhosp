"""Worker that processes queued IngestionRuns (Slice S2 + S3).

Picks up runs in 'queued' state, plans extraction windows using the
cache-first gap planner, executes extraction only for gaps via the
Playwright connector, ingests events into the canonical model, and
transitions the run to 'succeeded' or 'failed'.
"""

from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.playwright_extractor import PlaywrightEvolutionExtractor
from apps.ingestion.gap_planner import plan_extraction_windows
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import (
    _persist_event,
    _upsert_admission,
    _upsert_patient,
)

# Default path to internalized legacy Playwright script (MVP path2).
DEFAULT_SCRIPT_PATH = str(
    Path(__file__).resolve().parents[4]
    / "automation"
    / "source_system"
    / "medical_evolution"
    / "path2.py"
)


class Command(BaseCommand):
    help = "Process queued ingestion runs (async worker without Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--script-path",
            type=str,
            default=DEFAULT_SCRIPT_PATH,
            help="Absolute path to integrated legacy connector script path2.py.",
        )
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run Playwright in headless mode (default: True).",
        )
        parser.add_argument(
            "--no-headless",
            dest="headless",
            action="store_false",
            help="Run Playwright with a visible browser.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously, processing queued runs as they appear.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=5,
            help="Seconds to sleep when no queued runs are found (default: 5).",
        )

    def handle(self, *args, **options):
        script_path: str = options["script_path"]
        headless: bool = options["headless"]
        loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]

        if loop:
            self._run_loop(
                script_path=script_path,
                headless=headless,
                sleep_seconds=sleep_seconds,
            )
        else:
            self._process_once(
                script_path=script_path,
                headless=headless,
            )

    def _run_loop(
        self,
        script_path: str,
        headless: bool,
        sleep_seconds: int,
    ) -> None:
        """Continuously poll and process queued runs until interrupted."""
        import signal
        import sys

        def _signal_handler(signum, frame):
            self.stdout.write("\nReceived signal, shutting down worker gracefully...")
            sys.exit(0)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                f"Worker started in continuous mode (sleep={sleep_seconds}s)."
            )
        )

        while True:
            runs = IngestionRun.objects.filter(status="queued")
            count = runs.count()

            if count == 0:
                self.stdout.write(
                    f"[{timezone.now():%H:%M:%S}] No queued runs, sleeping {sleep_seconds}s..."
                )
            else:
                self.stdout.write(
                    f"[{timezone.now():%H:%M:%S}] Found {count} queued run(s), processing..."
                )
                for run in runs.iterator():
                    self._process_run(
                        run, script_path=script_path, headless=headless
                    )

            time.sleep(sleep_seconds)

    def _process_once(self, script_path: str, headless: bool) -> None:
        """Process all queued runs once and exit (original behavior)."""
        runs = IngestionRun.objects.filter(status="queued")
        count = runs.count()

        if count == 0:
            self.stdout.write("No queued runs to process.")
            return

        self.stdout.write(f"Processing {count} queued run(s)...")

        for run in runs.iterator():
            self._process_run(run, script_path=script_path, headless=headless)

        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_run(
        self,
        run: IngestionRun,
        *,
        script_path: str,
        headless: bool,
    ) -> None:
        """Process a single IngestionRun through its full lifecycle.

        Uses cache-first gap planning: only extracts date-ranges where
        no events exist yet for the patient.
        """
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")

        # Transition to running
        run.status = "running"
        run.save(update_fields=["status"])

        try:
            # Plan extraction windows (cache-first)
            plan = plan_extraction_windows(
                patient_source_key=patient_record,
                source_system="tasy",
                start_date=start_date,
                end_date=end_date,
            )
            run.gaps_json = plan["gaps"]

            if plan["skip_extraction"]:
                # Full coverage — nothing to extract
                run.status = "succeeded"
                run.events_processed = 0
                run.events_created = 0
                run.events_skipped = 0
                run.events_revised = 0
                run.finished_at = timezone.now()
                run.save()

                self.stdout.write(
                    f"  Run #{run.pk} skipped extraction (full coverage)."
                )
                return

            # Extract each gap window
            extractor = PlaywrightEvolutionExtractor(
                script_path=script_path,
                headless=headless,
            )

            all_evolutions: list[dict] = []
            for window in plan["windows"]:
                evolutions = extractor.extract_evolutions(
                    patient_record=patient_record,
                    start_date=window["start_date"],
                    end_date=window["end_date"],
                )
                all_evolutions.extend(evolutions)

            # Ingest extracted evolutions using existing helpers
            created, skipped, revised = self._ingest_evolutions(all_evolutions, run)

            run.events_processed = len(all_evolutions)
            run.events_created = created
            run.events_skipped = skipped
            run.events_revised = revised
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(
                f"  Run #{run.pk} succeeded "
                f"(gaps={len(plan['windows'])}, "
                f"processed={len(all_evolutions)}, "
                f"created={created}, skipped={skipped}, revised={revised})"
            )

        except ExtractionError as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save()

            self.stderr.write(f"  Run #{run.pk} failed: {exc}")

        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save()

            self.stderr.write(f"  Run #{run.pk} failed with unexpected error: {exc}")

    @staticmethod
    def _ingest_evolutions(
        evolutions: list[dict],
        run: IngestionRun,
    ) -> tuple[int, int, int]:
        """Ingest a list of evolution dicts, returning (created, skipped, revised).

        Reuses the same persistence helpers from services.py to ensure
        consistent dedup, upsert and revision logic.
        """
        from django.db import transaction

        created = 0
        skipped = 0
        revised = 0

        for evo in evolutions:
            with transaction.atomic():
                patient = _upsert_patient(evo, run)
                admission = _upsert_admission(evo, patient)
                _event, action = _persist_event(evo, patient, admission, run)

                if action == "created":
                    created += 1
                elif action == "skipped":
                    skipped += 1
                elif action == "revised":
                    revised += 1

        return created, skipped, revised
