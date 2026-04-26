# SLICE-DI-2: Integrar `demographics_only` no `process_census_snapshot`

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos
do sistema fonte hospitalar via web scraping (Playwright), persiste em
PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap+HTMX.

---

## 2. Estado atual do projeto (após Slice DI-1)

Após o Slice DI-1, o projeto já possui:

```text
apps/ingestion/services.py
    ├── queue_admissions_only_run()          ← existente antes
    └── queue_demographics_only_run()        ← NOVO (DI-1)

apps/ingestion/management/commands/process_ingestion_runs.py
    ├── _process_run() dispatcher            ← modificado: adicionou branch
    │                                           elif intent == "demographics_only"
    ├── _process_admissions_only()           ← existente
    ├── _process_full_sync()                 ← existente
    └── _process_demographics_only()         ← NOVO (DI-1)

tests/unit/test_demographics_worker.py      ← NOVO (DI-1)
```

**O worker já sabe processar `demographics_only`. Falta só o censo enfileirar.**

---

## 3. O `process_census_snapshot()` ATUAL

Arquivo: `apps/census/services.py`

```python
from apps.ingestion.services import queue_admissions_only_run
from apps.patients.models import Patient

def process_census_snapshot(run_id=None) -> dict[str, int]:
    # ... (busca snapshots, filtra occupied, deduplica)

    new_count = 0
    updated_count = 0
    enqueued_count = 0

    for entry in patients_to_process:
        prontuario = entry["prontuario"]
        nome = entry["nome"]

        patient, created = Patient.objects.get_or_create(
            source_system="tasy",
            patient_source_key=prontuario,
            defaults={"name": nome},
        )

        if created:
            new_count += 1
        elif nome and patient.name != nome:
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
        "patients_skipped": ...,
    }
```

**Problema**: o paciente é criado só com `name`. Nenhum campo demográfico é
preenchido. A função `queue_demographics_only_run()` já existe (DI-1) mas
não está sendo chamada.

---

## 4. Objetivo do Slice

Fazer o `process_census_snapshot()` enfileirar **também** runs de demográficos
para cada paciente processado. O worker (DI-1) se encarrega de executá-las.

### 4.1 O que EXATAMENTE modificar

#### A) `apps/census/services.py` — duas alterações pontuais

**Alteração 1 — import:**

Trocar:

```python
from apps.ingestion.services import queue_admissions_only_run
```

Por:

```python
from apps.ingestion.services import (
    queue_admissions_only_run,
    queue_demographics_only_run,
)
```

**Alteração 2 — dentro do loop de pacientes:**

Logo após a linha:

```python
        queue_admissions_only_run(patient_record=prontuario)
        enqueued_count += 1
```

Adicionar:

```python
        # Enqueue demographics-only run for this patient
        queue_demographics_only_run(patient_record=prontuario)
```

**Alteração 3 — dict de retorno:**

Adicionar a chave `demographics_runs_enqueued` ao dict de retorno. Como o número
de runs de demográficos é igual ao número de pacientes processados:

```python
    return {
        "patients_total": len(patients_to_process),
        "patients_new": new_count,
        "patients_updated": updated_count,
        "runs_enqueued": enqueued_count,
        "demographics_runs_enqueued": len(patients_to_process),  # NOVO
        "patients_skipped": max(0, occupied.count() - len(patients_to_process)),
    }
```

#### B) `apps/census/management/commands/process_census_snapshot.py`

O management command imprime as métricas. Atualizar o output para incluir
`demographics_runs_enqueued`:

```python
    def handle(self, *args, **options):
        run_id: int | None = options["run_id"]
        result = process_census_snapshot(run_id=run_id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Census snapshot processed:\n"
                f"  Patients total:             {result['patients_total']}\n"
                f"  Patients new:               {result['patients_new']}\n"
                f"  Patients updated:           {result['patients_updated']}\n"
                f"  Admissions runs enqueued:   {result['runs_enqueued']}\n"
                f"  Demographics runs enqueued: {result['demographics_runs_enqueued']}\n"
                f"  Skipped (no pront):         {result['patients_skipped']}"
            )
        )
```

---

## 5. Testes: atualizar `tests/unit/test_process_census_snapshot.py`

O arquivo **já existe** com 7+ testes da implementação do Slice CIS-S4.
**NÃO sobrescrever o arquivo.** Apenas **adicionar** ao final os testes abaixo
e **modificar** os testes existentes que verificam o dict de retorno.

### 5.1 Testes NOVOS a adicionar

```python
    def test_demographics_run_enqueued_for_new_patient(self):
        """New patient → demographics_only run is also enqueued."""
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

        assert result["demographics_runs_enqueued"] == 1

        # Verify demographics run exists
        demo_run = IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).first()
        assert demo_run is not None
        assert demo_run.parameters_json["patient_record"] == "14160147"

        # Verify admissions run also exists (existing behavior)
        adm_run = IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).first()
        assert adm_run is not None

    def test_demographics_run_enqueued_for_existing_patient(self):
        """Existing patient → demographics_only run is still enqueued."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
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

        # Demographics run should be enqueued even for existing patients
        assert result["demographics_runs_enqueued"] == 1
        assert IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).exists()

    def test_multiple_patients_get_demographics_runs(self):
        """Multiple occupied beds → one demographics run per patient."""
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
        assert result["demographics_runs_enqueued"] == 3
        assert result["runs_enqueued"] == 3  # admissions runs
        assert IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).count() == 3

    def test_demographics_not_enqueued_for_empty_beds(self):
        """Empty beds → no demographics runs."""
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
        assert result["demographics_runs_enqueued"] == 0
        assert not IngestionRun.objects.filter(
            intent="demographics_only"
        ).exists()
```

### 5.2 Testes EXISTENTES a atualizar

Nos testes existentes que verificam o dict de retorno, adicionar a asserção
`assert result["demographics_runs_enqueued"]` com o valor esperado. Em
particular:

- `test_new_patient_created_and_run_enqueued` → `assert result["demographics_runs_enqueued"] == 1`
- `test_existing_patient_not_duplicated` → `assert result["demographics_runs_enqueued"] == 1`
- `test_existing_patient_name_updated` → `assert result["demographics_runs_enqueued"] == 1`
- `test_duplicate_prontuario_in_same_run_deduplicated` → `assert result["demographics_runs_enqueued"] == 1`
- `test_multiple_patients_in_snapshot` → `assert result["demographics_runs_enqueued"] == 3`
- `test_empty_snapshot_returns_zero` → `assert result["demographics_runs_enqueued"] == 0`

---

## 6. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## 7. Relatório

Gerar `/tmp/sirhosp-slice-DI-2-report.md` com:

- Resumo do slice (1 parágrafo)
- Checklist de aceite (todos os checkboxes do tasks.md para DI-2)
- Lista de arquivos alterados (com paths absolutos)
- **Fragmentos de código ANTES/DEPOIS** por arquivo alterado
- Comandos executados e resultados (stdout resumido)
- Riscos, pendências e próximo passo sugerido

---

## 8. Anti-padrões PROIBIDOS

- ❌ Não modificar `queue_demographics_only_run()` nem `_process_demographics_only()`
- ❌ Não alterar a lógica de deduplicação do `process_census_snapshot()`
- ❌ Não remover a chamada a `queue_admissions_only_run()` (ela continua)
- ❌ Não quebrar os testes existentes — apenas **adicionar** asserções
- ❌ Não enfileirar `demographics_only` para leitos não-ocupados
- ❌ Não usar `print()` (usar `self.stdout.write()` no command)
