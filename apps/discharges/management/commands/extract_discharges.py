from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount
from apps.discharges.services import process_discharges
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


class Command(BaseCommand):
    help = "Extract today's discharges from source system and update Admission records."

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

    def handle(self, *args, **options):
        headless: bool = options["headless"]

        # Resolve credentials from settings/environment
        from django.conf import settings

        source_url = getattr(settings, "SOURCE_SYSTEM_URL", "") or os.getenv(
            "SOURCE_SYSTEM_URL", ""
        )
        username = getattr(settings, "SOURCE_SYSTEM_USERNAME", "") or os.getenv(
            "SOURCE_SYSTEM_USERNAME", ""
        )
        password = getattr(settings, "SOURCE_SYSTEM_PASSWORD", "") or os.getenv(
            "SOURCE_SYSTEM_PASSWORD", ""
        )

        if not all([source_url, username, password]):
            self.stderr.write("Missing source system credentials in settings.")
            sys.exit(1)

        # Path to the extract_discharges.py script
        script_path = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "discharges"
            / "extract_discharges.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create IngestionRun
        run = IngestionRun.objects.create(
            status="running",
            intent="discharge_extraction",
            queued_at=timezone.now(),
            processing_started_at=timezone.now(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # -- Stage: discharge_extraction (subprocess) -----------------
            ext_stage_start = timezone.now()
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir",
                str(tmpdir_path),
                "--source-url",
                source_url,
                "--username",
                username,
                "--password",
                password,
            ]
            if headless:
                cmd.append("--headless")

            self.stdout.write("Running discharge extraction...")
            try:
                result = run_subprocess(
                    cmd,
                    timeout=600,
                    check=False,
                )
            except SubprocessTimeoutError as exc:
                self._record_stage(
                    run,
                    "discharge_extraction",
                    "failed",
                    ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(
                    run,
                    str(exc),
                    failure_reason="timeout",
                    timed_out=True,
                )
                self.stderr.write(f"Discharge extraction timed out: {exc}")
                sys.exit(1)
            except Exception as exc:
                self._record_stage(
                    run,
                    "discharge_extraction",
                    "failed",
                    ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(
                    run,
                    str(exc),
                    failure_reason="unexpected_exception",
                )
                self.stderr.write(f"Discharge extraction failed: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                err_msg = result.stderr[:500] if result.stderr else "Unknown error"
                self._record_stage(
                    run,
                    "discharge_extraction",
                    "failed",
                    ext_stage_start,
                    details_json={"returncode": result.returncode},
                )
                self._mark_run_failed(
                    run,
                    err_msg,
                    failure_reason="source_unavailable",
                )
                self.stderr.write(result.stderr)
                sys.exit(1)

            self._record_stage(
                run,
                "discharge_extraction",
                "succeeded",
                ext_stage_start,
            )

            # -- Stage: discharge_persistence (process JSON) --------------
            persist_stage_start = timezone.now()

            # Find JSON output
            json_files = sorted(
                tmpdir_path.glob("discharges-*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not json_files:
                # Empty list — no discharges today (success, just nothing to do)
                metrics = {
                    "total_pdf": 0,
                    "discharge_set": 0,
                    "patient_not_found": 0,
                    "admission_not_found": 0,
                    "already_discharged": 0,
                }
                self._record_stage(
                    run,
                    "discharge_persistence",
                    "succeeded",
                    persist_stage_start,
                    details_json=metrics,
                )
                run.status = "succeeded"
                run.finished_at = timezone.now()
                run.save()

                # Record zero discharges for today (source of truth: PDF)
                DailyDischargeCount.objects.update_or_create(
                    date=date.today(),
                    defaults={"count": 0},
                )

                self.stdout.write(self.style.SUCCESS("No discharges found today."))
                return

            json_path = json_files[0]
            self.stdout.write(f"  JSON output: {json_path}")

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                patients = data.get("pacientes", [])
                self.stdout.write(f"  Patients in PDF: {len(patients)}")

                metrics = process_discharges(patients)
                self.stdout.write(
                    f"  Discharge set: {metrics['discharge_set']} | "
                    f"Already discharged: {metrics['already_discharged']} | "
                    f"Patient not found: {metrics['patient_not_found']} | "
                    f"Admission not found: {metrics['admission_not_found']}"
                )
            except Exception as exc:
                self._record_stage(
                    run,
                    "discharge_persistence",
                    "failed",
                    persist_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(
                    run,
                    str(exc),
                    failure_reason="unexpected_exception",
                )
                self.stderr.write(f"Discharge processing failed: {exc}")
                sys.exit(1)

            self._record_stage(
                run,
                "discharge_persistence",
                "succeeded",
                persist_stage_start,
                details_json=metrics,
            )

            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            # Record discharge count from PDF (source of truth)
            pdf_date_str = data.get("data", "")
            try:
                pdf_date = (
                    date.fromisoformat(pdf_date_str)
                    if pdf_date_str
                    else date.today()
                )
            except ValueError:
                pdf_date = date.today()

            DailyDischargeCount.objects.update_or_create(
                date=pdf_date,
                defaults={"count": len(patients)},
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Discharge extraction complete. "
                    f"{metrics['discharge_set']} discharges set."
                )
            )

    @staticmethod
    def _record_stage(
        run: IngestionRun,
        stage_name: str,
        status: str,
        started_at,
        finished_at=None,
        details_json: dict[str, Any] | None = None,
    ) -> None:
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    def _mark_run_failed(
        self,
        run: IngestionRun,
        error_message: str,
        failure_reason: str = "",
        timed_out: bool = False,
    ) -> None:
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = timezone.now()
        run.failure_reason = failure_reason
        run.timed_out = timed_out
        run.save()
