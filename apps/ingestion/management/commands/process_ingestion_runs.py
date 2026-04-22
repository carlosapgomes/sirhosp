"""Worker that processes queued IngestionRuns (Slice S2 + S3).

Picks up runs in 'queued' state, plans extraction windows using the
cache-first gap planner, executes extraction only for gaps via the
Playwright connector, ingests events into the canonical model, and
transitions the run to 'succeeded' or 'failed'.

Slice S3 adds:
- Explicit admissions capture step before evolutions extraction.
- Semantics: admission failure => run.failed (evolutions not attempted).
- Preservation: admissions stay persisted even if evolutions fail.
- Run metrics: admissions_seen, admissions_created, admissions_updated.
"""

from __future__ import annotations

import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.utils import OperationalError, ProgrammingError
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
            try:
                runs = IngestionRun.objects.filter(status="queued")
                count = runs.count()
            except (OperationalError, ProgrammingError) as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"[{timezone.now():%H:%M:%S}] Worker startup check failed "
                        f"({exc.__class__.__name__}): {exc}. "
                        f"Retrying in {sleep_seconds}s..."
                    )
                )
                time.sleep(sleep_seconds)
                continue

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

        Slice S3 worker lifecycle:
        1. Transition to 'running'.
        2. Capture admissions snapshot (fails run if error).
        3. Plan extraction windows (cache-first).
        4. If full coverage: succeed with zero events.
        5. Extract evolutions for gap windows.
        6. Ingest evolutions (deterministic admission resolution).
        7. Transition to 'succeeded' with metrics.
        8. On any failure after admissions: preserve admissions + fail run.
        """
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")

        # Step 0: Transition to running
        run.status = "running"
        run.save(update_fields=["status"])

        extractor = PlaywrightEvolutionExtractor(
            script_path=script_path,
            headless=headless,
        )

        # ------------------------------------------------------------------
        # Step 1: Capture admissions snapshot (mandatory — fail-fast)
        # ------------------------------------------------------------------
        patient, adm_metrics = self._capture_admissions(
            run=run,
            extractor=extractor,
            patient_record=patient_record,
            start_date=start_date,
            end_date=end_date,
        )

        # Run already failed + saved in _capture_admissions on error
        if run.status == "failed":
            return

        # ------------------------------------------------------------------
        # Step 2: Plan extraction windows (cache-first)
        # ------------------------------------------------------------------
        plan = plan_extraction_windows(
            patient_source_key=patient_record,
            source_system="tasy",
            start_date=start_date,
            end_date=end_date,
        )
        run.gaps_json = plan["gaps"]

        if plan["skip_extraction"]:
            # Full coverage — nothing to extract
            run.admissions_seen = adm_metrics["seen"]
            run.admissions_created = adm_metrics["created"]
            run.admissions_updated = adm_metrics["updated"]
            run.events_processed = 0
            run.events_created = 0
            run.events_skipped = 0
            run.events_revised = 0
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()
            self.stdout.write(
                f"  Run #{run.pk} skipped extraction (full coverage)."
            )
            return

        # ------------------------------------------------------------------
        # Step 3: Extract evolutions for each gap window
        # ------------------------------------------------------------------
        all_evolutions: list[dict] = []
        try:
            for window in plan["windows"]:
                evolutions = extractor.extract_evolutions(
                    patient_record=patient_record,
                    start_date=window["start_date"],
                    end_date=window["end_date"],
                )
                all_evolutions.extend(evolutions)
        except ExtractionError as exc:
            # Admissions were captured — preserve them, fail the run
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save()
            self.stderr.write(f"  Run #{run.pk} failed during evolution extraction: {exc}")
            return

        # ------------------------------------------------------------------
        # Step 4: Ingest evolutions (deterministic admission resolution)
        # ------------------------------------------------------------------
        ev_created, ev_skipped, ev_revised = self._ingest_evolutions(
            all_evolutions, run, patient=patient
        )

        # Persist metrics
        run.events_processed = len(all_evolutions)
        run.events_created = ev_created
        run.events_skipped = ev_skipped
        run.events_revised = ev_revised
        run.admissions_seen = adm_metrics["seen"]
        run.admissions_created = adm_metrics["created"]
        run.admissions_updated = adm_metrics["updated"]
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.save()

        self.stdout.write(
            f"  Run #{run.pk} succeeded "
            f"(admissions_seen={adm_metrics['seen']}, "
            f"admissions_created={adm_metrics['created']}, "
            f"admissions_updated={adm_metrics['updated']}, "
            f"gaps={len(plan['windows'])}, "
            f"processed={len(all_evolutions)}, "
            f"created={ev_created}, "
            f"skipped={ev_skipped}, "
            f"revised={ev_revised})"
        )

    # ------------------------------------------------------------------
    # Slice S3: Admission capture step
    # ------------------------------------------------------------------

    def _capture_admissions(
        self,
        *,
        run: IngestionRun,
        extractor: PlaywrightEvolutionExtractor,
        patient_record: str,
        start_date: str,
        end_date: str,
    ) -> tuple:
        """Capture admissions snapshot for the patient.

        This step is mandatory — any extraction error results in run.failed.
        Admissions are persisted before evolutions to enable preservation
        semantics when evolutions fail later.

        Returns:
            Tuple of (patient, adm_metrics) where adm_metrics is
            dict with keys: seen, created, updated.

        Side-effects:
            - Creates/updates Patient and Admission records.
            - Transitions run to 'failed' on error.
        """
        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Patient

        adm_metrics = {"seen": 0, "created": 0, "updated": 0}

        try:
            admissions_snapshot = extractor.get_admission_snapshot(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
                timeout=120,
            )
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save()
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture: {exc}"
            )
            # Return dummy metrics so caller can check run.status == 'failed'
            return None, adm_metrics

        adm_metrics["seen"] = len(admissions_snapshot)

        if admissions_snapshot:
            # Create or get patient (for upsert)
            patient, _ = Patient.objects.get_or_create(
                source_system="tasy",
                patient_source_key=patient_record,
                defaults={"name": ""},
            )

            # Upsert admissions
            upsert_result = upsert_admission_snapshot(
                patient=patient,
                admissions_snapshot=admissions_snapshot,
            )
            adm_metrics["created"] = upsert_result.get("created", 0)
            adm_metrics["updated"] = upsert_result.get("updated", 0)
        else:
            # Snapshot empty but capture succeeded — still need patient record
            patient, _ = Patient.objects.get_or_create(
                source_system="tasy",
                patient_source_key=patient_record,
                defaults={"name": ""},
            )

        return patient, adm_metrics

    # ------------------------------------------------------------------
    # Ingestion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ingest_evolutions(
        evolutions: list[dict],
        run: IngestionRun,
        patient,
    ) -> tuple[int, int, int]:
        """Ingest a list of evolution dicts, returning (created, skipped, revised).

        For each evolution, admission is resolved via admission_key direct hit
        or by period-based fallback (Slice S2). Uses transaction.atomic to ensure
        consistency.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from django.db import transaction

        from apps.ingestion.services import resolve_admission_for_event

        created = 0
        skipped = 0
        revised = 0

        for evo in evolutions:
            with transaction.atomic():
                # Ensure patient exists (already upserted in admissions step)
                _patient = _upsert_patient(evo, run)

                # Resolve admission deterministically (Slice S2 fallback)
                admission_key = evo.get("admission_key", "")
                happened_at_str = evo.get("happened_at", "")
                if happened_at_str:
                    happened_at = datetime.fromisoformat(happened_at_str)
                    if happened_at.tzinfo is None:
                        happened_at = happened_at.replace(
                            tzinfo=ZoneInfo("America/Sao_Paulo")
                        )
                else:
                    happened_at = timezone.now()

                try:
                    admission = resolve_admission_for_event(
                        admission_key=admission_key,
                        happened_at=happened_at,
                        patient=patient,
                    )
                except Exception:
                    # Fallback: upsert from evolution data (legacy behaviour)
                    admission = _upsert_admission(evo, patient)

                _event, action = _persist_event(evo, patient, admission, run)

                if action == "created":
                    created += 1
                elif action == "skipped":
                    skipped += 1
                elif action == "revised":
                    revised += 1

        return created, skipped, revised