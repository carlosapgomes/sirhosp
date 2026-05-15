from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.deaths.models import DailyDeathCount
from apps.deaths.services import process_deaths
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


class Command(BaseCommand):
    help = "Extract deaths report from source system for a specific date."

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
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Start date for period in DD/MM/AAAA format.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="End date for period in DD/MM/AAAA format.",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        raw_date: str | None = options.get("date")
        raw_start: str | None = options.get("start_date")
        raw_end: str | None = options.get("end_date")

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

        # Resolve dates
        today = timezone.localdate()
        date_value = today.strftime("%d/%m/%Y")
        start_date: str
        end_date: str

        if raw_start and raw_end:
            start_date = raw_start
            end_date = raw_end
        elif raw_date:
            start_date = raw_date
            end_date = raw_date
        else:
            start_date = date_value
            end_date = date_value

        try:
            ref_date = datetime.strptime(start_date, "%d/%m/%Y").date()
        except ValueError:
            self.stderr.write(f"Invalid date format: {start_date}. Use DD/MM/AAAA.")
            sys.exit(1)

        self.stdout.write(f"Extracting deaths from {start_date} to {end_date}...")

        # Path to the extract_deaths.py script
        script_path = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "deaths"
            / "extract_deaths.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create IngestionRun
        run = IngestionRun.objects.create(
            status="running",
            intent="death_extraction",
            queued_at=timezone.now(),
            processing_started_at=timezone.now(),
            parameters_json={
                "start_date": start_date,
                "end_date": end_date,
                "ref_date": ref_date.isoformat(),
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # -- Stage: death_extraction (subprocess) -----------------------
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
                "--start-date",
                start_date,
                "--end-date",
                end_date,
            ]
            if headless:
                cmd.append("--headless")

            self.stdout.write("Running death extraction...")
            try:
                result = run_subprocess(
                    cmd,
                    timeout=600,
                    check=False,
                )
            except SubprocessTimeoutError as exc:
                self._record_stage(
                    run,
                    "death_extraction",
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
                self.stderr.write(f"Death extraction timed out: {exc}")
                sys.exit(1)
            except Exception as exc:
                self._record_stage(
                    run,
                    "death_extraction",
                    "failed",
                    ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(
                    run,
                    str(exc),
                    failure_reason="unexpected_exception",
                )
                self.stderr.write(f"Death extraction failed: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                err_msg = result.stderr[:500] if result.stderr else "Unknown error"
                self._record_stage(
                    run,
                    "death_extraction",
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
                "death_extraction",
                "succeeded",
                ext_stage_start,
            )

            # -- Stage: death_persistence (process JSON) --------------------
            persist_stage_start = timezone.now()

            json_files = sorted(
                tmpdir_path.glob("obitos-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not json_files:
                # Empty — no deaths found (success, just nothing to persist)
                metrics = {"total_records": 0}
                self._record_stage(
                    run,
                    "death_persistence",
                    "succeeded",
                    persist_stage_start,
                    details_json=metrics,
                )
                run.status = "succeeded"
                run.finished_at = timezone.now()
                run.save()

                DailyDeathCount.objects.update_or_create(
                    date=ref_date,
                    defaults={"count": 0, "raw_data": []},
                )

                self.stdout.write(self.style.SUCCESS("No deaths found for the period."))
                return

            json_path = json_files[0]
            self.stdout.write(f"  JSON output: {json_path}")

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                records = data.get("records", [])
                self.stdout.write(f"  Records extracted: {len(records)}")

                metrics = process_deaths(records, reference_date=ref_date)
                self.stdout.write(
                    f"  Total records persisted: {metrics['total_records']}"
                )
            except Exception as exc:
                self._record_stage(
                    run,
                    "death_persistence",
                    "failed",
                    persist_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(
                    run,
                    str(exc),
                    failure_reason="unexpected_exception",
                )
                self.stderr.write(f"Death processing failed: {exc}")
                sys.exit(1)

            self._record_stage(
                run,
                "death_persistence",
                "succeeded",
                persist_stage_start,
                details_json=metrics,
            )

            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Death extraction complete. "
                    f"{metrics['total_records']} records persisted."
                )
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
