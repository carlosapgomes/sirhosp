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
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.ingestion.extractors.playwright_extractor import PlaywrightEvolutionExtractor
from apps.ingestion.gap_planner import plan_extraction_windows
from apps.ingestion.models import IngestionRun, IngestionRunAttempt
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

# Path to the demographics extraction Playwright script.
DEMOGRAPHICS_SCRIPT_PATH = str(
    Path(__file__).resolve().parents[4]
    / "automation"
    / "source_system"
    / "patient_demographics"
    / "extract_patient_demographics.py"
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

    @staticmethod
    def _claim_eligible_run() -> IngestionRun | None:
        """Claim the next eligible queued run respecting next_retry_at.

        Eligible = status='queued' AND (next_retry_at IS NULL OR next_retry_at <= now).
        Uses select_for_update(skip_locked=True) for safe concurrent access.
        """
        now = timezone.now()
        from django.db.models import Q

        return (
            IngestionRun.objects
            .select_for_update(skip_locked=True)
            .filter(
                status="queued",
            )
            .filter(
                Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now),
            )
            .order_by("pk")
            .first()
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
                time.sleep(sleep_seconds)
                continue

            self.stdout.write(
                f"[{timezone.now():%H:%M:%S}] Found {count} queued run(s), processing..."
            )
            # Claim and process runs atomically (safe for multiple workers)
            while True:
                with transaction.atomic():
                    run = self._claim_eligible_run()
                    if run is None:
                        break
                    run.status = "running"
                    run.save(update_fields=["status"])
                self._process_run(
                    run, script_path=script_path, headless=headless
                )

    def _process_once(self, script_path: str, headless: bool) -> None:
        """Process all queued runs once and exit (original behavior)."""
        runs = IngestionRun.objects.filter(status="queued")
        count = runs.count()

        if count == 0:
            self.stdout.write("No queued runs to process.")
            return

        self.stdout.write(f"Processing {count} queued run(s)...")

        # Claim and process runs atomically (safe for multiple workers)
        while True:
            with transaction.atomic():
                run = self._claim_eligible_run()
                if run is None:
                    break
                run.status = "running"
                run.save(update_fields=["status"])
            self._process_run(run, script_path=script_path, headless=headless)

        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_failure_reason(exc: Exception) -> tuple[str, bool]:
        """Classify an exception into normalized failure taxonomy.

        Returns:
            (failure_reason, timed_out)
        """
        from django.core.exceptions import ValidationError

        from apps.ingestion.extractors.errors import (
            ExtractionError,
            ExtractionTimeoutError,
            InvalidJsonError,
        )
        from apps.ingestion.extractors.subprocess_utils import (
            SubprocessTimeoutError,
        )

        if isinstance(exc, (ExtractionTimeoutError, SubprocessTimeoutError)):
            return ("timeout", True)
        if isinstance(exc, InvalidJsonError):
            return ("invalid_payload", False)
        if isinstance(exc, ValidationError):
            return ("validation_error", False)
        if isinstance(exc, ExtractionError):
            return ("source_unavailable", False)
        return ("unexpected_exception", False)

    @staticmethod
    def _record_stage(
        run: IngestionRun,
        stage_name: str,
        status: str,
        started_at,
        finished_at=None,
        details_json=None,
    ):
        """Persist a stage metric record for the given run.

        Args:
            run: The IngestionRun instance.
            stage_name: Stage identifier (e.g. 'admissions_capture').
            status: One of 'succeeded', 'failed', 'skipped'.
            started_at: Datetime when the stage started.
            finished_at: Datetime when the stage finished (defaults to now).
            details_json: Optional dict with stage-level context.
        """
        from apps.ingestion.models import IngestionRunStageMetric

        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    @staticmethod
    def _stage_error_details(exc: Exception) -> dict:
        """Build normalized stage-level error details payload."""
        return {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }

    def _mark_run_failed(self, run: IngestionRun, exc: Exception) -> None:
        """Transition run to failed with retry logic.

        CQM-S3: On failure, if attempts remain, requeue with backoff.
        Otherwise mark as terminally failed.

        Note: attempt_count was already incremented in _process_run.
        """
        failure_reason, timed_out = self._classify_failure_reason(exc)
        now = timezone.now()

        # Update the existing attempt record (created in _process_run)
        attempt = (
            IngestionRunAttempt.objects
            .filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        if attempt is not None:
            attempt.finished_at = now
            attempt.status = "failed"
            attempt.failure_reason = failure_reason
            attempt.timed_out = timed_out
            attempt.error_message = str(exc)
            attempt.save(
                update_fields=[
                    "finished_at",
                    "status",
                    "failure_reason",
                    "timed_out",
                    "error_message",
                ]
            )

        if run.attempt_count < run.max_attempts:
            # Requeue with backoff (CQM-S3: 60s fixed)
            run.status = "queued"
            run.next_retry_at = now + timedelta(seconds=60)
            run.failure_reason = failure_reason
            run.timed_out = timed_out
            run.error_message = str(exc)
            run.save(
                update_fields=[
                    "status",
                    "next_retry_at",
                    "failure_reason",
                    "timed_out",
                    "error_message",
                ]
            )
            self.stdout.write(
                f"  Run #{run.pk} failed (attempt {run.attempt_count}/"
                f"{run.max_attempts}), requeued at {run.next_retry_at}"
            )
        else:
            # Terminal failure — no more retries
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = now
            run.failure_reason = failure_reason
            run.timed_out = timed_out
            run.next_retry_at = None
            run.save(
                update_fields=[
                    "status",
                    "error_message",
                    "finished_at",
                    "failure_reason",
                    "timed_out",
                    "next_retry_at",
                ]
            )
            self.stderr.write(
                f"  Run #{run.pk} failed permanently "
                f"(attempt {run.attempt_count}/{run.max_attempts}): {exc}"
            )

    def _process_run(
        self,
        run: IngestionRun,
        *,
        script_path: str,
        headless: bool,
    ) -> None:
        """Process a single IngestionRun through its full lifecycle.

        Dispatches to admissions-only or full-sync based on intent.
        """
        params = run.parameters_json or {}
        intent = params.get("intent", "") or run.intent

        # Step 0: Transition to running + record attempt start (CQM-S3)
        run.status = "running"
        run.attempt_count += 1
        if run.processing_started_at is None:
            run.processing_started_at = timezone.now()
        run.save(update_fields=["status", "attempt_count", "processing_started_at"])

        # Persist attempt start record
        IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=run.attempt_count,
        )

        if intent == "admissions_only":
            self._process_admissions_only(
                run=run,
                script_path=script_path,
                headless=headless,
            )
        elif intent == "demographics_only":
            self._process_demographics_only(run=run)
        else:
            self._process_full_sync(
                run=run,
                script_path=script_path,
                headless=headless,
            )

    # ------------------------------------------------------------------
    # Admissions-only processing (AFMF-S2)
    # ------------------------------------------------------------------

    def _process_admissions_only(
        self,
        run: IngestionRun,
        *,
        script_path: str,
        headless: bool,
    ) -> None:
        """Process admissions-only run: capture snapshot, no evolution extraction."""
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")

        extractor = PlaywrightEvolutionExtractor(
            script_path=script_path,
            headless=headless,
        )

        adm_stage_start = timezone.now()
        try:
            patient, adm_metrics = self._capture_admissions(
                run=run,
                extractor=extractor,
                patient_record=patient_record,
                start_date="",
                end_date="",
            )
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="admissions_capture",
                status="failed",
                started_at=adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture: {exc}"
            )
            return

        self._record_stage(
            run=run,
            stage_name="admissions_capture",
            status="succeeded",
            started_at=adm_stage_start,
        )

        # Admissions-only: persist metrics and succeed, no gap planning
        run.admissions_seen = adm_metrics["seen"]
        run.admissions_created = adm_metrics["created"]
        run.admissions_updated = adm_metrics["updated"]
        run.events_processed = 0
        run.events_created = 0
        run.events_skipped = 0
        run.events_revised = 0
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.failure_reason = ""
        run.timed_out = False
        run.save()

        # Mark attempt as succeeded (CQM-S3)
        self._mark_latest_attempt_succeeded(run)

        # Auto-enqueue full_sync for the most recent admission
        if patient is not None:
            full_sync_run = self._enqueue_most_recent_full_sync(patient, run)
            if full_sync_run:
                self.stdout.write(
                    f"  Auto-enqueued full_sync run #{full_sync_run.pk} "
                    f"for most recent admission"
                )

        self.stdout.write(
            f"  Run #{run.pk} admissions-only succeeded "
            f"(admissions_seen={adm_metrics['seen']}, "
            f"admissions_created={adm_metrics['created']}, "
            f"admissions_updated={adm_metrics['updated']})"
        )

    # ------------------------------------------------------------------
    # Demographics-only processing (DI-1)
    # ------------------------------------------------------------------

    def _process_demographics_only(
        self,
        run: IngestionRun,
    ) -> None:
        """Process demographics-only run: extract and persist patient demographics.

        Executes the demographics Playwright script as a subprocess,
        reads the JSON output, and calls upsert_patient_demographics().
        """
        import json
        import sys
        import tempfile

        from apps.ingestion.extractors.subprocess_utils import (
            SubprocessTimeoutError,
            run_subprocess,
        )
        from apps.ingestion.services import upsert_patient_demographics

        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")

        if not patient_record:
            self._mark_run_failed(
                run, ValueError("Missing patient_record in parameters")
            )
            return

        # Stage: demographics_extraction (subprocess)
        ext_stage_start = timezone.now()

        with tempfile.TemporaryDirectory() as tmpdir:
            json_output_path = Path(tmpdir) / "demographics_output.json"

            cmd = [
                sys.executable,
                DEMOGRAPHICS_SCRIPT_PATH,
                "--patient-record", patient_record,
                "--headless",
                "--json-output", str(json_output_path),
            ]

            try:
                result = run_subprocess(
                    cmd,
                    timeout=300,  # 5 minutes max for single-patient extraction
                )
            except SubprocessTimeoutError as exc:
                self._record_stage(
                    run=run,
                    stage_name="demographics_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json=self._stage_error_details(exc),
                )
                self._mark_run_failed(run, exc)
                return
            except Exception as exc:
                self._record_stage(
                    run=run,
                    stage_name="demographics_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json=self._stage_error_details(exc),
                )
                self._mark_run_failed(run, exc)
                return

            if result.returncode != 0:
                err_msg = f"Exit code {result.returncode}: {result.stderr[:500]}"
                self._record_stage(
                    run=run,
                    stage_name="demographics_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"returncode": result.returncode},
                )
                run.status = "failed"
                run.error_message = err_msg
                run.finished_at = timezone.now()
                run.failure_reason = "source_unavailable"
                run.timed_out = False
                run.save()
                return

            # Stage: demographics_extraction succeeded
            self._record_stage(
                run=run,
                stage_name="demographics_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # Read JSON output
            if not json_output_path.exists():
                self._mark_run_failed(
                    run,
                    ValueError(f"JSON output not found at {json_output_path}"),
                )
                return

            try:
                demographics_data = json.loads(
                    json_output_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                self._mark_run_failed(run, exc)
                return

        # Stage: demographics_persistence (upsert)
        persist_stage_start = timezone.now()
        try:
            patient = upsert_patient_demographics(
                patient_source_key=patient_record,
                source_system="tasy",
                demographics=demographics_data,
                run=run,
            )
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="demographics_persistence",
                status="failed",
                started_at=persist_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        self._record_stage(
            run=run,
            stage_name="demographics_persistence",
            status="succeeded",
            started_at=persist_stage_start,
        )

        # Count how many fields were populated (non-empty after upsert)
        fields_populated = sum(
            1
            for field_name in [
                "name", "social_name", "date_of_birth", "gender",
                "gender_identity", "mother_name", "father_name",
                "race_color", "birthplace", "nationality",
                "marital_status", "education_level", "profession",
                "cns", "cpf", "phone_home", "phone_cellular",
                "phone_contact", "street", "address_number",
                "address_complement", "neighborhood", "city",
                "state", "postal_code",
            ]
            if getattr(patient, field_name, None)
        )

        # Success
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.failure_reason = ""
        run.timed_out = False
        # Store demographics metrics in parameters_json
        run.parameters_json = {
            **params,
            "demographics_fields_extracted": fields_populated,
        }
        run.save()

        # Mark attempt as succeeded (CQM-S3)
        self._mark_latest_attempt_succeeded(run)

        self.stdout.write(
            f"  Run #{run.pk} demographics_only succeeded "
            f"(fields_populated={fields_populated})"
        )

    # ------------------------------------------------------------------
    # Full-sync processing (legacy)
    # ------------------------------------------------------------------

    def _process_full_sync(
        self,
        run: IngestionRun,
        *,
        script_path: str,
        headless: bool,
    ) -> None:
        """Process full-sync run: admissions + gap planning + evolution extraction.

        Uses cache-first gap planning: only extracts date-ranges where
        no events exist yet for the patient.

        Slice S3 worker lifecycle:
        1. Capture admissions snapshot (fails run if error).
        2. Plan extraction windows (cache-first).
        3. If full coverage: succeed with zero events.
        4. Extract evolutions for gap windows.
        5. Ingest evolutions (deterministic admission resolution).
        6. Transition to 'succeeded' with metrics.
        7. On any failure after admissions: preserve admissions + fail run.
        """
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")

        extractor = PlaywrightEvolutionExtractor(
            script_path=script_path,
            headless=headless,
        )

        # ------------------------------------------------------------------
        # Step 1: Capture admissions snapshot (mandatory — fail-fast)
        # ------------------------------------------------------------------
        adm_stage_start = timezone.now()
        try:
            patient, adm_metrics = self._capture_admissions(
                run=run,
                extractor=extractor,
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="admissions_capture",
                status="failed",
                started_at=adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture: {exc}"
            )
            return

        self._record_stage(
            run=run,
            stage_name="admissions_capture",
            status="succeeded",
            started_at=adm_stage_start,
        )

        # ------------------------------------------------------------------
        # Step 2: Plan extraction windows (cache-first)
        # ------------------------------------------------------------------
        gap_stage_start = timezone.now()
        try:
            plan = plan_extraction_windows(
                patient_source_key=patient_record,
                source_system="tasy",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="gap_planning",
                status="failed",
                started_at=gap_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(f"  Run #{run.pk} failed during gap planning: {exc}")
            return

        run.gaps_json = plan["gaps"]
        self._record_stage(
            run=run,
            stage_name="gap_planning",
            status="succeeded",
            started_at=gap_stage_start,
        )

        if plan["skip_extraction"]:
            # Full coverage — evolution_extraction skipped
            self._record_stage(
                run=run,
                stage_name="evolution_extraction",
                status="skipped",
                started_at=timezone.now(),
            )
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
            run.failure_reason = ""
            run.timed_out = False
            run.save()
            self.stdout.write(
                f"  Run #{run.pk} skipped extraction (full coverage)."
            )
            return

        # ------------------------------------------------------------------
        # Step 3: Extract evolutions for each gap window
        # ------------------------------------------------------------------
        ev_stage_start = timezone.now()
        all_evolutions: list[dict] = []
        try:
            for window in plan["windows"]:
                evolutions = extractor.extract_evolutions(
                    patient_record=patient_record,
                    start_date=window["start_date"],
                    end_date=window["end_date"],
                )
                all_evolutions.extend(evolutions)
        except Exception as exc:
            # Admissions were captured — preserve them, fail the run
            self._record_stage(
                run=run,
                stage_name="evolution_extraction",
                status="failed",
                started_at=ev_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(f"  Run #{run.pk} failed during evolution extraction: {exc}")
            return
        self._record_stage(
            run=run,
            stage_name="evolution_extraction",
            status="succeeded",
            started_at=ev_stage_start,
        )

        # ------------------------------------------------------------------
        # Step 4: Ingest evolutions (deterministic admission resolution)
        # ------------------------------------------------------------------
        ingest_stage_start = timezone.now()
        try:
            ev_created, ev_skipped, ev_revised = self._ingest_evolutions(
                all_evolutions, run, patient=patient
            )
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="ingestion_persistence",
                status="failed",
                started_at=ingest_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(f"  Run #{run.pk} failed during ingestion persistence: {exc}")
            return

        self._record_stage(
            run=run,
            stage_name="ingestion_persistence",
            status="succeeded",
            started_at=ingest_stage_start,
            details_json={
                "processed": len(all_evolutions),
                "created": ev_created,
                "skipped": ev_skipped,
                "revised": ev_revised,
            },
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
        run.failure_reason = ""
        run.timed_out = False
        run.save()

        # Mark attempt as succeeded (CQM-S3)
        self._mark_latest_attempt_succeeded(run)

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
            - Propagates extractor errors to caller.
        """
        from apps.ingestion.services import upsert_admission_snapshot
        from apps.patients.models import Patient

        adm_metrics = {"seen": 0, "created": 0, "updated": 0}

        # For admissions-only runs with no date range, use a wide default
        snap_start = start_date or "2000-01-01"
        snap_end = end_date or timezone.now().strftime("%Y-%m-%d")
        admissions_snapshot = extractor.get_admission_snapshot(
            patient_record=patient_record,
            start_date=snap_start,
            end_date=snap_end,
            timeout=120,
        )

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

    # ------------------------------------------------------------------
    # Slice S5: Auto-enqueue full_sync after admissions_only
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_latest_attempt_succeeded(run: IngestionRun) -> None:
        """Mark the latest attempt for this run as succeeded (CQM-S3)."""
        attempt = (
            IngestionRunAttempt.objects
            .filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        if attempt is not None:
            attempt.status = "succeeded"
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "finished_at"])

    @staticmethod
    def _enqueue_most_recent_full_sync(patient, run):
        """Enqueue a full_sync run for the patient's most recent admission.

        CQM-S3: Inherits batch from the source run.

        Returns the created IngestionRun or None if no admission exists.
        """
        from django.utils import timezone

        from apps.ingestion.models import IngestionRun
        from apps.patients.models import Admission

        latest = (
            Admission.objects.filter(patient=patient)
            .order_by("-admission_date")
            .first()
        )
        if latest is None:
            return None

        # Calculate end_date: use discharge_date if available,
        # otherwise use current time (still admitted)
        if latest.discharge_date:
            end_date = latest.discharge_date.strftime("%Y-%m-%d")
        else:
            end_date = timezone.now().strftime("%Y-%m-%d")

        return IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            batch=run.batch,
            parameters_json={
                "patient_record": patient.patient_source_key,
                "admission_id": str(latest.pk),
                "admission_source_key": latest.source_admission_key,
                "start_date": latest.admission_date.strftime("%Y-%m-%d")
                    if latest.admission_date else "",
                "end_date": end_date,
                "intent": "full_sync",
            },
        )