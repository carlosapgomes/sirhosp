from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from apps.census.models import BedStatus


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
