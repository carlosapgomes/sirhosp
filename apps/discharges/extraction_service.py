"""Discharge report extraction service.

Provides ``run_discharge_extraction`` — a Python-callable entry point for
discharge report extraction from the source system. Designed to be invoked
both by the ``extract_discharges`` management command and by future
deterministic historical recovery orchestrators.

This module is intentionally separate from ``apps/discharges/services.py``
to avoid coupling with or modifying the existing discharge reconciliation flow.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import transaction
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

__all__ = [
    "run_discharge_extraction",
]


# ---------------------------------------------------------------------------
# XLS row parsing helpers
# ---------------------------------------------------------------------------


def _parse_datetime(raw: str) -> datetime | None:
    """Parse 'DD/MM/YYYY HH:MM' or return None."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y %H:%M")
    except (ValueError, OverflowError):
        return None


def _make_aware(dt: datetime | None) -> datetime | None:
    """Convert a naive datetime to timezone-aware."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def _patient_for_raw(p: dict) -> dict:
    """Build a JSON-serializable copy of a patient dict."""
    d = dict(p)
    for key in ("alta_em", "saida_em"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    return d


def _parse_xls_row(
    row: tuple,
) -> dict[str, Any] | None:
    """Convert an openpyxl row tuple into a patient dict.

    Column layout (0-indexed, from the XLS):
      A(0): JSF internal ID   → ignored
      B(1): Prontuario         → float, convert to int → str
      C(2): Nome               → str
      D(3): Internacao         → DD/MM/YYYY
      E(4): Equipe             → ignored
      F(5): Esp                → str
      G(6): Alta Medica        → DD/MM/YYYY HH:MM or ''
      H(7): Local              → 'L:UN08H' or 'U:0 T'
      I(8): Saida              → DD/MM/YYYY HH:MM or ''
    """
    if len(row) < 9:
        return None

    pront_raw = row[1]
    nome = (row[2] or "").strip()
    data_int = (row[3] or "").strip()
    esp = (row[5] or "").strip()
    alta_str = (row[6] or "").strip()
    local_raw = (row[7] or "").strip()
    saida_str = (row[8] or "").strip()

    # Prontuario
    if pront_raw is None:
        return None
    try:
        prontuario = str(int(float(pront_raw)))
    except (ValueError, TypeError):
        prontuario = str(pront_raw).strip()

    if not prontuario:
        return None

    # Leito: remove "L:" prefix; "U:0 T" → empty
    leito = ""
    if local_raw.startswith("L:"):
        leito = local_raw[2:].strip()
    elif local_raw in ("U:0 T",):
        leito = ""  # unidade inteira, leito nao especificado

    # Datetime fields
    alta_em = _parse_datetime(alta_str)
    saida_em = _parse_datetime(saida_str)

    return {
        "prontuario": prontuario,
        "nome": nome,
        "data_internacao": data_int,
        "especialidade": esp,
        "leito": leito,
        "alta_em": alta_em,
        "saida_em": saida_em,
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


@transaction.atomic
def _persist_discharge_records(
    patients: list[dict[str, Any]],
    *,
    ref_date: Date,
) -> dict[str, int]:
    """Upsert ``DischargeRecord`` rows and update ``DailyDischargeCount``.

    Args:
        patients: List of parsed patient dicts from XLS rows.
        ref_date: The reference date for the ``DailyDischargeCount``.

    Returns:
        A dict with ``total_records``, ``created``, ``updated``, and
        ``errors`` counters.
    """
    from apps.discharges.models import DailyDischargeCount, DischargeRecord  # noqa: PLC0415

    # When patients list is empty, record zero-count for ref_date
    if not patients:
        DailyDischargeCount.objects.update_or_create(
            date=ref_date,
            defaults={"count": 0, "raw_data": []},
        )
        return {
            "total_records": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

    created = 0
    updated = 0
    parse_errors = 0

    for p in patients:
        if p is None:
            parse_errors += 1
            continue

        prontuario = p["prontuario"]
        data_int = p["data_internacao"]

        existing = DischargeRecord.objects.filter(
            prontuario=prontuario,
            data_internacao=data_int,
        ).first()

        alta_em = _make_aware(p["alta_em"])
        saida_em = _make_aware(p["saida_em"])

        if existing:
            changed = False
            for field, new_val in (
                ("alta_em", alta_em),
                ("saida_em", saida_em),
                ("leito", p["leito"]),
                ("especialidade", p["especialidade"]),
                ("nome", p["nome"]),
            ):
                old_val = getattr(existing, field)
                if new_val is not None and new_val != old_val:
                    setattr(existing, field, new_val)
                    changed = True
            if changed:
                existing.save()
                updated += 1
        else:
            count_date = alta_em.date() if alta_em else ref_date
            daily_count, _ = DailyDischargeCount.objects.get_or_create(
                date=count_date,
                defaults={"count": 0, "raw_data": []},
            )
            DischargeRecord.objects.create(
                daily_count=daily_count,
                alta_em=alta_em,
                saida_em=saida_em,
                prontuario=prontuario,
                nome=p["nome"],
                data_internacao=data_int,
                leito=p["leito"],
                especialidade=p["especialidade"],
            )
            created += 1

    # Persist DailyDischargeCount with JSON-serializable raw_data
    raw_patients = [_patient_for_raw(p) for p in patients if p is not None]
    DailyDischargeCount.objects.update_or_create(
        date=ref_date,
        defaults={
            "count": len(raw_patients),
            "raw_data": raw_patients,
        },
    )

    return {
        "total_records": len(raw_patients),
        "created": created,
        "updated": updated,
        "errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Service entry point
# ---------------------------------------------------------------------------


def run_discharge_extraction(
    *,
    date: str,
    headless: bool = True,
) -> ExtractionResult:
    """Execute discharge report extraction from the source system and persist records.

    This is the Python-callable service entry point for discharge historical
    report extraction. It handles the full orchestration flow:

    1. Resolve and validate the target date.
    2. Resolve source-system credentials.
    3. Create an ``IngestionRun`` for observability.
    4. Execute the Playwright automation script via subprocess.
    5. Parse the generated XLS output.
    6. Persist records via :func:`_persist_discharge_records`.
    7. Record stage metrics.
    8. Return a structured ``ExtractionResult``.

    Args:
        date: Target date in ``DD/MM/AAAA`` format.
        headless: Whether to run Playwright in headless mode.

    Returns:
        An ``ExtractionResult`` describing the execution outcome.
    """
    # --- Resolve and validate date ---
    try:
        parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        return ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=Date(1, 1, 1),
            target_end=Date(1, 1, 1),
            success=False,
            failure_reason="validation_error",
            error_message=f"Invalid date format: {date}. Use DD/MM/AAAA.",
        )

    ref_date = parsed_date
    safe_date = date.replace("/", "-")
    ref_date_iso = ref_date.isoformat()

    # --- Resolve credentials ---
    try:
        creds = resolve_source_credentials()
    except ValueError as exc:
        return ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="validation_error",
            error_message=str(exc),
        )

    # --- Create IngestionRun ---
    run = IngestionRun.objects.create(
        status="running",
        intent="discharge_extraction",
        queued_at=timezone.now(),
        processing_started_at=timezone.now(),
        parameters_json={
            "date": date,
            "ref_date": ref_date_iso,
        },
    )

    # --- Resolve automation script path ---
    script_path = (
        Path(__file__).resolve().parents[2]
        / "automation"
        / "source_system"
        / "discharges"
        / "extract_discharges.py"
    )

    if not script_path.exists():
        err_msg = f"Automation script not found: {script_path}"
        mark_run_failed(
            run, error_message=err_msg, failure_reason="source_unavailable"
        )
        create_stage_metric(
            run=run,
            stage_name="discharge_extraction",
            status="failed",
            started_at=timezone.now(),
            details_json={"error": err_msg},
        )
        return ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="source_unavailable",
            error_message=err_msg,
            ingestion_run_id=run.pk,
        )

    # --- Stage: discharge_extraction (subprocess) ---
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
                "--date",
                date,
            ]
            cmd.extend(["--reference-date", ref_date_iso])
            if headless:
                cmd.append("--headless")

            try:
                subprocess_result = run_subprocess(
                    cmd,
                    timeout=600,
                    check=False,
                )
            except SubprocessTimeoutError:
                err_msg = safe_error_message(
                    "Source-system automation timed out."
                )
                create_stage_metric(
                    run=run,
                    stage_name="discharge_extraction",
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
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="timeout",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="discharge_extraction",
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
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            if subprocess_result.returncode != 0:
                err_msg = safe_error_message(
                    subprocess_result.stderr[:500]
                    if subprocess_result.stderr
                    else "Unknown error"
                )
                create_stage_metric(
                    run=run,
                    stage_name="discharge_extraction",
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
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="source_unavailable",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="discharge_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # --- Stage: discharge_persistence (XLS parse + upsert) ---
            persist_stage_start = timezone.now()

            xls_files = sorted(
                tmpdir_path.glob(f"altas-{safe_date}-*.xlsx"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not xls_files:
                metrics = {
                    "total_records": 0,
                    "created": 0,
                    "updated": 0,
                    "errors": 0,
                }
                create_stage_metric(
                    run=run,
                    stage_name="discharge_persistence",
                    status="succeeded",
                    started_at=persist_stage_start,
                    details_json=metrics,
                )
                mark_run_succeeded(run)
                # Ensure DailyDischargeCount exists for this date with zero count
                from apps.discharges.models import DailyDischargeCount as _DDC  # noqa: PLC0415
                _DDC.objects.update_or_create(
                    date=ref_date,
                    defaults={"count": 0, "raw_data": []},
                )
                return ExtractionResult(
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=True,
                    metrics=metrics,
                    ingestion_run_id=run.pk,
                )

            xls_path = xls_files[0]

            try:
                import openpyxl  # noqa: PLC0415

                wb = openpyxl.load_workbook(xls_path, read_only=True)
                ws = wb.active

                rows = list(ws.iter_rows(values_only=True))
                wb.close()

                if not rows:
                    metrics = {
                        "total_records": 0,
                        "created": 0,
                        "updated": 0,
                        "errors": 0,
                    }
                    create_stage_metric(
                        run=run,
                        stage_name="discharge_persistence",
                        status="succeeded",
                        started_at=persist_stage_start,
                        details_json=metrics,
                    )
                    mark_run_succeeded(run)
                    from apps.discharges.models import DailyDischargeCount as _DDC  # noqa: PLC0415
                    _DDC.objects.update_or_create(
                        date=ref_date,
                        defaults={"count": 0, "raw_data": []},
                    )
                    return ExtractionResult(
                        extraction_type="discharge_extraction",
                        target_start=parsed_date,
                        target_end=parsed_date,
                        success=True,
                        metrics=metrics,
                        ingestion_run_id=run.pk,
                    )

                # Skip header row (first row)
                data_rows = rows[1:] if rows else []
                patients: list[dict[str, Any]] = []

                for row in data_rows:
                    parsed = _parse_xls_row(row)
                    if parsed is not None:
                        patients.append(parsed)

                metrics = _persist_discharge_records(
                    patients, ref_date=ref_date,
                )

            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="discharge_persistence",
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
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="discharge_persistence",
                status="succeeded",
                started_at=persist_stage_start,
                details_json=metrics,
            )

            mark_run_succeeded(run)

            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=parsed_date,
                target_end=parsed_date,
                success=True,
                metrics=metrics,
                ingestion_run_id=run.pk,
            )

    except Exception as exc:
        err_msg = safe_error_message(str(exc))
        if run and run.pk:
            mark_run_failed(
                run,
                error_message=err_msg,
                failure_reason="unexpected_exception",
            )
        return ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="unexpected_exception",
            error_message=err_msg,
            ingestion_run_id=run.pk if run and run.pk else None,
        )
