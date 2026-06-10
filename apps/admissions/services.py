"""Services for processing admission records."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.historical_extraction import (
    ExtractionResult,
    create_stage_metric,
    mark_run_failed,
    mark_run_succeeded,
    resolve_source_credentials,
    safe_error_message,
)
from apps.ingestion.models import IngestionRun


def run_admission_extraction(
    *,
    start_date: str,
    end_date: str,
    headless: bool = True,
) -> ExtractionResult:
    """Execute admission extraction from the source system and persist records.

    This is the Python-callable service entry point for admission historical
    report extraction. It handles the full orchestration flow:

    1. Resolve and validate dates.
    2. Resolve source-system credentials.
    3. Create an ``IngestionRun`` for observability.
    4. Execute the Playwright automation script via subprocess.
    5. Parse the generated JSON output.
    6. Persist records via :func:`process_admissions`.
    7. Record stage metrics.
    8. Return a structured ``ExtractionResult``.

    Args:
        start_date: Start date in ``DD/MM/AAAA`` format.
        end_date: End date in ``DD/MM/AAAA`` format.
        headless: Whether to run Playwright in headless mode.

    Returns:
        An ``ExtractionResult`` describing the execution outcome.
    """
    # --- Resolve and validate dates ---
    try:
        ref_date = datetime.strptime(start_date, "%d/%m/%Y").date()
    except ValueError:
        return ExtractionResult(
            extraction_type="admission_extraction",
            target_start=Date(1, 1, 1),
            target_end=Date(1, 1, 1),
            success=False,
            failure_reason="validation_error",
            error_message=f"Invalid date format: {start_date}. Use DD/MM/AAAA.",
        )

    # --- Resolve credentials ---
    try:
        creds = resolve_source_credentials()
    except ValueError as exc:
        return ExtractionResult(
            extraction_type="admission_extraction",
            target_start=ref_date,
            target_end=ref_date,
            success=False,
            failure_reason="validation_error",
            error_message=str(exc),
        )

    # --- Create IngestionRun ---
    run = IngestionRun.objects.create(
        status="running",
        intent="admission_extraction",
        queued_at=timezone.now(),
        processing_started_at=timezone.now(),
        parameters_json={
            "start_date": start_date,
            "end_date": end_date,
            "ref_date": ref_date.isoformat(),
        },
    )

    # --- Resolve automation script path ---
    script_path = (
        Path(__file__).resolve().parents[2]
        / "automation"
        / "source_system"
        / "admissions"
        / "extract_admissions.py"
    )

    if not script_path.exists():
        err_msg = f"Automation script not found: {script_path}"
        mark_run_failed(run, error_message=err_msg, failure_reason="source_unavailable")
        create_stage_metric(
            run=run,
            stage_name="admission_extraction",
            status="failed",
            started_at=timezone.now(),
            details_json={"error": err_msg},
        )
        return ExtractionResult(
            extraction_type="admission_extraction",
            target_start=ref_date,
            target_end=ref_date,
            success=False,
            failure_reason="source_unavailable",
            error_message=err_msg,
            ingestion_run_id=run.pk,
        )

    # --- Stage: admission_extraction (subprocess) ---
    ext_stage_start = timezone.now()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir",
                str(tmpdir_path),
                "--source-url",
                creds.url,
                "--username",
                creds.username,
                "--password",
                creds.password,
                "--start-date",
                start_date,
                "--end-date",
                end_date,
            ]
            if headless:
                cmd.append("--headless")

            try:
                subprocess_result = run_subprocess(
                    cmd,
                    timeout=600,
                    check=False,
                )
            except SubprocessTimeoutError as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="admission_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"error": err_msg},
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="timeout",
                    timed_out=True,
                )
                return ExtractionResult(
                    extraction_type="admission_extraction",
                    target_start=ref_date,
                    target_end=ref_date,
                    success=False,
                    failure_reason="timeout",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="admission_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"error": err_msg},
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="unexpected_exception",
                )
                return ExtractionResult(
                    extraction_type="admission_extraction",
                    target_start=ref_date,
                    target_end=ref_date,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            if subprocess_result.returncode != 0:
                err_msg = safe_error_message(
                    subprocess_result.stderr[:500] if subprocess_result.stderr else "Unknown error"
                )
                create_stage_metric(
                    run=run,
                    stage_name="admission_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={"returncode": subprocess_result.returncode},
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="source_unavailable",
                )
                return ExtractionResult(
                    extraction_type="admission_extraction",
                    target_start=ref_date,
                    target_end=ref_date,
                    success=False,
                    failure_reason="source_unavailable",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="admission_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # --- Stage: admission_persistence (process JSON) ---
            persist_stage_start = timezone.now()

            json_files = sorted(
                tmpdir_path.glob("admissoes-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not json_files:
                # No admissions found — success, nothing to persist
                metrics: dict[str, Any] = {"total_records": 0}
                create_stage_metric(
                    run=run,
                    stage_name="admission_persistence",
                    status="succeeded",
                    started_at=persist_stage_start,
                    details_json=metrics,
                )
                mark_run_succeeded(run)

                from apps.admissions.models import DailyAdmissionCount

                DailyAdmissionCount.objects.update_or_create(
                    date=ref_date,
                    defaults={"count": 0, "raw_data": []},
                )

                return ExtractionResult(
                    extraction_type="admission_extraction",
                    target_start=ref_date,
                    target_end=ref_date,
                    success=True,
                    metrics=metrics,
                    ingestion_run_id=run.pk,
                )

            json_path = json_files[0]

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                records = data.get("records", [])

                metrics = process_admissions(records, reference_date=ref_date)
            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="admission_persistence",
                    status="failed",
                    started_at=persist_stage_start,
                    details_json={"error": err_msg},
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="unexpected_exception",
                )
                return ExtractionResult(
                    extraction_type="admission_extraction",
                    target_start=ref_date,
                    target_end=ref_date,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="admission_persistence",
                status="succeeded",
                started_at=persist_stage_start,
                details_json=metrics,
            )

            mark_run_succeeded(run)

            return ExtractionResult(
                extraction_type="admission_extraction",
                target_start=ref_date,
                target_end=ref_date,
                success=True,
                metrics=metrics,
                ingestion_run_id=run.pk,
            )

    except Exception as exc:
        err_msg = safe_error_message(str(exc))
        return ExtractionResult(
            extraction_type="admission_extraction",
            target_start=ref_date,
            target_end=ref_date,
            success=False,
            failure_reason="unexpected_exception",
            error_message=err_msg,
            ingestion_run_id=run.pk if "run" in dir() and run.pk else None,
        )


def process_admissions(
    records: list[dict[str, str | None]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process admission records from the XLS extraction.

    Persists both the daily aggregate and individual AdmissionRecord rows.

    Args:
        records: List of dicts with admission record data from the XLS.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.admissions.models import AdmissionRecord, DailyAdmissionCount

    daily_count, _created = DailyAdmissionCount.objects.update_or_create(
        date=reference_date,
        defaults={
            "count": len(records),
            "raw_data": records,
        },
    )

    # Delete old individual records and recreate
    daily_count.records.all().delete()

    for rec in records:
        prontuario = _find_value(rec, "PRONTUARIO", "prontuario", "Prontuário")
        nome = _find_value(rec, "NOME", "nome", "Paciente")
        data_internacao = _find_value(
            rec,
            "DATA INTERNACAO",
            "DATA_INTERNACAO",
            "DATA INTERNAÇÃO",
            "data_internacao",
            "Data Internação",
        )

        extra = {
            k: v
            for k, v in rec.items()
            if k
            not in {
                "PRONTUARIO",
                "NOME",
                "DATA INTERNACAO",
                "DATA_INTERNACAO",
                "DATA INTERNAÇÃO",
                "prontuario",
                "nome",
                "data_internacao",
                "Prontuário",
                "Paciente",
                "Data Internação",
            }
            and v
        }

        AdmissionRecord.objects.create(
            daily_count=daily_count,
            date=reference_date,
            prontuario=str(prontuario or ""),
            nome=str(nome or ""),
            data_internacao=str(data_internacao or ""),
            raw_extra=extra,
        )

    return {
        "total_records": len(records),
    }


def _find_value(record: dict, *keys: str) -> str | None:
    """Try multiple possible key names for a field (case-insensitive fallback)."""
    # Direct match first
    for key in keys:
        if key in record:
            return record[key]

    # Case-insensitive fallback
    for key in keys:
        for rk in record:
            if rk.upper().replace(" ", "_") == key.upper().replace(" ", "_"):
                return record[rk]

    return None
