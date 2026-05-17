#!/usr/bin/env python3
"""
Ad-hoc: limpa prontuários gravados como float (.0) ou com separadores.

Problema: o openpyxl lê células numéricas do XLSX como float, e
str(19017680.0) vira "19017680.0". Isso contamina toda a cadeia:

    CensusSnapshot.prontuario → Patient.patient_source_key
                              → IngestionRun.parameters_json

Uso:
    uv run python scripts/fix_prontuario_float.py          # dry-run
    uv run python scripts/fix_prontuario_float.py --apply  # executa

Requisitos: Django configurado (DJANGO_SETTINGS_MODULE).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Generator
from typing import Any

# ---------------------------------------------------------------------------
# Setup Django
# ---------------------------------------------------------------------------

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402

from apps.census.models import CensusSnapshot  # noqa: E402
from apps.ingestion.models import IngestionRun  # noqa: E402
from apps.patients.models import Patient  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Pattern: ends with .0 or contains dot/slash after digits
_DIRTY_RE = re.compile(r"\.0$|/\d+$|\.(?=\d)")


def is_dirty_prontuario(val: str) -> bool:
    """Check if a prontuário string has float contamination."""
    if not val:
        return False
    return bool(_DIRTY_RE.search(val))


def clean_prontuario(val: str) -> str:
    """Remove float suffix and separators."""
    if not val:
        return val
    # Remove trailing .0
    if val.endswith(".0"):
        val = val[:-2]
    # Remove any remaining dots and slashes
    val = val.replace("/", "").replace(".", "")
    return val.strip()


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------


def dirty_patients() -> Generator[Patient, None, None]:
    for p in Patient.objects.filter(source_system="tasy").iterator():
        if is_dirty_prontuario(p.patient_source_key):
            yield p


def dirty_snapshots() -> Generator[CensusSnapshot, None, None]:
    for s in CensusSnapshot.objects.iterator():
        if is_dirty_prontuario(s.prontuario):
            yield s


def dirty_runs() -> Generator[IngestionRun, None, None]:
    for r in IngestionRun.objects.iterator():
        params = r.parameters_json or {}
        pront = params.get("patient_record", "")
        if is_dirty_prontuario(str(pront)):
            yield r


# ---------------------------------------------------------------------------
# Fixers
# ---------------------------------------------------------------------------


@transaction.atomic
def fix_patients(dry_run: bool = True) -> int:
    fixed = 0
    for p in dirty_patients():
        old = p.patient_source_key
        new = clean_prontuario(old)
        if old == new:
            continue
        if not dry_run:
            p.patient_source_key = new
            p.save(update_fields=["patient_source_key", "updated_at"])
        print(f"  Patient pk={p.pk}: '{old}' → '{new}'")
        fixed += 1
    return fixed


@transaction.atomic
def fix_snapshots(dry_run: bool = True) -> int:
    fixed = 0
    for s in dirty_snapshots():
        old = s.prontuario
        new = clean_prontuario(old)
        if old == new:
            continue
        if not dry_run:
            s.prontuario = new
            s.save(update_fields=["prontuario"])
        print(f"  Snapshot pk={s.pk}: '{old}' → '{new}'")
        fixed += 1
    return fixed


@transaction.atomic
def fix_runs(dry_run: bool = True) -> int:
    fixed = 0
    for r in dirty_runs():
        params: dict[str, Any] = r.parameters_json or {}
        old_pront = str(params.get("patient_record", ""))
        new_pront = clean_prontuario(old_pront)
        if old_pront == new_pront:
            continue
        params["patient_record"] = new_pront
        if not dry_run:
            r.parameters_json = params
            r.save(update_fields=["parameters_json"])
        print(f"  Run pk={r.pk}: patient_record '{old_pront}' → '{new_pront}'")
        fixed += 1
    return fixed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--apply" not in sys.argv

    print("=" * 70)
    print("Limpeza de prontuários contaminados com .0 / separadores")
    print(f"Modo: {'DRY-RUN (sem alterações)' if dry_run else 'APLICANDO'}")
    print("=" * 70)

    total_patients = Patient.objects.filter(source_system="tasy").count()
    total_snapshots = CensusSnapshot.objects.count()
    total_runs = IngestionRun.objects.count()

    dirty_p_count = sum(1 for _ in dirty_patients())
    dirty_s_count = sum(1 for _ in dirty_snapshots())
    dirty_r_count = sum(1 for _ in dirty_runs())

    print(f"\nRegistros total: {total_patients} patients, "
          f"{total_snapshots} snapshots, {total_runs} runs")
    print(f"Contaminados:    {dirty_p_count} patients, "
          f"{dirty_s_count} snapshots, {dirty_r_count} runs")

    if dirty_p_count == 0 and dirty_s_count == 0 and dirty_r_count == 0:
        print("\nNada a limpar. Tudo ok!")
        return

    print(f"\n--- Limpando Patients ({dirty_p_count}) ---")
    p_fixed = fix_patients(dry_run=dry_run)
    print(f"  {p_fixed} corrigidos")

    print(f"\n--- Limpando Snapshots ({dirty_s_count}) ---")
    s_fixed = fix_snapshots(dry_run=dry_run)
    print(f"  {s_fixed} corrigidos")

    print(f"\n--- Limpando IngestionRuns ({dirty_r_count}) ---")
    r_fixed = fix_runs(dry_run=dry_run)
    print(f"  {r_fixed} corrigidos")

    total = p_fixed + s_fixed + r_fixed
    print(f"\nTotal registros corrigidos: {total}")

    if dry_run and total > 0:
        print("\n⚠  Dry-run — nenhuma alteração foi persistida.")
        print("   Execute com --apply para aplicar as correções.")


if __name__ == "__main__":
    main()
