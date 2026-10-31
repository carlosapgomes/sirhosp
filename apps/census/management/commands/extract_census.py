from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.census.models import CensusSnapshot, OccupancyAgeBand
from apps.census.services import (
    CENSUS_EXTRACTION_SUMMARY_FILENAME,
    CensusExtractionSummaryError,
    CensusTransportError,
    load_census_extraction_summary,
    parse_census_csv,
    validate_census_completeness,
    validate_census_extraction_summary,
)
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


class CensusArtifactError(ValueError):
    """Canonical handoff artifact is missing or ambiguous."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _select_single_artifact(
    directory: Path,
    pattern: str,
    *,
    missing_reason: str,
    ambiguous_reason: str,
) -> Path:
    candidates = sorted(
        path for path in directory.glob(pattern) if path.is_file()
    )
    if not candidates:
        raise CensusArtifactError(missing_reason)
    if len(candidates) > 1:
        raise CensusArtifactError(ambiguous_reason)
    return candidates[0]



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
                "--csv-only",
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
                    timeout=4800,  # 80 minutes max (sistema fonte lento)
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
                err_msg = f"Exit code {result.returncode}."
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
                self.stderr.write(err_msg)
                sys.exit(1)

            self._record_stage(
                run=run,
                stage_name="census_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # -- Stage: census_persistence (artifacts + snapshot) ----------
            persist_stage_start = timezone.now()

            try:
                csv_path = _select_single_artifact(
                    tmpdir_path,
                    "censo-*.csv",
                    missing_reason="csv_missing",
                    ambiguous_reason="csv_ambiguous",
                )
                self.stdout.write(f"  CSV output: {csv_path.name}")
                summary_path = _select_single_artifact(
                    tmpdir_path,
                    CENSUS_EXTRACTION_SUMMARY_FILENAME,
                    missing_reason="summary_missing",
                    ambiguous_reason="summary_ambiguous",
                )
                summary = load_census_extraction_summary(summary_path)

                # Parse CSV and classify bed status
                parsed_rows = parse_census_csv(csv_path)
                self.stdout.write(f"  Rows parsed: {len(parsed_rows)}")

                validated_summary = validate_census_extraction_summary(
                    summary, parsed_rows
                )

                # -- Completeness gate (GCEC-S1) -----------------------
                completeness = validate_census_completeness(parsed_rows)
                if not completeness["accepted"]:
                    sector_count = completeness["sector_count"]
                    min_required = completeness["minimum_required_sectors"]
                    err_msg = (
                        f"Census extraction incomplete: {sector_count} sectors "
                        f"found, minimum required is {min_required}. "
                        f"No snapshots persisted."
                    )
                    self.stderr.write(err_msg)
                    self._record_stage(
                        run=run,
                        stage_name="census_persistence",
                        status="failed",
                        started_at=persist_stage_start,
                        details_json=completeness,
                    )
                    run.status = "failed"
                    run.error_message = err_msg
                    run.finished_at = timezone.now()
                    run.failure_reason = "invalid_payload"
                    run.timed_out = False
                    run.save()
                    sys.exit(1)

                # Bulk create CensusSnapshot rows
                captured_at = timezone.now()
                snapshots = [
                    CensusSnapshot(
                        captured_at=captured_at,
                        ingestion_run=run,
                        setor_codigo=row.get("setor_codigo", ""),
                        setor=row["setor"],
                        leito=row["leito"],
                        prontuario=row["prontuario"],
                        nome=row["nome"],
                        especialidade=row["especialidade"],
                        data_internacao=row.get("data_internacao", ""),
                        tempo_internacao=row.get("tempo_internacao"),
                        data_movimentacao=row.get("data_movimentacao", ""),
                        source_admission_at=row.get("source_admission_at"),
                        source_movement_at=row.get("source_movement_at"),
                        tipo_alta=row.get("tipo_alta", ""),
                        origem=row.get("origem", ""),
                        bed_status=row["bed_status"],
                        age_band=(
                            row.get("age_band") or OccupancyAgeBand.UNKNOWN
                        ),
                    )
                    for row in parsed_rows
                ]

                accepted_details = {
                    **completeness,
                    **validated_summary,
                    "rows_persisted": len(snapshots),
                }

                # The new snapshot set, its accepted metrics and the run
                # acceptance are promoted together: a failure after insertion
                # rolls back the whole new set.
                with transaction.atomic():
                    CensusSnapshot.objects.bulk_create(snapshots)
                    self._record_stage(
                        run=run,
                        stage_name="census_persistence",
                        status="succeeded",
                        started_at=persist_stage_start,
                        details_json=accepted_details,
                    )
                    run.status = "succeeded"
                    run.finished_at = timezone.now()
                    run.failure_reason = ""
                    run.timed_out = False
                    run.save()
                self.stdout.write(f"  Snapshots persisted: {len(snapshots)}")
            except (CensusExtractionSummaryError, CensusArtifactError) as exc:
                self._reject_persistence(
                    run=run,
                    started_at=persist_stage_start,
                    reason=exc.reason,
                    message=f"Census persistence rejected: {exc.reason}.",
                )
                sys.exit(1)
            except CensusTransportError as exc:
                self._reject_persistence(
                    run=run,
                    started_at=persist_stage_start,
                    reason="transport_validation_failed",
                    message=f"Census persistence failed: {exc}",
                )
                sys.exit(1)
            except Exception as exc:
                self._reject_persistence(
                    run=run,
                    started_at=persist_stage_start,
                    reason="persistence_failed",
                    message=(
                        "Census persistence failed "
                        f"({exc.__class__.__name__})."
                    ),
                    failure_reason="unexpected_exception",
                    error_type=exc.__class__.__name__,
                )
                sys.exit(1)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Census extraction complete. "
                    f"{len(snapshots)} rows persisted."
                )
            )

    # ------------------------------------------------------------------
    # Internal helpers (same contract as process_ingestion_runs)
    # ------------------------------------------------------------------

    def _reject_persistence(
        self,
        *,
        run: IngestionRun,
        started_at,
        reason: str,
        message: str,
        failure_reason: str = "invalid_payload",
        error_type: str | None = None,
    ) -> None:
        """Record a rejected handoff without persisting delivered values."""
        details: dict[str, str] = {"error": reason}
        if error_type:
            details["error_type"] = error_type
        self._record_stage(
            run=run,
            stage_name="census_persistence",
            status="failed",
            started_at=started_at,
            details_json=details,
        )
        run.status = "failed"
        run.error_message = message
        run.finished_at = timezone.now()
        run.failure_reason = failure_reason
        run.timed_out = False
        run.save()
        self.stderr.write(message)

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
