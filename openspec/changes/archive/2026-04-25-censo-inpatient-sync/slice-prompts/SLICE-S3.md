# SLICE-S3: Management command `extract_census` + parser CSV + classificador

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright), persiste em PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, Playwright (Chromium), pytest, Bootstrap+HTMX.

**Padrão de execução de scripts**: management commands Django que chamam scripts Playwright via `subprocess.run()`. Ver `PlaywrightEvolutionExtractor` em `apps/ingestion/extractors/playwright_extractor.py` para referência do padrão.

---

## 2. Estado atual do projeto (após Slices S1–S2)

````text
apps/census/
├── __init__.py
├── apps.py              ← CensusConfig
├── models.py             ← BedStatus, CensusSnapshot
├── admin.py              ← CensusSnapshotAdmin
└── migrations/
    └── 0001_initial.py

tests/unit/
└── test_census_models.py ← 9 testes (S1)

automation/source_system/current_inpatients/
├── extract_census.py     ← script Playwright (S2)
└── README.md
```text

### Modelo `CensusSnapshot` (relevante para este slice)

```python
class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"

class CensusSnapshot(models.Model):
    captured_at = models.DateTimeField(...)
    ingestion_run = models.ForeignKey("ingestion.IngestionRun", null=True, ...)
    setor = models.CharField(max_length=255)
    leito = models.CharField(max_length=50)
    prontuario = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=512, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    bed_status = models.CharField(max_length=20, choices=BedStatus.choices)
```text

### Modelo `IngestionRun` (referência)

```python
class IngestionRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"), ("running", "Running"),
        ("succeeded", "Succeeded"), ("failed", "Failed"),
    ]
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    intent = models.CharField(max_length=50, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    events_processed = models.PositiveIntegerField(default=0)
    # ... outros campos
```text

### Contrato de saída do script `extract_census.py`

O script gera um CSV com colunas: `setor`, `qrt_leito`, `prontuario`, `nome`, `esp`.

Exemplo:

```csv
setor,qrt_leito,prontuario,nome,esp
UTI GERAL ADULTO 1 - HGRS,UG01A,14160147,JOSE AUGUSTO MERCES,NEF
UTI GERAL ADULTO 1 - HGRS,UG09I,,RESERVA CIRÚRGICA,
UTI PEDIATRICA - HGRS,UP01B,,LIMPEZA,
```text

---

## 3. Objetivo do Slice

Criar:

1. **Classificador de leitos** (`classify_bed_status`) — função pura que mapeia `(prontuario, nome)` → `BedStatus`
2. **Parser de CSV** (`parse_census_csv`) — lê o CSV gerado pelo script e retorna lista de dicts com `bed_status` classificado
3. **Management command** `extract_census` — orquestra: executa o script Playwright, faz parse do CSV, popula `CensusSnapshot`, registra `IngestionRun`

---

## 4. O que EXATAMENTE criar

### 4.1 `apps/census/services.py` — Classificador + Parser

```python
from __future__ import annotations

import csv
import re
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

            rows.append({
                "setor": (row.get("setor") or "").strip(),
                "leito": (row.get("qrt_leito") or "").strip(),
                "prontuario": prontuario,
                "nome": nome,
                "especialidade": (row.get("esp") or "").strip(),
                "bed_status": bed_status,
            })

    return rows
```text

### 4.2 `apps/census/management/__init__.py`

Arquivo vazio.

### 4.3 `apps/census/management/commands/__init__.py`

Arquivo vazio.

### 4.4 `apps/census/management/commands/extract_census.py`

```python
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.census.census_parser import parse_census_csv  # vai ser criado
from apps.census.models import CensusSnapshot
from apps.ingestion.models import IngestionRun


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
            csv_output = tmpdir_path / "census.csv"

            # Build subprocess command
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir", str(tmpdir_path),
            ]
            if headless:
                cmd.append("--headless")
            if max_setores > 0:
                cmd.extend(["--max-setores", str(max_setores)])

            self.stdout.write(f"Running census extraction...")
            self.stdout.write(f"  Script: {script_path}")

            # Create IngestionRun to track this execution
            run = IngestionRun.objects.create(
                status="running",
                intent="census_extraction",
                started_at=timezone.now(),
            )

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=1800,  # 30 minutes max
                )
            except subprocess.TimeoutExpired as exc:
                run.status = "failed"
                run.error_message = f"Timeout: {exc}"
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write(f"Census extraction timed out: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                run.status = "failed"
                run.error_message = (
                    f"Exit code {result.returncode}: {result.stderr[:500]}"
                )
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write(result.stderr)
                sys.exit(1)

            # Find the CSV file in output dir
            csv_files = list(tmpdir_path.glob("censo-*.csv"))
            if not csv_files:
                # Try to find by the save_results naming pattern
                csv_files = list(tmpdir_path.glob("*.csv"))

            if not csv_files:
                run.status = "failed"
                run.error_message = "No CSV output found after extraction."
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write("No CSV output found.")
                sys.exit(1)

            csv_path = csv_files[0]
            self.stdout.write(f"  CSV output: {csv_path}")

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

            # Update run status
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Census extraction complete. "
                    f"{len(snapshots)} rows persisted."
                )
            )
```text

---

## 5. Estrutura de diretórios a criar

```text
apps/census/
├── services.py              ← classify_bed_status + parse_census_csv (NOVO)
├── management/
│   ├── __init__.py           ← vazio (NOVO)
│   └── commands/
│       ├── __init__.py       ← vazio (NOVO)
│       └── extract_census.py ← management command (NOVO)
```text

**Nota**: o arquivo `services.py` é novo. O S4 vai adicionar `process_census_snapshot()` a ele. Não crie `census_parser.py` separado — coloque `parse_census_csv` e `classify_bed_status` em `services.py`.

---

## 6. Testes

### 6.1 `tests/unit/test_bed_classification.py`

```python
from __future__ import annotations

import pytest
from apps.census.services import classify_bed_status
from apps.census.models import BedStatus


class TestClassifyBedStatus:
    def test_occupied_with_prontuario(self):
        assert classify_bed_status("14160147", "JOSE AUGUSTO MERCES") == BedStatus.OCCUPIED

    def test_occupied_even_with_weird_name(self):
        """Se tem prontuario, é occupied independente do nome."""
        assert classify_bed_status("99999", "IGNORADO SUPOSTO CLAUDIO") == BedStatus.OCCUPIED

    def test_empty_desocupado(self):
        assert classify_bed_status("", "DESOCUPADO") == BedStatus.EMPTY

    def test_empty_vazio(self):
        assert classify_bed_status("", "VAZIO") == BedStatus.EMPTY

    def test_empty_case_insensitive(self):
        assert classify_bed_status("", "desocupado") == BedStatus.EMPTY

    def test_maintenance_limpeza(self):
        assert classify_bed_status("", "LIMPEZA") == BedStatus.MAINTENANCE

    def test_reserved_reserva_interna(self):
        assert classify_bed_status("", "RESERVA INTERNA") == BedStatus.RESERVED

    def test_reserved_reserva_cirurgica(self):
        assert classify_bed_status("", "RESERVA CIRÚRGICA") == BedStatus.RESERVED

    def test_reserved_reserva_regulacao(self):
        assert classify_bed_status("", "RESERVA REGULAÇÃO") == BedStatus.RESERVED

    def test_reserved_reserva_hemodinamica(self):
        assert classify_bed_status("", "RESERVA HEMODINÂMICA") == BedStatus.RESERVED

    def test_isolation_isolamento_medico(self):
        assert classify_bed_status("", "ISOLAMENTO MÉDICO") == BedStatus.ISOLATION

    def test_isolation_isolamento_social(self):
        assert classify_bed_status("", "ISOLAMENTO SOCIAL") == BedStatus.ISOLATION

    def test_fallback_unknown_empty(self):
        """Nome desconhecido sem prontuario → empty."""
        assert classify_bed_status("", "ALGUMA COISA ESTRANHA") == BedStatus.EMPTY

    def test_prontuario_with_spaces(self):
        """Prontuario com espaços em branco → occupied."""
        assert classify_bed_status(" 14160147 ", "JOSE") == BedStatus.OCCUPIED

    def test_empty_prontuario_empty_string(self):
        """Prontuario vazio com string vazia."""
        assert classify_bed_status("", "") == BedStatus.EMPTY
```text

### 6.2 `tests/unit/test_extract_census_command.py`

```python
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone
from unittest.mock import patch, MagicMock

from apps.census.models import CensusSnapshot, BedStatus
from apps.census.services import parse_census_csv
from apps.ingestion.models import IngestionRun


@pytest.mark.django_db
class TestParseCensusCsv:
    def test_parse_valid_csv(self):
        """Parse a valid CSV with mixed bed statuses."""
        csv_content = (
            "setor,qrt_leito,prontuario,nome,esp\n"
            "UTI A,UG01A,14160147,JOSE MERCES,NEF\n"
            "UTI A,UG02B,,DESOCUPADO,\n"
            "UTI A,UG03C,,RESERVA INTERNA,\n"
            "ENF B,E01A,99999,MARIA SILVA,CME\n"
            "ENF B,E02B,,LIMPEZA,\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            rows = parse_census_csv(csv_path)
            assert len(rows) == 5
            assert rows[0]["bed_status"] == BedStatus.OCCUPIED
            assert rows[0]["prontuario"] == "14160147"
            assert rows[1]["bed_status"] == BedStatus.EMPTY
            assert rows[2]["bed_status"] == BedStatus.RESERVED
            assert rows[3]["bed_status"] == BedStatus.OCCUPIED
            assert rows[4]["bed_status"] == BedStatus.MAINTENANCE
        finally:
            csv_path.unlink(missing_ok=True)

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_census_csv(Path("/nonexistent/census.csv"))

    def test_parse_missing_columns(self):
        csv_content = "setor,qrt_leito\nUTI A,UG01A\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="missing required columns"):
                parse_census_csv(csv_path)
        finally:
            csv_path.unlink(missing_ok=True)
```text

---

## 7. Quality Gate

```bash
# Django system check
./scripts/test-in-container.sh check

# Unit tests (apenas os do slice + existentes)
./scripts/test-in-container.sh unit

# Lint
./scripts/test-in-container.sh lint
```text

---

## 8. Relatório

Gerar `/tmp/sirhosp-slice-CIS-S3-report.md` com status, arquivos criados/modificados, snippets before/after, comandos executados, riscos, próximo slice.

---

## 9. Anti-padrões PROIBIDOS

- ❌ Rodar scraping real durante testes (mockar subprocess)
- ❌ Criar `census_parser.py` separado (tudo em `services.py`)
- ❌ Esquecer `__init__.py` nos pacotes `management/` e `management/commands/`
- ❌ Usar `print()` em vez de `self.stdout.write()` / `self.stderr.write()` no management command
- ❌ Hardcodar caminhos absolutos (usar `__file__` relativo)
````
