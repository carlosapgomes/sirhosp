from __future__ import annotations

import csv
import json
import logging
import re
import sys
import tempfile
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, OfficialCensusRecord, PatientMovement
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
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.ingestion.services import (
    queue_admissions_only_run,
    queue_demographics_only_run,
)
from apps.patients.models import Admission, Patient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Completeness gate constants and helpers (GCEC-S1)
# ---------------------------------------------------------------------------

MINIMUM_CENSUS_SECTORS: int = 40
"""Minimum distinct non-empty sectors required for a valid census extraction."""


def validate_census_completeness(
    parsed_rows: list[dict],
) -> dict:
    """Validate census CSV parsed rows have sufficient sector coverage.

    Counts distinct non-empty sectors in the parsed rows and compares
    against ``MINIMUM_CENSUS_SECTORS``.

    Args:
        parsed_rows: Output from :func:`parse_census_csv`.

    Returns:
        A dict with:
        - ``accepted``: True if sector count >= minimum.
        - ``sector_count``: Number of distinct non-empty sectors.
        - ``row_count``: Total parsed rows.
        - ``minimum_required_sectors``: The threshold used.
        - ``completeness_status``: ``"accepted"`` or ``"rejected"``.
    """
    distinct_sectors: set[str] = set()
    for row in parsed_rows:
        sector = (row.get("setor") or "").strip()
        if sector:
            distinct_sectors.add(sector)

    sector_count = len(distinct_sectors)
    row_count = len(parsed_rows)
    accepted = sector_count >= MINIMUM_CENSUS_SECTORS

    return {
        "accepted": accepted,
        "sector_count": sector_count,
        "row_count": row_count,
        "minimum_required_sectors": MINIMUM_CENSUS_SECTORS,
        "completeness_status": "accepted" if accepted else "rejected",
    }



def classify_bed_status(prontuario: str, nome: str) -> str:
    """Classify bed status from census row data.

    Rules (in priority order):
    1. prontuario non-empty → OCCUPIED
    2. prontuario empty → classify by nome

    Args:
        prontuario: Patient record number (may be empty).
        nome: Patient name or bed status label.

    Returns:
        One of BedStatus values.
    """
    # Rule 1: prontuario present → occupied
    if prontuario and prontuario.strip():
        return BedStatus.OCCUPIED

    # Rule 2: classify by nome (case-insensitive)
    nome_upper = nome.strip().upper()

    if any(term in nome_upper for term in ["DESOCUPADO", "VAZIO"]):
        return BedStatus.EMPTY

    if "LIMPEZA" in nome_upper:
        return BedStatus.MAINTENANCE

    if "RESERVA" in nome_upper:
        return BedStatus.RESERVED

    if "ISOLAMENTO" in nome_upper:
        return BedStatus.ISOLATION

    # Fallback: empty bed (unknown non-patient label)
    return BedStatus.EMPTY


def _sync_admission_ward_bed(
    patient: Patient,
    setor: str,
    leito: str,
) -> None:
    """Sync ward/bed from census data to the most recent active admission.

    The census is the authoritative source for a patient's current location.
    This updates the Admission model so the patient page can display the
    sector even before admissions are fully extracted from the source system.

    Args:
        patient: Patient whose admission may be updated.
        setor: Ward/sector name from the census (may be empty).
        leito: Bed identifier from the census (may be empty).
    """
    if not setor and not leito:
        return

    # Find most recent admission without discharge date
    active = (
        Admission.objects.filter(
            patient=patient,
            discharge_date__isnull=True,
        )
        .order_by("-admission_date")
        .first()
    )

    if active is None:
        return

    changed = False
    if setor and active.ward != setor:
        active.ward = setor
        changed = True
    if leito and active.bed != leito:
        active.bed = leito
        changed = True

    if changed:
        active.save(update_fields=["ward", "bed", "updated_at"])


def _parse_dt_int(raw: str) -> str:
    """Parse admission date from DD/MM format, inferring the year.

    Rule:
    - If the date (with current year) is in the future, assume previous year.
    - Otherwise use current year.
    - If already DD/MM/AAAA, return as-is.

    Returns a normalized string in DD/MM/AAAA format (or empty on failure).
    """
    from datetime import date as date_mod

    raw = (raw or "").strip()
    if not raw:
        return ""

    # Already full format?
    if re.match(r"^\d{2}/\d{2}/\d{4}$", raw):
        return raw

    # Expect DD/MM
    m = re.match(r"^(\d{2})/(\d{2})$", raw)
    if not m:
        return raw  # keep as-is if unrecognized

    day, month = int(m.group(1)), int(m.group(2))
    today = date_mod.today()
    year = today.year

    try:
        parsed = date_mod(year, month, day)
    except ValueError:
        return raw

    if parsed > today:
        # Future date → use previous year
        parsed = date_mod(year - 1, month, day)

    return parsed.strftime("%d/%m/%Y")


def parse_census_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Parse a census CSV file and classify bed status for each row.

    Args:
        csv_path: Path to CSV file with columns:
            setor, qrt_leito, prontuario, nome, esp
            plus optional: dt_int, tempo, idade, convenio

    Returns:
        List of dicts with keys:
            setor, leito, prontuario, nome, especialidade, bed_status,
            data_internacao (str DD/MM/AAAA), tempo_internacao (int or None)

    Raises:
        FileNotFoundError: If csv_path does not exist.
        ValueError: If CSV is missing required columns.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Census CSV not found: {csv_path}")

    rows: list[dict[str, Any]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Validate columns
        expected = {"setor", "qrt_leito", "prontuario", "nome", "esp"}
        actual = set(reader.fieldnames or [])
        if not expected.issubset(actual):
            missing = expected - actual
            raise ValueError(
                f"CSV missing required columns: {missing}. "
                f"Found: {actual}"
            )

        has_setor_codigo = "setor_codigo" in actual
        has_dt_int = "dt_int" in actual
        has_tempo = "tempo" in actual
        has_dt_mvt = "dt_mvt" in actual
        has_alta = "alta" in actual
        has_origem = "origem" in actual

        for row in reader:
            prontuario = (row.get("prontuario") or "").strip()
            nome = (row.get("nome") or "").strip()
            bed_status = classify_bed_status(prontuario, nome)

            dt_int_raw = (row.get("dt_int") or "").strip() if has_dt_int else ""
            data_internacao = _parse_dt_int(dt_int_raw)

            tempo_raw = (row.get("tempo") or "").strip() if has_tempo else ""
            tempo_internacao = None
            if tempo_raw:
                try:
                    tempo_internacao = int(float(tempo_raw))
                except (ValueError, TypeError):
                    pass

            rows.append(
                {
                    "setor_codigo": (row.get("setor_codigo") or "").strip()
                    if has_setor_codigo
                    else "",
                    "setor": (row.get("setor") or "").strip(),
                    "leito": (row.get("qrt_leito") or "").strip(),
                    "prontuario": prontuario,
                    "nome": nome,
                    "especialidade": (row.get("esp") or "").strip(),
                    "data_internacao": data_internacao,
                    "tempo_internacao": tempo_internacao,
                    "bed_status": bed_status,
                    "data_movimentacao": (
                        (row.get("dt_mvt") or "").strip()
                        if has_dt_mvt
                        else ""
                    ),
                    "tipo_alta": (
                        (row.get("alta") or "").strip()
                        if has_alta
                        else ""
                    ),
                    "origem": (
                        (row.get("origem") or "").strip()
                        if has_origem
                        else ""
                    ),
                }
            )

    return rows


def process_census_snapshot(
    run_id: int | None = None,
) -> dict[str, int | None]:
    """Process the most recent census snapshot and enqueue patient sync runs.

    For each occupied bed with a prontuario, creates or updates the
    corresponding Patient record and enqueues both admissions-only
    and demographics-only ingestion runs.

    Creates a CensusExecutionBatch to group all runs from this cycle.
    If no patients are found to process, no batch is created.

    Args:
        run_id: Optional IngestionRun ID to process a specific census run.
            If None, processes the most recent captured_at.

    Returns:
        Dict with metrics:
            batch_id: CensusExecutionBatch pk (None if no batch created)
            patients_total: Total unique prontuarios processed
            patients_new: Patients created (not previously in DB)
            patients_updated: Patients whose name was updated
            runs_enqueued: Admissions ingestion runs created
            demographics_runs_enqueued: Demographics ingestion runs created
            patients_skipped: Patients skipped (e.g., no prontuario)
    """
    # Determine which census run to process
    if run_id is not None:
        snapshots = CensusSnapshot.objects.filter(ingestion_run_id=run_id)
    else:
        latest_captured = CensusSnapshot.objects.aggregate(
            latest=Max("captured_at")
        )["latest"]
        if latest_captured is None:
            return {
                "batch_id": None,
                "patients_total": 0,
                "patients_new": 0,
                "patients_updated": 0,
                "runs_enqueued": 0,
                "demographics_runs_enqueued": 0,
                "patients_skipped": 0,
                "patients_skipped_no_pront": 0,
                "patients_skipped_duplicate": 0,
            }
        snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    # Filter only occupied beds
    occupied = snapshots.filter(bed_status=BedStatus.OCCUPIED)

    # Deduplicate by prontuario — prefer entry with non-empty especialidade
    patients_dict: dict[str, dict[str, str]] = {}
    patients_esp: dict[str, str] = {}  # best especialidade per prontuario
    no_pront_skipped = 0
    dup_skipped = 0

    for snap in occupied.order_by("-pk"):  # latest first
        pront = snap.prontuario.strip()
        if not pront:
            no_pront_skipped += 1
            continue

        esp = snap.especialidade.strip()
        entry = {
            "prontuario": pront,
            "nome": snap.nome.strip(),
            "setor": snap.setor,
            "leito": snap.leito,
        }

        if pront in patients_dict:
            # Duplicate — prefer entry with non-empty especialidade
            if esp and not patients_esp.get(pront, ""):
                patients_dict[pront] = entry
                patients_esp[pront] = esp
            dup_skipped += 1
        else:
            patients_dict[pront] = entry
            patients_esp[pront] = esp

    patients_to_process = list(patients_dict.values())

    # No occupied beds with prontuario → no batch needed
    if not patients_to_process:
        return {
            "batch_id": None,
            "patients_total": 0,
            "patients_new": 0,
            "patients_updated": 0,
            "runs_enqueued": 0,
            "demographics_runs_enqueued": 0,
            "patients_skipped": no_pront_skipped + dup_skipped,
            "patients_skipped_no_pront": no_pront_skipped,
            "patients_skipped_duplicate": dup_skipped,
        }

    # Create execution batch for this census cycle
    batch = CensusExecutionBatch.objects.create(
        status="running",
        notes_json={
            "patients_total": len(patients_to_process),
        },
    )

    new_count = 0
    updated_count = 0
    enqueued_count = 0

    for entry in patients_to_process:
        prontuario = entry["prontuario"]
        nome = entry["nome"]
        setor = entry["setor"]
        leito = entry["leito"]

        # Create or get patient
        patient, created = Patient.objects.get_or_create(
            source_system="tasy",
            patient_source_key=prontuario,
            defaults={"name": nome},
        )

        if created:
            new_count += 1
        elif nome and patient.name != nome:
            # Update name if changed
            patient.name = nome
            patient.save(update_fields=["name", "updated_at"])
            updated_count += 1

        # Sync ward/bed from census to the most recent active admission
        _sync_admission_ward_bed(patient, setor, leito)

        # Enqueue admissions-only run for this patient
        queue_admissions_only_run(patient_record=prontuario, batch=batch)
        enqueued_count += 1

        # Enqueue demographics-only run for this patient
        queue_demographics_only_run(patient_record=prontuario, batch=batch)

    total_skipped = no_pront_skipped + dup_skipped

    # Mark enqueue phase as complete
    batch.enqueue_finished_at = timezone.now()
    batch.notes_json = {
        **batch.notes_json,
        "runs_enqueued": enqueued_count,
        "demographics_runs_enqueued": len(patients_to_process),
        "patients_skipped": total_skipped,
        "patients_skipped_no_pront": no_pront_skipped,
        "patients_skipped_duplicate": dup_skipped,
    }
    batch.save(update_fields=["enqueue_finished_at", "notes_json"])

    return {
        "batch_id": batch.pk,
        "patients_total": len(patients_to_process),
        "patients_new": new_count,
        "patients_updated": updated_count,
        "runs_enqueued": enqueued_count,
        "demographics_runs_enqueued": len(patients_to_process),
        "patients_skipped": total_skipped,
        "patients_skipped_no_pront": no_pront_skipped,
        "patients_skipped_duplicate": dup_skipped,
    }


# ---------------------------------------------------------------------------
# PatientMovement upsert
# ---------------------------------------------------------------------------


def _recalc_sequences(patient: Patient) -> None:
    """Recalculate sequence numbers for all movements of a patient.

    Orders by movement_date, first_seen_at, pk and assigns sequential
    sequence values starting from 0.
    """
    movements = PatientMovement.objects.filter(
        patient=patient,
    ).order_by("movement_date", "first_seen_at", "pk")
    for i, m in enumerate(movements):
        if m.sequence != i:
            m.sequence = i
            m.save(update_fields=["sequence"])


def upsert_patient_movements() -> dict:
    """Upsert PatientMovement records from the latest census snapshot.

    Processes the most recent CensusSnapshot (by captured_at), filtering
    only occupied beds with a non-empty prontuario. For each patient,
    creates or updates a PatientMovement based on the unique key
    (patient, movement_date, sector).

    Returns:
        dict with keys: movements_created, movements_updated,
        patients_processed, errors
    """
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at"),
    )["latest"]
    if latest_captured is None:
        return {
            "movements_created": 0,
            "movements_updated": 0,
            "patients_processed": 0,
            "errors": 0,
        }

    snapshots = CensusSnapshot.objects.filter(
        captured_at=latest_captured,
        bed_status=BedStatus.OCCUPIED,
    )

    now = timezone.now()
    movements_created = 0
    movements_updated = 0
    patients_processed = 0
    errors = 0
    touched_patients: set[int] = set()

    for snap in snapshots:
        pront = snap.prontuario.strip()
        if not pront:
            continue

        # Parse movement_date from data_movimentacao
        raw_date = _parse_dt_int(snap.data_movimentacao)
        if not raw_date:
            logger.warning(
                "Skipping patient prontuario=%s: empty data_movimentacao",
                pront,
            )
            continue

        try:
            movement_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        except (ValueError, TypeError):
            logger.warning(
                "Skipping patient prontuario=%s: invalid data_movimentacao='%s'",
                pront,
                raw_date,
            )
            errors += 1
            continue

        # Get or create Patient
        patient, _ = Patient.objects.get_or_create(
            source_system="tasy",
            patient_source_key=pront,
            defaults={"name": snap.nome.strip()},
        )

        # Find active admission (best-effort)
        active_admission = (
            Admission.objects.filter(
                patient=patient,
                discharge_date__isnull=True,
            )
            .order_by("-admission_date")
            .first()
        )

        # Upsert PatientMovement
        movement, created = PatientMovement.objects.get_or_create(
            patient=patient,
            movement_date=movement_date,
            sector=snap.setor.strip(),
            defaults={
                "admission": active_admission,
                "origin": snap.origem.strip(),
                "bed": snap.leito.strip(),
                "discharge_type": snap.tipo_alta.strip(),
                "first_seen_at": now,
                "last_seen_at": now,
            },
        )

        if created:
            movements_created += 1
        else:
            movement.last_seen_at = now
            movement.save(update_fields=["last_seen_at"])
            movements_updated += 1

        touched_patients.add(patient.pk)

    # Recalculate sequences for all touched patients
    for patient_pk in touched_patients:
        _recalc_sequences(Patient.objects.get(pk=patient_pk))

    patients_processed = len(touched_patients)

    return {
        "movements_created": movements_created,
        "movements_updated": movements_updated,
        "patients_processed": patients_processed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Ward/Bed registry parser
# ---------------------------------------------------------------------------


def parse_wards_beds_pdf_text(pdf_text):
    """Parse ward/bed catalog PDF text into a list of unit dicts.

    Each dict: {source_code, name, beds: [{code, status, accommodation,
    is_active}]}

    Strategy: split the text by "Unidade" markers, then parse each block.
    """
    HEADER = ('Leito', 'Status', 'Acomodação', 'Ativo')

    # Split into blocks: each "Unidade" starts a new unit
    raw_blocks = pdf_text.split('Unidade')
    units = []

    for block in raw_blocks:
        block_lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not block_lines:
            continue

        # First line is the code (e.g. "640")
        code = block_lines[0]
        if not code.isdigit() or len(code) > 6:
            continue

        # Find unit name: scan until header
        name = ''
        header_idx = None
        for j in range(1, len(block_lines)):
            if block_lines[j] in HEADER:
                header_idx = j
                break
            name = block_lines[j]

        if header_idx is None:
            continue

        # Collect bed values from after header (skip 4 header lines) until Total
        bed_values = []
        for j in range(header_idx + 4, len(block_lines)):
            line = block_lines[j]
            if line == 'Total':
                break
            bed_values.append(line)

        # Every 4 lines = one bed
        beds = []
        for i in range(0, len(bed_values), 4):
            if i + 3 < len(bed_values):
                beds.append({
                    'code': bed_values[i],
                    'status': bed_values[i + 1],
                    'accommodation': bed_values[i + 2],
                    'is_active': bed_values[i + 3] == 'A',
                })

        units.append({
            'source_code': code,
            'name': name,
            'beds': beds,
        })

    return units


# ---------------------------------------------------------------------------
# Official census extraction service
# ---------------------------------------------------------------------------


def run_official_census_extraction(
    *,
    date: str,
    headless: bool = True,
) -> ExtractionResult:
    """Execute official daily census extraction from the source system and persist records.

    This is the Python-callable service entry point for official census
    historical report extraction. It handles the full orchestration flow:

    1. Resolve and validate the target date.
    2. Resolve source-system credentials.
    3. Create an ``IngestionRun`` for observability.
    4. Execute the Playwright automation script via subprocess.
    5. Parse the generated JSON output.
    6. Persist records via :func:`process_official_census_records`.
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
            extraction_type="official_census_extraction",
            target_start=Date(1, 1, 1),
            target_end=Date(1, 1, 1),
            success=False,
            failure_reason="validation_error",
            error_message=f"Invalid date format: {date}. Use DD/MM/AAAA.",
        )

    ref_date = parsed_date

    # --- Resolve credentials ---
    try:
        creds = resolve_source_credentials()
    except ValueError as exc:
        return ExtractionResult(
            extraction_type="official_census_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="validation_error",
            error_message=str(exc),
        )

    # --- Create IngestionRun ---
    run = IngestionRun.objects.create(
        status="running",
        intent="official_census_extraction",
        queued_at=timezone.now(),
        processing_started_at=timezone.now(),
        parameters_json={
            "date": date,
            "ref_date": ref_date.isoformat(),
        },
    )

    # --- Resolve automation script path ---
    script_path = (
        Path(__file__).resolve().parents[2]
        / "automation"
        / "source_system"
        / "official_census"
        / "extract_official_census.py"
    )

    if not script_path.exists():
        err_msg = f"Automation script not found: {script_path}"
        mark_run_failed(
            run, error_message=err_msg, failure_reason="source_unavailable"
        )
        create_stage_metric(
            run=run,
            stage_name="official_census_extraction",
            status="failed",
            started_at=timezone.now(),
            details_json={"error": err_msg},
        )
        return ExtractionResult(
            extraction_type="official_census_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="source_unavailable",
            error_message=err_msg,
            ingestion_run_id=run.pk,
        )

    # --- Stage: official_census_extraction (subprocess) ---
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
                    stage_name="official_census_extraction",
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
                    extraction_type="official_census_extraction",
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
                    stage_name="official_census_extraction",
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
                    extraction_type="official_census_extraction",
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
                    stage_name="official_census_extraction",
                    status="failed",
                    started_at=ext_stage_start,
                    details_json={
                        "returncode": subprocess_result.returncode
                    },
                )
                mark_run_failed(
                    run,
                    error_message=err_msg,
                    failure_reason="source_unavailable",
                )
                return ExtractionResult(
                    extraction_type="official_census_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="source_unavailable",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="official_census_extraction",
                status="succeeded",
                started_at=ext_stage_start,
            )

            # --- Stage: official_census_persistence (process JSON) ---
            persist_stage_start = timezone.now()

            json_files = sorted(
                tmpdir_path.glob("censo-oficial-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not json_files:
                # No official census data found — success, zero records.
                # Call process with empty list to clear stale rows for this date.
                metrics = process_official_census_records(
                    [], reference_date=ref_date
                )
                create_stage_metric(
                    run=run,
                    stage_name="official_census_persistence",
                    status="succeeded",
                    started_at=persist_stage_start,
                    details_json=metrics,
                )
                mark_run_succeeded(run)

                return ExtractionResult(
                    extraction_type="official_census_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=True,
                    metrics=metrics,
                    ingestion_run_id=run.pk,
                )

            json_path = json_files[0]

            try:
                data = json.loads(
                    json_path.read_text(encoding="utf-8")
                )
                records = data.get("records", [])

                metrics = process_official_census_records(
                    records, reference_date=ref_date
                )
            except Exception as exc:
                err_msg = safe_error_message(str(exc))
                create_stage_metric(
                    run=run,
                    stage_name="official_census_persistence",
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
                    extraction_type="official_census_extraction",
                    target_start=parsed_date,
                    target_end=parsed_date,
                    success=False,
                    failure_reason="unexpected_exception",
                    error_message=err_msg,
                    ingestion_run_id=run.pk,
                )

            create_stage_metric(
                run=run,
                stage_name="official_census_persistence",
                status="succeeded",
                started_at=persist_stage_start,
                details_json=metrics,
            )

            mark_run_succeeded(run)

            return ExtractionResult(
                extraction_type="official_census_extraction",
                target_start=parsed_date,
                target_end=parsed_date,
                success=True,
                metrics=metrics,
                ingestion_run_id=run.pk,
            )

    except Exception as exc:
        err_msg = safe_error_message(str(exc))
        if "run" in dir() and run and run.pk:
            mark_run_failed(
                run,
                error_message=err_msg,
                failure_reason="unexpected_exception",
            )
        return ExtractionResult(
            extraction_type="official_census_extraction",
            target_start=parsed_date,
            target_end=parsed_date,
            success=False,
            failure_reason="unexpected_exception",
            error_message=err_msg,
            ingestion_run_id=run.pk
            if "run" in dir() and run and run.pk
            else None,
        )


def process_official_census_records(
    records: list[dict[str, str | None]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process official census records from the JSON extraction.

    Persists individual ``OfficialCensusRecord`` rows with date-replace
    semantics: existing rows for the target date are deleted and new rows
    are bulk-created from the extracted data.

    Args:
        records: List of dicts with official census record data from the
            JSON output. Expected keys: PRONTUARIO, NOME, DATA INTERNACAO,
            TEMPO INT, QUARTO/LEITO, CID INT, DESCRICAO, UNIDADE,
            AREA FUNCIONAL, SIGLA, ESPECIALIDADE.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.census.models import OfficialCensusRecord

    with transaction.atomic():
        # Delete existing rows for this date
        OfficialCensusRecord.objects.filter(
            date=reference_date
        ).delete()

        # Bulk-create from the extracted records
        snapshot_batch: list[OfficialCensusRecord] = []
        for record in records:
            snapshot_batch.append(
                OfficialCensusRecord(
                    date=reference_date,
                    prontuario=record.get("PRONTUARIO", "") or "",
                    nome=record.get("NOME", "") or "",
                    data_internacao=record.get(
                        "DATA INTERNACAO", ""
                    )
                    or "",
                    tempo_internacao=record.get("TEMPO INT", "")
                    or "",
                    quarto_leito=record.get("QUARTO/LEITO", "")
                    or "",
                    cid=record.get("CID INT", "") or "",
                    descricao=record.get("DESCRICAO", "") or "",
                    unidade=record.get("UNIDADE", "") or "",
                    area_funcional=record.get(
                        "AREA FUNCIONAL", ""
                    )
                    or "",
                    sigla=record.get("SIGLA", "") or "",
                    especialidade=record.get(
                        "ESPECIALIDADE", ""
                    )
                    or "",
                )
            )
        if snapshot_batch:
            OfficialCensusRecord.objects.bulk_create(
                snapshot_batch
            )

    return {
        "total_records": len(snapshot_batch),
    }
