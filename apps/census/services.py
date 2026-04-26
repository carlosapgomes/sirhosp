from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.db.models import Max

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.services import (
    queue_admissions_only_run,
    queue_demographics_only_run,
)
from apps.patients.models import Patient


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


def parse_census_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Parse a census CSV file and classify bed status for each row.

    Args:
        csv_path: Path to CSV file with columns:
            setor, qrt_leito, prontuario, nome, esp

    Returns:
        List of dicts with keys:
            setor, leito, prontuario, nome, especialidade, bed_status

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

        for row in reader:
            prontuario = (row.get("prontuario") or "").strip()
            nome = (row.get("nome") or "").strip()
            bed_status = classify_bed_status(prontuario, nome)

            rows.append(
                {
                    "setor": (row.get("setor") or "").strip(),
                    "leito": (row.get("qrt_leito") or "").strip(),
                    "prontuario": prontuario,
                    "nome": nome,
                    "especialidade": (row.get("esp") or "").strip(),
                    "bed_status": bed_status,
                }
            )

    return rows


def process_census_snapshot(
    run_id: int | None = None,
) -> dict[str, int]:
    """Process the most recent census snapshot and enqueue patient sync runs.

    For each occupied bed with a prontuario, creates or updates the
    corresponding Patient record and enqueues both admissions-only
    and demographics-only ingestion runs.

    Args:
        run_id: Optional IngestionRun ID to process a specific census run.
            If None, processes the most recent captured_at.

    Returns:
        Dict with metrics:
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
                "patients_total": 0,
                "patients_new": 0,
                "patients_updated": 0,
                "runs_enqueued": 0,
                "demographics_runs_enqueued": 0,
                "patients_skipped": 0,
            }
        snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    # Filter only occupied beds
    occupied = snapshots.filter(bed_status=BedStatus.OCCUPIED)

    # Deduplicate by prontuario — keep last occurrence
    seen: set[str] = set()
    patients_to_process: list[dict[str, str]] = []
    for snap in occupied.order_by("-pk"):  # latest first → keeps last
        pront = snap.prontuario.strip()
        if not pront:
            continue
        if pront not in seen:
            seen.add(pront)
            patients_to_process.append({
                "prontuario": pront,
                "nome": snap.nome.strip(),
            })

    new_count = 0
    updated_count = 0
    enqueued_count = 0

    for entry in patients_to_process:
        prontuario = entry["prontuario"]
        nome = entry["nome"]

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

        # Enqueue admissions-only run for this patient
        queue_admissions_only_run(patient_record=prontuario)
        enqueued_count += 1

        # Enqueue demographics-only run for this patient
        queue_demographics_only_run(patient_record=prontuario)

    return {
        "patients_total": len(patients_to_process),
        "patients_new": new_count,
        "patients_updated": updated_count,
        "runs_enqueued": enqueued_count,
        "demographics_runs_enqueued": len(patients_to_process),
        "patients_skipped": max(0, occupied.count() - len(patients_to_process)),
    }
