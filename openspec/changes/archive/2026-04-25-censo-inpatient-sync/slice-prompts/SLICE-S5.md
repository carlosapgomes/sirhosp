# SLICE-S5: Worker — auto-enfileira `full_sync` da admissão mais recente

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright), persiste em PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest.

---

## 2. Estado atual do projeto (após Slices S1–S4)

```text
apps/ingestion/
├── management/
│   └── commands/
│       └── process_ingestion_runs.py   ← worker (VAI SER MODIFICADO)
├── services.py     ← ingest_evolution(), queue_ingestion_run(), queue_admissions_only_run()

apps/patients/
├── models.py       ← Patient, Admission (admission_date, discharge_date, source_admission_key)
├── services.py     ← search_patients, get_patient_or_404, ...

apps/census/
├── services.py     ← process_census_snapshot(), classify_bed_status(), parse_census_csv()
├── management/
│   └── commands/
│       ├── extract_census.py
│       └── process_census_snapshot.py
```text

### Modelo `Admission` (campos relevantes)

```python
class Admission(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="admissions")
    source_admission_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=100, default="tasy")
    admission_date = models.DateTimeField(null=True, blank=True)
    discharge_date = models.DateTimeField(null=True, blank=True)
    ward = models.CharField(max_length=100, blank=True, default="")
    bed = models.CharField(max_length=50, blank=True, default="")
```text

### Modelo `IngestionRun` (campos relevantes)

```python
class IngestionRun(models.Model):
    status = models.CharField(max_length=20, ...)  # queued, running, succeeded, failed
    intent = models.CharField(max_length=50, ...)  # admissions_only, full_sync, census_extraction
    parameters_json = models.JSONField(default=dict)
```text

---

## 3. Worker atual — fluxo `_process_admissions_only`

O método `_process_admissions_only` em `process_ingestion_runs.py` (linha ~200):

```python
def _process_admissions_only(self, run, *, script_path, headless):
    """Process admissions-only run: capture snapshot, no evolution extraction."""
    params = run.parameters_json or {}
    patient_record = params.get("patient_record", "")

    extractor = PlaywrightEvolutionExtractor(script_path=script_path, headless=headless)

    patient, adm_metrics = self._capture_admissions(
        run=run, extractor=extractor,
        patient_record=patient_record,
        start_date="", end_date="",
    )

    if run.status == "failed":
        return

    run.admissions_seen = adm_metrics["seen"]
    run.admissions_created = adm_metrics["created"]
    run.admissions_updated = adm_metrics["updated"]
    run.events_processed = 0
    run.status = "succeeded"
    run.finished_at = timezone.now()
    run.save()

    self.stdout.write(
        f"  Run #{run.pk} admissions-only succeeded "
        f"(admissions_seen={adm_metrics['seen']}, ...)"
    )
    # ← AQUI: adicionar auto-enfileiramento
```text

---

## 4. Objetivo do Slice

Modificar o worker para que, após concluir um `admissions_only` run com sucesso, ele detecte a admissão mais recente do paciente e enfileire automaticamente um `IngestionRun` com `intent="full_sync"`.

Isso implementa a padronização: **para cada paciente novo, o sistema captura TODAS as admissões, mas só extrai evoluções da internação atual (mais recente).**

---

## 5. O que EXATAMENTE modificar

### 5.1 Adicionar método `_enqueue_most_recent_full_sync` ao Command

Adicionar ao final da classe `Command` em `apps/ingestion/management/commands/process_ingestion_runs.py`,
antes de qualquer outro método existente (ou após o último método):

```python
    @staticmethod
    def _enqueue_most_recent_full_sync(patient, run):
        """Enqueue a full_sync run for the patient's most recent admission.

        Returns the created IngestionRun or None if no admission exists.
        """
        from apps.patients.models import Admission
        from apps.ingestion.models import IngestionRun
        from django.utils import timezone

        latest = (
            Admission.objects.filter(patient=patient)
            .order_by("-admission_date")
            .first()
        )
        if latest is None:
            return None

        # Calculate end_date: use discharge_date if available,
        # otherwise use current time (still admitted)
        if latest.discharge_date:
            end_date = latest.discharge_date.strftime("%Y-%m-%d")
        else:
            end_date = timezone.now().strftime("%Y-%m-%d")

        return IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            parameters_json={
                "patient_record": patient.patient_source_key,
                "admission_id": str(latest.pk),
                "admission_source_key": latest.source_admission_key,
                "start_date": latest.admission_date.strftime("%Y-%m-%d")
                    if latest.admission_date else "",
                "end_date": end_date,
                "intent": "full_sync",
            },
        )
```text

### 5.2 Chamar o método no final de `_process_admissions_only`

Após `run.save()` e antes do `self.stdout.write(...)`, adicionar:

```python
        # Auto-enqueue full_sync for the most recent admission
        if patient is not None:
            full_sync_run = self._enqueue_most_recent_full_sync(patient, run)
            if full_sync_run:
                self.stdout.write(
                    f"  Auto-enqueued full_sync run #{full_sync_run.pk} "
                    f"for most recent admission"
                )
```text

O local exato é logo após:

```python
    run.status = "succeeded"
    run.finished_at = timezone.now()
    run.save()

    # ← AQUI: inserir o bloco de auto-enfileiramento

    self.stdout.write(...)
```text

### 5.3 Garantir que `patient` não é None

O método `_capture_admissions` retorna `(patient, adm_metrics)`. Em caso de snapshot vazio, ele faz `Patient.objects.get_or_create(...)` e retorna o paciente. Em caso de erro, retorna `(None, ...)` e o método já faz `return` antes de chegar ao novo código. Então `patient` **sempre** será não-None quando o código chegar ao ponto de inserção.

---

## 6. Testes: `tests/unit/test_worker_auto_full_sync.py`

```python
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestWorkerAutoFullSync:
    """Test the _enqueue_most_recent_full_sync static method."""

    def _get_method(self):
        from apps.ingestion.management.commands.process_ingestion_runs import Command
        return Command._enqueue_most_recent_full_sync

    def test_enqueues_full_sync_for_single_admission(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-KEY-1",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is not None
        assert result.intent == "full_sync"
        assert result.status == "queued"
        assert result.parameters_json["patient_record"] == "12345"
        assert result.parameters_json["admission_id"] == str(admission.pk)
        assert result.parameters_json["intent"] == "full_sync"

    def test_picks_most_recent_admission(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        old = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-OLD",
            admission_date=timezone.now() - timezone.timedelta(days=30),
            discharge_date=timezone.now() - timezone.timedelta(days=20),
        )
        recent = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-RECENT",
            admission_date=timezone.now() - timezone.timedelta(days=3),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is not None
        # Should target the most recent admission
        assert result.parameters_json["admission_id"] == str(recent.pk)
        assert result.parameters_json["admission_source_key"] == "ADM-RECENT"

    def test_no_admissions_returns_none(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is None

    def test_full_sync_has_correct_end_date(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-1",
            admission_date=timezone.now() - timezone.timedelta(days=10),
            discharge_date=timezone.now() - timezone.timedelta(days=2),
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        # End date should be the discharge date
        expected_end = admission.discharge_date.strftime("%Y-%m-%d")
        assert result.parameters_json["end_date"] == expected_end

    def test_full_sync_end_date_is_today_when_still_admitted(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-1",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        # End date should be today (still admitted)
        today = timezone.now().strftime("%Y-%m-%d")
        assert result.parameters_json["end_date"] == today
```text

---

## 7. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```text

**Atenção**: garantir que TODOS os testes existentes do worker continuam passando (test_worker_lifecycle.py, test_worker_gap_planning.py, test_worker_loop_resilience.py).

---

## 8. Relatório

Gerar `/tmp/sirhosp-slice-CIS-S5-report.md`.

---

## 9. Anti-padrões PROIBIDOS

- ❌ Modificar `_process_full_sync` (não precisa mexer)
- ❌ Enfileirar full_sync quando `admissions_only` falhar
- ❌ Alterar a lógica de `_capture_admissions`
- ❌ Criar import circular (usar imports locais dentro dos métodos, como já faz o worker)
- ❌ Quebrar testes existentes do worker
