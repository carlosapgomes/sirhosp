"""Discharge report extraction service.

Provides ``run_discharge_extraction`` — a Python-callable entry point for
discharge report extraction from the source system. Designed to be invoked
both by the ``extract_discharges`` management command and by future
deterministic historical recovery orchestrators.

Since RPSA-S2 this module:

- persists ``DischargeRecord`` evidence without writing the operational
  daily aggregate (decoupled report-batch storage);
- routes every persisted row through the canonical reconciliation
  boundary (``apps.patients.reconciliation`` via
  ``apps.discharges.services.reconcile_discharge_record``) using only
  ``saida_em``, never ``alta_em``.

Since RPSA-S7 this module also implements semantic confirmation of empty
reports: one empty/missing result is not success. The service runs at
most two independent attempts (each one subprocess invocation plus XLS
parse in a fresh temporary output directory). Two successful empty
attempts confirm a semantic zero; a failed confirmation stays failed
(``zero_unconfirmed``); a non-empty confirmation is processed normally.
The operational daily aggregate is refreshed via the
``refresh_daily_discharge_counts`` command exactly once, only after
evidence persistence and reconciliation complete on confirmed success.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.historical_extraction import (
    ExtractionResult,
    SourceCredentials,
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
    """Upsert ``DischargeRecord`` evidence rows (RPSA-S2).

    Evidence persistence is decoupled from the operational daily
    aggregate: this path never creates or updates it and never stores
    patient-bearing ``raw_data``. ``DischargeRecord`` rows are persisted
    with a null ``daily_count`` and are reconciled afterwards by
    :func:`_reconcile_persisted_records`.

    Args:
        patients: List of parsed patient dicts from XLS rows.
        ref_date: The reference date of the extraction report (metadata).

    Returns:
        A dict with ``total_records``, ``created``, ``updated``, and
        ``errors`` counters.
    """
    from apps.discharges.models import DischargeRecord  # noqa: PLC0415

    if not patients:
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
            DischargeRecord.objects.create(
                daily_count=None,
                alta_em=alta_em,
                saida_em=saida_em,
                prontuario=prontuario,
                nome=p["nome"],
                data_internacao=data_int,
                leito=p["leito"],
                especialidade=p["especialidade"],
            )
            created += 1

    return {
        "total_records": len([p for p in patients if p is not None]),
        "created": created,
        "updated": updated,
        "errors": parse_errors,
    }


def _reconcile_persisted_records(
    patients: list[dict[str, Any]],
) -> dict[str, int]:
    """Offer every persisted report row to canonical reconciliation.

    Calls the shared boundary
    (:func:`apps.discharges.services.reconcile_discharge_record`) instead
    of duplicating matching rules. Rows lacking ``saida_em`` stay
    pending. Returns one counter per reconciliation status, keyed as
    ``reconciliation_<status>``.
    """
    from apps.discharges.models import DischargeRecord  # noqa: PLC0415
    from apps.discharges.services import (  # noqa: PLC0415
        reconcile_discharge_record,
    )
    from apps.patients.models import RECONCILIATION_STATUSES  # noqa: PLC0415

    counters = {f"reconciliation_{s}": 0 for s in RECONCILIATION_STATUSES}

    for p in patients:
        if p is None:
            continue
        record = DischargeRecord.objects.filter(
            prontuario=p["prontuario"],
            data_internacao=p["data_internacao"],
        ).first()
        if record is None:
            continue
        status = reconcile_discharge_record(record=record)
        counters[f"reconciliation_{status}"] += 1

    return counters


# ---------------------------------------------------------------------------
# Single extraction attempt (RPSA-S7)
# ---------------------------------------------------------------------------


def _run_discharge_attempt(
    *,
    script_path: Path,
    creds: SourceCredentials,
    date: str,
    ref_date_iso: str,
    headless: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Run ONE independent extraction attempt and parse its XLS output.

    One attempt is exactly one subprocess invocation plus output parsing,
    executed in a fresh temporary output directory so the RPSA-S7
    confirmation is a genuinely independent observation. This function is
    called at most twice per service run and contains no retry loop.

    Returns:
        ``(patients, None)`` when the subprocess completed successfully
        (``patients`` may be empty — no XLS produced or zero parseable
        rows); ``([], failure)`` when the attempt failed, where
        ``failure`` is a structured, credential-safe dict with
        ``failure_reason``, ``error_message``, ``stage_details`` and
        ``timed_out`` keys.
    """
    safe_date = date.replace("/", "-")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        cmd = [
            sys.executable,
            str(script_path),
            "--output-dir",
            str(tmpdir_path),
            "--source-url",
            creds.url,
            "--date",
            date,
        ]
        cmd.extend(["--reference-date", ref_date_iso])
        if headless:
            cmd.append("--headless")

        # RPSA-S7A: credentials travel only in the scoped child
        # environment, never in argv (the command line is visible via
        # process inspection). Parent environment is never mutated.
        child_env = os.environ.copy()
        child_env["SOURCE_SYSTEM_USERNAME"] = creds.username
        child_env["SOURCE_SYSTEM_PASSWORD"] = creds.password

        try:
            subprocess_result = run_subprocess(
                cmd,
                timeout=600,
                check=False,
                env=child_env,
            )
        except SubprocessTimeoutError:
            err_msg = safe_error_message(
                "Source-system automation timed out."
            )
            return [], {
                "failure_reason": "timeout",
                "error_message": err_msg,
                "stage_details": {"error": err_msg},
                "timed_out": True,
            }
        except Exception as exc:
            err_msg = safe_error_message(str(exc))
            return [], {
                "failure_reason": "unexpected_exception",
                "error_message": err_msg,
                "stage_details": {"error": err_msg},
                "timed_out": False,
            }

        if subprocess_result.returncode != 0:
            err_msg = safe_error_message(
                subprocess_result.stderr[:500]
                if subprocess_result.stderr
                else "Unknown error"
            )
            return [], {
                "failure_reason": "source_unavailable",
                "error_message": err_msg,
                "stage_details": {"returncode": subprocess_result.returncode},
                "timed_out": False,
            }

        try:
            xls_files = sorted(
                tmpdir_path.glob(f"altas-{safe_date}-*.xlsx"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not xls_files:
                # Empty: the automation succeeded but produced no XLS.
                return [], None

            import openpyxl  # noqa: PLC0415

            wb = openpyxl.load_workbook(xls_files[0], read_only=True)
            ws = wb.active

            rows = list(ws.iter_rows(values_only=True))
            wb.close()
        except Exception as exc:
            err_msg = safe_error_message(str(exc))
            return [], {
                "failure_reason": "unexpected_exception",
                "error_message": err_msg,
                "stage_details": {"error": err_msg},
                "timed_out": False,
            }

        # Skip header row (first row)
        data_rows = rows[1:] if rows else []
        patients: list[dict[str, Any]] = []

        for row in data_rows:
            parsed = _parse_xls_row(row)
            if parsed is not None:
                patients.append(parsed)

        # Empty also covers an XLS with zero parseable rows.
        return patients, None


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
    4. Run ONE extraction attempt (subprocess plus parse). A failed first
       attempt keeps the existing failure semantics and is never
       confirmed by another invocation.
    5. When the first attempt is empty (no XLS or zero parseable rows),
       run exactly ONE independent confirmation attempt in a fresh
       output directory. Two successful empties confirm a semantic zero;
       a failed confirmation stays failed (``zero_unconfirmed``); a
       non-empty confirmation is processed normally.
    6. Persist evidence via :func:`_persist_discharge_records` and
       reconcile it via :func:`_reconcile_persisted_records` (RPSA-S2
       per-status counters) only after the semantic outcome is known.
    7. Record stage metrics carrying ``attempt_count``/``zero_confirmed``
       alongside the reconciliation counters.
    8. On confirmed success (rows or confirmed zero), refresh the
       operational daily aggregate exactly once via the
       ``refresh_daily_discharge_counts`` command, AFTER persistence and
       reconciliation. Failed or unconfirmed extractions never refresh.
    9. Return a structured ``ExtractionResult``.

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

    # --- Stage: discharge_extraction (subprocess + parse, RPSA-S7) -----
    ext_stage_start = timezone.now()

    try:
        # First attempt. A failed attempt keeps the existing failure
        # semantics and is never confirmed by a second invocation.
        patients, failure = _run_discharge_attempt(
            script_path=script_path,
            creds=creds,
            date=date,
            ref_date_iso=ref_date_iso,
            headless=headless,
        )

        attempt_count = 1
        zero_confirmed = False

        if failure is not None:
            create_stage_metric(
                run=run,
                stage_name="discharge_extraction",
                status="failed",
                started_at=ext_stage_start,
                details_json={
                    **failure["stage_details"],
                    "attempt_count": attempt_count,
                    "zero_confirmed": zero_confirmed,
                },
            )
            mark_run_failed(
                run,
                error_message=failure["error_message"],
                failure_reason=failure["failure_reason"],
                timed_out=failure["timed_out"],
            )
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=parsed_date,
                target_end=parsed_date,
                success=False,
                failure_reason=failure["failure_reason"],
                error_message=failure["error_message"],
                ingestion_run_id=run.pk,
                zero_confirmed=zero_confirmed,
                attempt_count=attempt_count,
            )

        if not patients:
            # RPSA-S7: one empty/missing report is not success. Prior
            # evidence stays untouched and nothing is persisted before the
            # semantic outcome is known. Exactly ONE independent
            # confirmation attempt follows (no retry loop, no third call).
            patients, failure = _run_discharge_attempt(
                script_path=script_path,
                creds=creds,
                date=date,
                ref_date_iso=ref_date_iso,
                headless=headless,
            )
            attempt_count = 2

            if failure is not None:
                # Unconfirmed zero: structured, credential-safe failure.
                # RPSA-S7 deferred P2 (landed in RPSA-S7A): propagate the
                # confirmation timeout to the run exactly like the
                # first-attempt timeout path.
                err_msg = safe_error_message(
                    "Zero-row discharge report could not be confirmed by "
                    "an independent second attempt."
                )
                create_stage_metric(
                    run=run,
                    stage_name="discharge_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={
                        "error": err_msg,
                        "confirmation_failure_reason": failure["failure_reason"],
                        "attempt_count": attempt_count,
                        "zero_confirmed": False,
                    },
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="zero_unconfirmed",
                    timed_out=failure["timed_out"],
                )
                return ExtractionResult(
                    extraction_type="discharge_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="zero_unconfirmed",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                    zero_confirmed=False,
                    attempt_count=attempt_count,
                )

            if not patients:
                # Two independent successful empty attempts: the zero is
                # semantically confirmed.
                zero_confirmed = True

        create_stage_metric(
            run=run,
            stage_name="discharge_extraction",
            status="succeeded",
            started_at=ext_stage_start,
            details_json={
                "attempt_count": attempt_count,
                "zero_confirmed": zero_confirmed,
            },
        )

        # --- Stage: discharge_persistence (upsert + reconcile + refresh) --
        persist_stage_start = timezone.now()

        try:
            metrics = _persist_discharge_records(
                patients, ref_date=ref_date,
            )
            # RPSA-S2: route persisted rows through the canonical
            # reconciliation boundary after evidence persistence.
            metrics.update(_reconcile_persisted_records(patients))
            metrics["zero_confirmed"] = zero_confirmed
            metrics["attempt_count"] = attempt_count
            # RPSA-S7: the aggregate refresh command is the only
            # extraction-triggered writer of the operational daily
            # aggregate. It runs exactly once per confirmed success —
            # rows or confirmed zero — AFTER evidence persistence and
            # reconciliation complete. Failed or unconfirmed extractions
            # never reach this point.
            call_command("refresh_daily_discharge_counts")
        except Exception as exc:
            err_msg = safe_error_message(str(exc))
            create_stage_metric(
                run=run,
                stage_name="discharge_persistence",
                status="failed",
                started_at=persist_stage_start,
                # RPSA-S7 deferred P2 (landed in RPSA-S7A): the
                # failure-stage metric carries the same attempt metadata
                # as the succeeded path.
                details_json={
                    "error": err_msg,
                    "attempt_count": attempt_count,
                    "zero_confirmed": zero_confirmed,
                },
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
                zero_confirmed=zero_confirmed,
                attempt_count=attempt_count,
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
            zero_confirmed=zero_confirmed,
            attempt_count=attempt_count,
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
