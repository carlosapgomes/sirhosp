<!-- markdownlint-disable MD013 MD033 MD040 MD036 -->
# SLICE-S4: Processador de censo — descoberta de pacientes + enfileiramento

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos do sistema fonte hospitalar (AGHU/TASY) via web scraping (Playwright), persiste em PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap+HTMX.

---

## 2. Estado atual do projeto (após Slices S1–S3)

```
apps/census/
├── models.py         ← CensusSnapshot, BedStatus
├── services.py       ← classify_bed_status(), parse_census_csv()
├── admin.py
├── apps.py
├── management/
│   └── commands/
│       └── extract_census.py   ← command que popula CensusSnapshot

apps/ingestion/
├── models.py         ← IngestionRun (intent, status, parameters_json)
├── services.py       ← queue_ingestion_run(), queue_admissions_only_run()

apps/patients/
├── models.py         ← Patient (patient_source_key, name, source_system)

tests/unit/
├── test_census_models.py        ← 9 testes (S1)
├── test_bed_classification.py   ← 15 testes (S3)
└── test_extract_census_command.py ← 3 testes (S3)
```

### Função existente para enfileirar

Em `apps/ingestion/services.py`:

```python
def queue_admissions_only_run(*, patient_record: str) -> IngestionRun:
    """Create an IngestionRun for admissions-only synchronization."""
    return IngestionRun.objects.create(
        status="queued",
        intent="admissions_only",
        parameters_json={
            "patient_record": patient_record,
            "intent": "admissions_only",
        },
    )
```

### Modelo Patient (resumo)

```python
class Patient(models.Model):
    patient_source_key = models.CharField(max_length=255)  # prontuário
    source_system = models.CharField(max_length=100, default="tasy")
    name = models.CharField(max_length=512)
    # ... outros campos demográficos

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["source_system", "patient_source_key"],
                name="uq_patient_src",
            ),
        ]
```

---

## 3. Objetivo do Slice

Adicionar a função `process_census_snapshot()` ao `apps/census/services.py` e o management command `process_census_snapshot`. Este processador:

1. Lê o `CensusSnapshot` mais recente (ou de um `run_id` específico)
2. Filtra apenas leitos `occupied`
3. Deduplica por `prontuario`
4. Para cada prontuario único:
   - Cria `Patient` se não existir (com `source_system="tasy"`)
   - Atualiza `name` se o paciente já existir e o nome for diferente
   - Enfileira `IngestionRun` com `intent="admissions_only"` para cada paciente

---

## 4. O que EXATAMENTE criar

### 4.1 `apps/census/services.py` — Adicionar função `process_census_snapshot`

Adicionar ao arquivo existente (que já contém `classify_bed_status` e `parse_census_csv`):

```python
from __future__ import annotations

from typing import Any

from django.db.models import Max
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import queue_admissions_only_run
from apps.patients.models import Patient


def process_census_snapshot(
    run_id: int | None = None,
) -> dict[str, int]:
    """Process the most recent census snapshot and enqueue patient sync runs.

    For each occupied bed with a prontuario, creates or updates the
    corresponding Patient record and enqueues an admissions-only
    ingestion run.

    Args:
        run_id: Optional IngestionRun ID to process a specific census run.
            If None, processes the most recent captured_at.

    Returns:
        Dict with metrics:
            patients_total: Total unique prontuarios processed
            patients_new: Patients created (not previously in DB)
            patients_updated: Patients whose name was updated
            runs_enqueued: IngestionRuns created
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
                "patients_skipped": 0,
            }
        snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    # Filter only occupied beds
    occupied = snapshots.filter(bed_status=BedStatus.OCCUPIED)

    # Deduplicate by prontuario — keep last occurrence
    seen: set[str] = set()
    patients_to_process: list[dict[str, str]] = []
    for snap in occupied.order_by("pk"):  # preserve insertion order
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

    return {
        "patients_total": len(patients_to_process),
        "patients_new": new_count,
        "patients_updated": updated_count,
        "runs_enqueued": enqueued_count,
        "patients_skipped": max(0, occupied.count() - len(patients_to_process)),
    }
```

**IMPORTANTE**: esta função é **ADICIONADA** ao `services.py` existente. Não sobrescrever as funções `classify_bed_status` e `parse_census_csv` já presentes.

### 4.2 `apps/census/management/commands/process_census_snapshot.py`

```python
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.census.services import process_census_snapshot


class Command(BaseCommand):
    help = "Process latest census snapshot: create/update Patients and enqueue admission sync runs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help="Process a specific ingestion run ID (default: most recent).",
        )

    def handle(self, *args, **options):
        run_id: int | None = options["run_id"]

        result = process_census_snapshot(run_id=run_id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Census snapshot processed:\n"
                f"  Patients total:    {result['patients_total']}\n"
                f"  Patients new:      {result['patients_new']}\n"
                f"  Patients updated:  {result['patients_updated']}\n"
                f"  Runs enqueued:     {result['runs_enqueued']}\n"
                f"  Skipped (no pront): {result['patients_skipped']}"
            )
        )
```

---

## 5. Testes: `tests/unit/test_process_census_snapshot.py`

```python
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import process_census_snapshot
from apps.ingestion.models import IngestionRun
from apps.patients.models import Patient


@pytest.mark.django_db
class TestProcessCensusSnapshot:
    def test_empty_snapshot_returns_zero(self):
        """When no CensusSnapshot exists, all counts are zero."""
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["patients_new"] == 0
        assert result["runs_enqueued"] == 0

    def test_only_empty_beds_no_patients(self):
        """Beds without prontuario are skipped."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["runs_enqueued"] == 0
        assert Patient.objects.count() == 0

    def test_new_patient_created_and_run_enqueued(self):
        """New prontuario → Patient created + admissions_only enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_new"] == 1
        assert result["patients_total"] == 1
        assert result["runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "JOSE AUGUSTO MERCES"

        # Verify IngestionRun was enqueued
        queued_run = IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).first()
        assert queued_run is not None
        assert queued_run.parameters_json["patient_record"] == "14160147"

    def test_existing_patient_not_duplicated(self):
        """Patient already exists → no duplicate, but run is still enqueued."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE AUGUSTO MERCES",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_new"] == 0
        assert result["patients_updated"] == 0
        assert result["runs_enqueued"] == 1
        assert Patient.objects.count() == 1

    def test_existing_patient_name_updated(self):
        """Patient exists with different name → name updated."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="NOME ANTIGO",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="NOME NOVO",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_updated"] == 1
        assert result["runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "NOME NOVO"

    def test_duplicate_prontuario_in_same_run_deduplicated(self):
        """Same prontuario appears twice → only 1 run enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES UPDATED",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["runs_enqueued"] == 1
        assert result["patients_total"] == 1

        # Name should be from the LAST occurrence
        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        last_snap = CensusSnapshot.objects.order_by("-pk").first()
        assert patient.name == last_snap.nome

    def test_specific_run_id(self):
        """Can process a specific run by ID."""
        run1 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now() - timezone.timedelta(hours=2),
            ingestion_run=run1,
            setor="OLD",
            leito="01",
            prontuario="111",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        run2 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run2,
            setor="NEW",
            leito="01",
            prontuario="222",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        # Process only run1
        result = process_census_snapshot(run_id=run1.pk)
        assert result["patients_total"] == 1
        assert Patient.objects.filter(patient_source_key="111").exists()
        assert not Patient.objects.filter(patient_source_key="222").exists()

    def test_multiple_patients_in_snapshot(self):
        """Multiple occupied beds → multiple patients + runs."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        for i, (pront, nome) in enumerate(
            [("111", "A"), ("222", "B"), ("333", "C")]
        ):
            CensusSnapshot.objects.create(
                captured_at=timezone.now(),
                ingestion_run=run,
                setor="UTI",
                leito=f"L{i}",
                prontuario=pront,
                nome=nome,
                especialidade="TST",
                bed_status=BedStatus.OCCUPIED,
            )
        result = process_census_snapshot()
        assert result["patients_total"] == 3
        assert result["patients_new"] == 3
        assert result["runs_enqueued"] == 3
        assert Patient.objects.count() == 3
        assert IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).count() == 3
```

---

## 6. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## 7. Relatório

Gerar `/tmp/sirhosp-slice-CIS-S4-report.md`.

---

## 8. Anti-padrões PROIBIDOS

- ❌ Não criar management command sem testar com --help
- ❌ Não usar `print()` no management command (usar `self.stdout.write()`)
- ❌ Não criar `Patient` com `source_system` diferente de `"tasy"`
- ❌ Não processar leitos com `bed_status != occupied`
- ❌ Não enfileirar run para prontuario vazio
- ❌ Não modificar `apps/ingestion/services.py` (usar funções existentes)
