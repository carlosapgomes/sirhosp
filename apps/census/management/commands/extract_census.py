from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.census.models import CensusSnapshot
from apps.census.services import parse_census_csv
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


class Command(BaseCommand):
    help = "Run census extraction script and persist snapshot."

    def add_arguments(self, parser):
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
            help="Run Playwright with visible browser.",
        )
        parser.add_argument(
            "--max-setores",
            type=int,
            default=0,
            help="Limit sectors (0 = all).",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        max_setores: int = options["max_setores"]

        # Path to the extract_census.py script
        script_path = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "current_inpatients"
            / "extract_census.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create temp directory for output
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Build subprocess command
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir",
                str(tmpdir_path),
            ]
            if headless:
                cmd.append("--headless")
            if max_setores > 0:
                cmd.extend(["--max-setores", str(max_setores)])

            self.stdout.write("Running census extraction...")
            self.stdout.write(f"  Script: {script_path}")

            # Create IngestionRun to track this execution
            run = IngestionRun.objects.create(
                status="running",
                intent="census_extraction",
                queued_at=timezone.now(),
                processing_started_at=timezone.now(),
            )

            # -- Stage: census_extraction (subprocess) ---------------------
            ext_stage_start = timezone.now()
            try:
                result = run_subprocess(
                    cmd,
                    timeout=1800,  # 30 minutes max
                )
            except SubprocessTimeoutError as exc:
                self._record_stage(
                    run=run,
                    stage_name="census_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(run, exc)
                self.stderr.write(f"Census extraction timed out: {exc}")
                sys.exit(1)
            except Exception as exc:
                self._record_stage(
                    run=run,
                    stage_name="census_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"error_type": exc.__class__.__name__,
                                  "error": str(exc)},
                )
                self._mark_run_failed(run, exc)
                self.stderr.write(f"Census extraction failed: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                err_msg = (
                    f"Exit code {result.returncode}: {result.stderr[:500]}"
                )
                self._record_stage(
                    run=run,
                    stage_name="census_extraction",
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
                self.stderr.write(result.stderr)
                sys.exit(1)

            self._record_stage(
                run=run,
                stage_name="census_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # -- Stage: census_persistence (CSV parse + snapshot) ----------
            persist_stage_start = timezone.now()

            # Find the CSV file in output dir
            csv_files = list(tmpdir_path.glob("censo-*.csv"))
            if not csv_files:
                # Try to find any CSV
                csv_files = list(tmpdir_path.glob("*.csv"))

            if not csv_files:
                self._record_stage(
                    run=run,
                    stage_name="census_persistence",
                    status="failed",
                    started_at=persist_stage_start,
                    details_json={"error": "No CSV output found"},
                )
                run.status = "failed"
                run.error_message = "No CSV output found after extraction."
                run.finished_at = timezone.now()
                run.failure_reason = "source_unavailable"
                run.timed_out = False
                run.save()
                self.stderr.write("No CSV output found.")
                sys.exit(1)

            csv_path = csv_files[0]
            self.stdout.write(f"  CSV output: {csv_path}")

            try:
                # Parse CSV and classify bed status
                parsed_rows = parse_census_csv(csv_path)
                self.stdout.write(f"  Rows parsed: {len(parsed_rows)}")

                # Bulk create CensusSnapshot rows
                captured_at = timezone.now()
                snapshots = [
                    CensusSnapshot(
                        captured_at=captured_at,
                        ingestion_run=run,
                        setor=row["setor"],
                        leito=row["leito"],
                        prontuario=row["prontuario"],
                        nome=row["nome"],
                        especialidade=row["especialidade"],
                        bed_status=row["bed_status"],
                    )
                    for row in parsed_rows
                ]

                CensusSnapshot.objects.bulk_create(snapshots)
                self.stdout.write(f"  Snapshots persisted: {len(snapshots)}")
            except Exception as exc:
                self._record_stage(
                    run=run,
                    stage_name="census_persistence",
                    status="failed",
                    started_at=persist_stage_start,
                    details_json={
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    },
                )
                self._mark_run_failed(run, exc)
                self.stderr.write(f"Census persistence failed: {exc}")
                sys.exit(1)

            self._record_stage(
                run=run,
                stage_name="census_persistence",
                status="succeeded",
                started_at=persist_stage_start,
                details_json={"rows_persisted": len(snapshots)},
            )

            # Update run status
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.failure_reason = ""
            run.timed_out = False
            run.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Census extraction complete. "
                    f"{len(snapshots)} rows persisted."
                )
            )

    # ------------------------------------------------------------------
    # Internal helpers (same contract as process_ingestion_runs)
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_failure_reason(exc: Exception) -> tuple[str, bool]:
        """Classify a subprocess exception into normalized failure taxonomy.

        Returns:
            (failure_reason, timed_out)
        """
        if isinstance(exc, SubprocessTimeoutError):
            return ("timeout", True)
        # Non-timeout subprocess errors (source unavailable from script)
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
        """Persist a stage metric record for the given run."""
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    def _mark_run_failed(self, run: IngestionRun, exc: Exception) -> None:
        """Transition run to failed with normalized failure fields."""
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        failure_reason, timed_out = self._classify_failure_reason(exc)
        run.failure_reason = failure_reason
        run.timed_out = timed_out
        run.save()
