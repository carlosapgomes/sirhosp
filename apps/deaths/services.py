"""Services for processing death records."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from collections import Counter
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

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

if TYPE_CHECKING:
    from apps.deaths.models import DeathRecord  # noqa: F401

logger = logging.getLogger(__name__)

_TZ_DEATH_EVIDENCE = ZoneInfo("America/Bahia")
"""Institutional timezone for naive source death datetimes."""

_DEATH_DATETIME_FORMATS: tuple[tuple[str, bool], ...] = (
    ("%d/%m/%Y %H:%M:%S", True),
    ("%d/%m/%Y %H:%M", True),
    ("%d/%m/%Y", False),
)
"""Raw ``data_obito`` shapes; the boolean marks whether the source value
actually carries a time component."""


def run_death_extraction(
    *,
    start_date: str,
    end_date: str,
    headless: bool = True,
) -> ExtractionResult:
    """Execute death extraction from the source system and persist records.

    This is the Python-callable service entry point for death historical
    report extraction. It handles the full orchestration flow:

    1. Resolve and validate dates.
    2. Resolve source-system credentials.
    3. Create an ``IngestionRun`` for observability.
    4. Execute the Playwright automation script via subprocess.
    5. Parse the generated JSON output.
    6. Persist records via :func:`process_deaths`.
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
        parsed_start = datetime.strptime(start_date, "%d/%m/%Y").date()
        parsed_end = datetime.strptime(end_date, "%d/%m/%Y").date()
    except ValueError:
        return ExtractionResult(
            extraction_type="death_extraction",
            target_start=Date(1, 1, 1),
            target_end=Date(1, 1, 1),
            success=False,
            failure_reason="validation_error",
            error_message=f"Invalid date format: {start_date} / {end_date}. Use DD/MM/AAAA.",
        )

    ref_date = parsed_start

    # --- Resolve credentials ---
    try:
        creds = resolve_source_credentials()
    except ValueError as exc:
        return ExtractionResult(
            extraction_type="death_extraction",
            target_start=parsed_start,
            target_end=parsed_end,
            success=False,
            failure_reason="validation_error",
            error_message=str(exc),
        )

    # --- Create IngestionRun ---
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

    # --- Resolve automation script path ---
    script_path = (
        Path(__file__).resolve().parents[2]
        / "automation"
        / "source_system"
        / "deaths"
        / "extract_deaths.py"
    )

    if not script_path.exists():
        err_msg = f"Automation script not found: {script_path}"
        mark_run_failed(run, error_message=err_msg, failure_reason="source_unavailable")
        create_stage_metric(
            run=run,
            stage_name="death_extraction",
            status="failed",
            started_at=timezone.now(),
            details_json={"error": err_msg},
        )
        return ExtractionResult(
            extraction_type="death_extraction",
            target_start=parsed_start,
            target_end=parsed_end,
            success=False,
            failure_reason="source_unavailable",
            error_message=err_msg,
            ingestion_run_id=run.pk,
        )

    # --- Stage: death_extraction (subprocess) ---
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
                "--start-date",
                start_date,
                "--end-date",
                end_date,
            ]
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
                create_stage_metric(
                    run=run,
                    stage_name="death_extraction",
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
                    extraction_type="death_extraction",
                    target_start=parsed_start,
                    target_end=parsed_end,
                    success=False,
                    failure_reason="timeout",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="death_extraction",
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
                    extraction_type="death_extraction",
                    target_start=parsed_start,
                    target_end=parsed_end,
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
                    stage_name="death_extraction",
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
                    extraction_type="death_extraction",
                    target_start=parsed_start,
                    target_end=parsed_end,
                    success=False,
                    failure_reason="source_unavailable",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="death_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # --- Stage: death_persistence (process JSON) ---
            persist_stage_start = timezone.now()

            json_files = sorted(
                tmpdir_path.glob("obitos-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not json_files:
                # No deaths found — success, nothing to persist.
                # Call process_deaths with empty list to ensure any stale
                # DeathRecord rows for this date are also cleared.
                metrics = process_deaths([], reference_date=ref_date)
                create_stage_metric(
                    run=run,
                    stage_name="death_persistence",
                    status="succeeded",
                    started_at=persist_stage_start,
                    details_json=metrics,
                )
                mark_run_succeeded(run)

                return ExtractionResult(
                    extraction_type="death_extraction",
                    target_start=parsed_start,
                    target_end=parsed_end,
                    success=True,
                    metrics=metrics,
                    ingestion_run_id=run.pk,
                )

            json_path = json_files[0]

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                records = data.get("records", [])

                metrics = process_deaths(records, reference_date=ref_date)
            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="death_persistence",
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
                    extraction_type="death_extraction",
                    target_start=parsed_start,
                    target_end=parsed_end,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="death_persistence",
                status="succeeded",
                started_at=persist_stage_start,
                details_json=metrics,
            )

            mark_run_succeeded(run)

            return ExtractionResult(
                extraction_type="death_extraction",
                target_start=parsed_start,
                target_end=parsed_end,
                success=True,
                metrics=metrics,
                ingestion_run_id=run.pk,
            )

    except Exception as exc:
        err_msg = safe_error_message(str(exc))
        # If the run was already created, mark it as failed —
        # do not leave it stuck as 'running'.
        if "run" in dir() and run and run.pk:
            mark_run_failed(
                run,
                error_message=err_msg,
                failure_reason="unexpected_exception",
            )
        return ExtractionResult(
            extraction_type="death_extraction",
            target_start=parsed_start,
            target_end=parsed_end,
            success=False,
            failure_reason="unexpected_exception",
            error_message=err_msg,
            ingestion_run_id=run.pk if "run" in dir() and run and run.pk else None,
        )


def process_deaths(
    records: list[dict[str, str]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process death records from the CSV extraction (RPSA-S3 upsert).

    Persists the daily aggregate and offers every row to canonical death
    reconciliation through a stable-key upsert:

    - each snapshot row is upserted by ``(date, prontuario)``, so
      repeated extraction preserves the evidence primary key, the
      Admission link and the reconciliation state (never delete/recreate);
    - snapshot rows absent from a repeated extraction are retained as
      evidence but detached from the report-batch aggregate
      (``daily_count`` set to NULL), so the aggregate always reflects the
      latest snapshot;
    - no synthetic Patient/Admission is ever created; unresolved evidence
      requests bounded, deduplicated source synchronization instead.

    Args:
        records: List of dicts with death record data from the CSV.
        reference_date: The date these records refer to.

    Returns:
        A dict with ``total_records`` plus one ``reconciliation_<status>``
        counter per reconciliation status observed in this batch.
    """
    from apps.deaths.models import DailyDeathCount, DeathRecord

    with transaction.atomic():
        daily_count, _created = DailyDeathCount.objects.update_or_create(
            date=reference_date,
            defaults={
                "count": len(records),
                "raw_data": records,
            },
        )

        status_counts: Counter[str] = Counter()
        snapshot_pks: list[int] = []

        for rec in records:
            prontuario = str(_find_value(rec, "PRONTUARIO", "prontuario", "Prontuário") or "")
            nome = str(_find_value(rec, "NOME", "nome", "Paciente") or "")
            data_obito = str(
                _find_value(
                    rec,
                    "OBITO",
                    "DATA OBITO",
                    "DATA_OBITO",
                    "DATA ÓBITO",
                    "data_obito",
                    "Data Óbito",
                )
                or ""
            )

            extra = {
                k: v
                for k, v in rec.items()
                if k
                not in {
                    "PRONTUARIO",
                    "NOME",
                    "OBITO",
                    "DATA OBITO",
                    "DATA_OBITO",
                    "DATA ÓBITO",
                    "prontuario",
                    "nome",
                    "data_obito",
                    "Prontuário",
                    "Paciente",
                    "Data Óbito",
                }
                and v
            }

            record, _record_created = DeathRecord.objects.update_or_create(
                date=reference_date,
                prontuario=prontuario,
                defaults={
                    "nome": nome,
                    "data_obito": data_obito,
                    "raw_extra": extra,
                    "daily_count": daily_count,
                },
            )
            snapshot_pks.append(record.pk)

            status = reconcile_death_record(record=record)
            status_counts[status] += 1

        # Rows of this date that dropped out of the repeated snapshot are
        # detached from the report batch but survive as evidence (never
        # deleted) — their linkage and reconciliation state remain.
        DeathRecord.objects.filter(
            date=reference_date,
            daily_count__isnull=False,
        ).exclude(pk__in=snapshot_pks).update(daily_count=None)

    metrics: dict[str, int] = {"total_records": len(records)}
    for status, count in sorted(status_counts.items()):
        metrics[f"reconciliation_{status}"] = count
    return metrics


def _find_value(record: dict, *keys: str) -> str | None:
    """Try multiple possible key names for a field (case-insensitive fallback)."""
    for key in keys:
        if key in record:
            return record[key]

    for key in keys:
        norm = key.upper().replace(" ", "_")
        for rk in record:
            if rk.upper().replace(" ", "_") == norm:
                return record[rk]

    return None


def _parse_death_datetime(raw: str) -> datetime | None:
    """Parse the raw ``data_obito`` string without ever synthesizing an hour.

    Returns an aware ``America/Bahia`` datetime only when the source string
    carries a complete date AND time. Date-only or unparseable evidence
    yields ``None`` (reconciliation stays pending) — no hour of day is
    ever invented for evidence the source did not provide.
    """
    text = (raw or "").strip()
    for fmt, has_time in _DEATH_DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if not has_time:
            return None
        return timezone.make_aware(parsed, _TZ_DEATH_EVIDENCE)
    return None


def reconcile_death_record(
    *,
    record: DeathRecord,
    source_system: str = "tasy",
) -> str:
    """Offer one persisted ``DeathRecord`` to canonical reconciliation.

    Death evidence carries no admission key, no exact admission start and
    no local admission date: the only matching layer available is the
    unique canonical admission whose known period contains a complete
    death datetime (``match_by_period``). A date-only or unparseable
    ``data_obito`` never synthesizes an hour: the row stays pending and a
    deduplicated ``admissions_only`` source synchronization is requested.

    Evidence linkage/status is written in the same transaction as the
    admission mutation and the append-only audit. Logs carry
    aggregate-safe fields only (record primary key and status).

    Returns the final reconciliation status (one of
    ``apps.patients.models.RECONCILIATION_STATUSES``).
    """
    from apps.patients.models import (  # noqa: PLC0415
        EXIT_DEATH,
        RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
        RECONCILIATION_STATUS_ALREADY_RECONCILED,
        RECONCILIATION_STATUS_AMBIGUOUS,
        RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
        RECONCILIATION_STATUS_PENDING,
        RECONCILIATION_STATUS_RECONCILED,
    )
    from apps.patients.reconciliation import (  # noqa: PLC0415
        EVIDENCE_SOURCE_DEATH_RECORD,
        DischargeExitEvidence,
        apply_discharge_exit,
        decide_discharge_match,
    )

    exit_datetime = _parse_death_datetime(record.data_obito)
    record.obito_em = exit_datetime

    if exit_datetime is None:
        # Date-only (or unparseable) evidence: no source hour exists, so
        # none is synthesized. The row stays pending; the requested
        # admissions sync may restore a complete datetime on the source.
        record.reconciliation_status = RECONCILIATION_STATUS_PENDING
        record.save(update_fields=["obito_em", "reconciliation_status"])
        queued = _enqueue_missing_mirror_sync(
            record.prontuario,
            include_demographics=False,
        )
        logger.info(
            "death reconciliation pending (date-only evidence): "
            "record_id=%s status=%s admissions_sync_queued=%d",
            record.pk,
            RECONCILIATION_STATUS_PENDING,
            queued["admissions_only"],
        )
        return RECONCILIATION_STATUS_PENDING

    evidence = DischargeExitEvidence(
        patient_record=record.prontuario,
        exit_datetime=exit_datetime,
        admission_key=None,
        admission_start=None,
        admission_local_date=None,
        source_system=source_system,
        match_by_period=True,
    )

    with transaction.atomic():
        decision = decide_discharge_match(evidence=evidence)
        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=exit_datetime,
            exit_type=EXIT_DEATH,
            source_kind=EVIDENCE_SOURCE_DEATH_RECORD,
            source_id=record.pk,
        )
        # Evidence-side linkage/status joins the same atomic block so a
        # crash can never close an admission while leaving the evidence
        # row stale.
        record.admission = (
            decision.admission
            if status in (
                RECONCILIATION_STATUS_RECONCILED,
                RECONCILIATION_STATUS_ALREADY_RECONCILED,
            )
            else None
        )
        record.reconciliation_status = status
        record.reconciled_at = timezone.now()
        record.save(
            update_fields=[
                "admission",
                "reconciliation_status",
                "reconciled_at",
                "obito_em",
            ],
        )

    if status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND:
        queued = _enqueue_missing_mirror_sync(
            record.prontuario,
            include_demographics=True,
        )
    elif status in (
        RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
        RECONCILIATION_STATUS_AMBIGUOUS,
    ):
        queued = _enqueue_missing_mirror_sync(
            record.prontuario,
            include_demographics=False,
        )
    else:
        queued = {"admissions_only": 0, "demographics_only": 0}

    logger.info(
        "death reconciliation: record_id=%s status=%s "
        "admissions_sync_queued=%d demographics_sync_queued=%d",
        record.pk,
        status,
        queued["admissions_only"],
        queued["demographics_only"],
    )
    return status


def _enqueue_missing_mirror_sync(
    patient_record: str,
    *,
    include_demographics: bool,
) -> dict[str, int]:
    """Enqueue bounded, deduplicated source synchronization requests.

    Mirrors the discharge adapter policy: at most one active
    (queued/running) run per intent and patient record is kept, so
    repeated unresolved evidence cannot flood the ingestion queue. No
    synthetic Patient/Admission is ever created from evidence.
    """
    from apps.ingestion.services import (  # noqa: PLC0415
        queue_admissions_only_run,
        queue_demographics_only_run,
    )

    active_intents = set(
        IngestionRun.objects.filter(
            status__in=("queued", "running"),
            intent__in=("admissions_only", "demographics_only"),
            parameters_json__patient_record=patient_record,
        ).values_list("intent", flat=True)
    )

    queued = {"admissions_only": 0, "demographics_only": 0}
    if "admissions_only" not in active_intents:
        queue_admissions_only_run(patient_record=patient_record)
        queued["admissions_only"] = 1
    if include_demographics and "demographics_only" not in active_intents:
        queue_demographics_only_run(patient_record=patient_record)
        queued["demographics_only"] = 1
    return queued
