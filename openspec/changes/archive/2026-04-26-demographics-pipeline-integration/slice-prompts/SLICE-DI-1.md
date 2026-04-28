# SLICE-DI-1: Worker `demographics_only` — enfileiramento + processamento

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos
do sistema fonte hospitalar (AGHU/TASY) via web scraping (Playwright), persiste
em PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap+HTMX.

---

## 2. Estado atual do projeto (arquivos relevantes para este slice)

### 2.1 Worker existente (`process_ingestion_runs.py`)

O worker processa `IngestionRun` com base no `intent`. Hoje há dois intents:

```text
apps/ingestion/management/commands/
└── process_ingestion_runs.py
    ├── _process_run()          ← dispatcher: if intent == "admissions_only" ...
    ├── _process_admissions_only()   ← captura admissions, auto-enfileira full_sync
    ├── _process_full_sync()         ← admissions + gap planning + evolutions
    └── _capture_admissions()        ← shared admissions capture step
```

### 2.2 Função `queue_admissions_only_run()` (padrão a seguir)

Em `apps/ingestion/services.py`:

```python
def queue_admissions_only_run(
    *,
    patient_record: str,
) -> IngestionRun:
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

### 2.3 `upsert_patient_demographics()` JÁ existe e funciona

Em `apps/ingestion/services.py` (~linha 118):

```python
def upsert_patient_demographics(
    *,
    patient_source_key: str,
    source_system: str = "tasy",
    demographics: dict[str, Any],
    run: IngestionRun | None = None,
) -> Patient:
```

Esta função:

- Mapeia chaves externas (`prontuario`, `nome`, `nome_mae`, `data_nascimento`,
  `cns`, `cpf`, `logradouro`, etc.) para campos do modelo `Patient`
- Faz `get_or_create` por `(source_system, patient_source_key)`
- Campos não-vazios sobrescrevem existentes; vazios NÃO sobrescrevem
- Mudanças em CNS/CPF são registradas em `PatientIdentifierHistory`

**NÃO MODIFICAR esta função. Ela já está implementada e testada.**

### 2.4 Script Playwright de demográficos JÁ existe

`automation/source_system/patient_demographics/extract_patient_demographics.py`

Aceita CLI:

```text
python extract_patient_demographics.py \
    --patient-record 14160147 \
    --headless \
    --json-output /tmp/demo_14160147.json
```

Gera JSON com 35+ campos + `_meta`. Exemplo de saída:

```json
{
  "_meta": {
    "patient_record": "14160147",
    "extracted_at": "2026-04-26T10:30:00"
  },
  "prontuario": "14160147",
  "nome": "JOSE AUGUSTO MERCES",
  "nome_social": "",
  "sexo": "Masculino",
  "genero": "Cisgênero",
  "data_nascimento": "15/03/1965",
  "nome_mae": "MARIA MERCES",
  "nome_pai": "JOAO MERCES",
  "raca_cor": "Branca",
  "naturalidade": "Sao Paulo",
  "nacionalidade": "Brasileira",
  "estado_civil": "Casado",
  "profissao": "Motorista",
  "grau_instrucao": "Ensino Medio Completo",
  "cns": "898001234567890",
  "cpf": "12345678900",
  "ddd_fone_residencial": "11",
  "fone_residencial": "12345678",
  "logradouro": "Rua das Flores",
  "numero": "123",
  "bairro": "Centro",
  "cidade": "Sao Paulo",
  "uf": "SP",
  "cep": "01001000"
}
```

**NÃO MODIFICAR este script. Ele já funciona.**

### 2.5 Padrão de subprocess (como o `extract_census` faz)

Em `apps/census/management/commands/extract_census.py`, o script Playwright é
executado assim:

```python
script_path = Path(__file__).resolve().parents[4] / "automation" / ...

cmd = [
    sys.executable,
    str(script_path),
    "--output-dir", str(tmpdir_path),
]
if headless:
    cmd.append("--headless")

result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    timeout=1800,
)
```

---

## 3. Objetivo do Slice

Criar a infraestrutura para que o worker possa processar runs com intent
`demographics_only`: enfileirar + processar.

### 3.1 O que EXATAMENTE criar

#### A) `queue_demographics_only_run()` em `apps/ingestion/services.py`

Adicionar ao final do arquivo (antes da última linha). Segue exatamente o
padrão de `queue_admissions_only_run()`:

```python
def queue_demographics_only_run(
    *,
    patient_record: str,
) -> IngestionRun:
    """Create an IngestionRun for demographics-only extraction.

    The worker will execute the demographics Playwright script and
    persist the extracted data via upsert_patient_demographics().

    Args:
        patient_record: Patient record identifier (prontuário).

    Returns:
        IngestionRun instance with status=queued and intent='demographics_only'.
    """
    return IngestionRun.objects.create(
        status="queued",
        intent="demographics_only",
        parameters_json={
            "patient_record": patient_record,
            "intent": "demographics_only",
        },
    )
```

#### B) Método `_process_demographics_only()` no worker

Adicionar ao `process_ingestion_runs.py`. O método segue o contrato dos
métodos `_process_*` existentes:

```python
# Constante no topo do arquivo (junto com DEFAULT_SCRIPT_PATH)
DEMOGRAPHICS_SCRIPT_PATH = str(
    Path(__file__).resolve().parents[4]
    / "automation"
    / "source_system"
    / "patient_demographics"
    / "extract_patient_demographics.py"
)


def _process_demographics_only(
    self,
    run: IngestionRun,
) -> None:
    """Process demographics-only run: extract and persist patient demographics.

    Executes the demographics Playwright script as a subprocess,
    reads the JSON output, and calls upsert_patient_demographics().
    """
    import json
    import subprocess
    import sys
    import tempfile

    from apps.ingestion.services import upsert_patient_demographics

    params = run.parameters_json or {}
    patient_record = params.get("patient_record", "")

    if not patient_record:
        self._mark_run_failed(run, ValueError("Missing patient_record in parameters"))
        return

    # Stage: demographics_extraction (subprocess)
    ext_stage_start = timezone.now()

    with tempfile.TemporaryDirectory() as tmpdir:
        json_output_path = Path(tmpdir) / "demographics_output.json"

        cmd = [
            sys.executable,
            DEMOGRAPHICS_SCRIPT_PATH,
            "--patient-record", patient_record,
            "--headless",
            "--json-output", str(json_output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes max for single-patient extraction
            )
        except subprocess.TimeoutExpired as exc:
            self._record_stage(
                run=run,
                stage_name="demographics_extraction",
                status="failed",
                started_at=ext_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return
        except Exception as exc:
            self._record_stage(
                run=run,
                stage_name="demographics_extraction",
                status="failed",
                started_at=ext_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        if result.returncode != 0:
            err_msg = f"Exit code {result.returncode}: {result.stderr[:500]}"
            self._record_stage(
                run=run,
                stage_name="demographics_extraction",
                status="failed",
                started_at=ext_stage_start,
                details_json={"returncode": result.returncode},
            )
            run.status = "failed"
            run.error_message = err_msg
            run.finished_at = timezone.now()
            run.failure_reason = "source_unavailable"
            run.timed_out = False
            run.save()
            return

        # Stage: demographics_extraction succeeded
        self._record_stage(
            run=run,
            stage_name="demographics_extraction",
            status="succeeded",
            started_at=ext_stage_start,
        )

        # Read JSON output
        if not json_output_path.exists():
            self._mark_run_failed(
                run,
                ValueError(f"JSON output not found at {json_output_path}"),
            )
            return

        try:
            demographics_data = json.loads(
                json_output_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            self._mark_run_failed(run, exc)
            return

    # Stage: demographics_persistence (upsert)
    persist_stage_start = timezone.now()
    try:
        patient = upsert_patient_demographics(
            patient_source_key=patient_record,
            source_system="tasy",
            demographics=demographics_data,
            run=run,
        )
    except Exception as exc:
        self._record_stage(
            run=run,
            stage_name="demographics_persistence",
            status="failed",
            started_at=persist_stage_start,
            details_json=self._stage_error_details(exc),
        )
        self._mark_run_failed(run, exc)
        return

    self._record_stage(
        run=run,
        stage_name="demographics_persistence",
        status="succeeded",
        started_at=persist_stage_start,
    )

    # Count how many fields were populated (non-empty after upsert)
    fields_populated = sum(
        1
        for field_name in [
            "name", "social_name", "date_of_birth", "gender",
            "gender_identity", "mother_name", "father_name",
            "race_color", "birthplace", "nationality",
            "marital_status", "education_level", "profession",
            "cns", "cpf", "phone_home", "phone_cellular",
            "phone_contact", "street", "address_number",
            "address_complement", "neighborhood", "city",
            "state", "postal_code",
        ]
        if getattr(patient, field_name, None)
    )

    # Success
    run.status = "succeeded"
    run.finished_at = timezone.now()
    run.failure_reason = ""
    run.timed_out = False
    # Store demographics metrics in parameters_json
    run.parameters_json = {
        **params,
        "demographics_fields_extracted": fields_populated,
    }
    run.save()

    self.stdout.write(
        f"  Run #{run.pk} demographics_only succeeded "
        f"(fields_populated={fields_populated})"
    )
```

#### C) Branch no `_process_run()` dispatcher

No método `_process_run()`, adicionar a branch para `demographics_only`.
O dispatcher atual é:

```python
def _process_run(self, run, *, script_path, headless):
    params = run.parameters_json or {}
    intent = params.get("intent", "") or run.intent

    run.status = "running"
    if run.processing_started_at is None:
        run.processing_started_at = timezone.now()
    run.save(update_fields=["status", "processing_started_at"])

    if intent == "admissions_only":
        self._process_admissions_only(...)
    else:
        self._process_full_sync(...)
```

**Adicionar** `elif intent == "demographics_only"` **antes** do `else`:

```python
    if intent == "admissions_only":
        self._process_admissions_only(
            run=run, script_path=script_path, headless=headless,
        )
    elif intent == "demographics_only":
        self._process_demographics_only(run=run)
    else:
        self._process_full_sync(
            run=run, script_path=script_path, headless=headless,
        )
```

---

## 4. Testes: `tests/unit/test_demographics_worker.py`

Criar arquivo NOVO com os testes abaixo. **IMPORTANTE**: usar
`unittest.mock.patch` para mockar `subprocess.run` e evitar execução real
do Playwright.

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.ingestion.services import queue_demographics_only_run
from apps.patients.models import Patient


@pytest.mark.django_db
class TestQueueDemographicsOnlyRun:
    """Tests for queue_demographics_only_run()."""

    def test_creates_run_with_correct_intent(self):
        """queue_demographics_only_run creates IngestionRun with
        intent='demographics_only'."""
        run = queue_demographics_only_run(patient_record="12345")

        assert run.status == "queued"
        assert run.intent == "demographics_only"
        assert run.parameters_json["patient_record"] == "12345"
        assert run.parameters_json["intent"] == "demographics_only"

    def test_creates_run_with_empty_record(self):
        """Empty patient_record is still enqueued (validation in worker)."""
        run = queue_demographics_only_run(patient_record="")
        assert run.status == "queued"
        assert run.parameters_json["patient_record"] == ""


@pytest.mark.django_db
class TestProcessDemographicsOnly:
    """Tests for _process_demographics_only() worker method.

    All tests mock subprocess.run to avoid real Playwright execution.
    """

    SCRIPT_PATH = (
        Path(__file__).resolve().parents[3]
        / "automation"
        / "source_system"
        / "patient_demographics"
        / "extract_patient_demographics.py"
    )

    DEMOGRAPHICS_JSON = {
        "_meta": {"patient_record": "14160147",
                   "extracted_at": "2026-01-01T00:00:00"},
        "prontuario": "14160147",
        "nome": "JOSE AUGUSTO MERCES",
        "nome_social": "",
        "sexo": "Masculino",
        "genero": "Cisgênero",
        "data_nascimento": "15/03/1965",
        "nome_mae": "MARIA MERCES",
        "nome_pai": "JOAO MERCES",
        "raca_cor": "Branca",
        "naturalidade": "Sao Paulo",
        "nacionalidade": "Brasileira",
        "estado_civil": "Casado",
        "profissao": "Motorista",
        "grau_instrucao": "Ensino Medio Completo",
        "cns": "898001234567890",
        "cpf": "12345678900",
        "ddd_fone_residencial": "11",
        "fone_residencial": "12345678",
        "logradouro": "Rua das Flores",
        "numero": "123",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "cep": "01001000",
    }

    def _create_queued_run(self, patient_record="14160147"):
        """Helper: create a queued demographics_only run."""
        return IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        )

    def _mock_subprocess_success(self, mock_run, json_data=None):
        """Configure mock subprocess.run to simulate success."""
        data = json_data or self.DEMOGRAPHICS_JSON

        def _side_effect(cmd, **kwargs):
            # Write JSON to the --json-output path
            for i, arg in enumerate(cmd):
                if arg == "--json-output" and i + 1 < len(cmd):
                    output_path = Path(cmd[i + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        json.dumps(data, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    break
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _side_effect

    def _mock_subprocess_failure(self, mock_run, returncode=1,
                                  stderr="Script error"):
        """Configure mock subprocess.run to simulate failure."""
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = stderr
        mock_run.return_value = result

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    @patch("subprocess.run")
    def test_successful_extraction_creates_patient(self, mock_run):
        """Successful demographics extraction → Patient created with
        full data."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.failure_reason == ""

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "JOSE AUGUSTO MERCES"
        assert patient.mother_name == "MARIA MERCES"
        assert patient.cns == "898001234567890"
        assert patient.cpf == "12345678900"
        assert patient.city == "Sao Paulo"

    @patch("subprocess.run")
    def test_successful_extraction_updates_existing_patient(self, mock_run):
        """Existing patient gets demographic data updated."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        # Create patient with minimal data first (simulating census creation)
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
            # All other fields empty
        )

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "succeeded"

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        # Name was updated from census name
        assert patient.name == "JOSE AUGUSTO MERCES"
        # New fields populated
        assert patient.mother_name == "MARIA MERCES"
        assert patient.cpf == "12345678900"

    @patch("subprocess.run")
    def test_subprocess_timeout_fails_run(self, mock_run):
        """Timeout → run failed with timeout reason."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["python", "script.py"], timeout=300
        )

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True

    @patch("subprocess.run")
    def test_subprocess_nonzero_exit_fails_run(self, mock_run):
        """Non-zero exit code → run failed."""
        self._mock_subprocess_failure(mock_run, returncode=1,
                                       stderr="Connection refused")

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "source_unavailable"

    @patch("subprocess.run")
    def test_invalid_json_output_fails_run(self, mock_run):
        """Invalid JSON in output file → run failed."""
        self._mock_subprocess_success(mock_run, json_data=None)

        # Override side_effect to write invalid JSON
        def _side_effect(cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "--json-output" and i + 1 < len(cmd):
                    output_path = Path(cmd[i + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text("not valid json {{{", encoding="utf-8")
                    break
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _side_effect

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"

    @patch("subprocess.run")
    def test_missing_patient_record_fails_early(self, mock_run):
        """Missing patient_record in parameters → fail without subprocess."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={"intent": "demographics_only"},
            # No patient_record
        )

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        # subprocess.run should NOT have been called
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_stage_metrics_recorded_on_success(self, mock_run):
        """Stage metrics are created for successful demographics extraction."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )
        from apps.ingestion.models import IngestionRunStageMetric

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        stages = IngestionRunStageMetric.objects.filter(run=run)
        stage_names = {s.stage_name for s in stages}
        assert "demographics_extraction" in stage_names
        assert "demographics_persistence" in stage_names

        ext_stage = stages.get(stage_name="demographics_extraction")
        assert ext_stage.status == "succeeded"

        persist_stage = stages.get(stage_name="demographics_persistence")
        assert persist_stage.status == "succeeded"
```

---

## 5. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

Opcional (se typecheck não quebrar por causas externas):

```bash
./scripts/test-in-container.sh typecheck
```

---

## 6. Relatório

Gerar `/tmp/sirhosp-slice-DI-1-report.md` com:

- Resumo do slice (1 parágrafo)
- Checklist de aceite (todos os checkboxes do tasks.md para DI-1)
- Lista de arquivos alterados (com paths absolutos)
- **Fragmentos de código ANTES/DEPOIS** por arquivo alterado
- Comandos executados e resultados (stdout resumido)
- Riscos, pendências e próximo passo sugerido

---

## 7. Anti-padrões PROIBIDOS

- ❌ Não modificar `upsert_patient_demographics()` nem o script Playwright
- ❌ Não executar Playwright real nos testes (usar `@patch("subprocess.run")`)
- ❌ Não usar `print()` no management command (usar `self.stdout.write()`)
- ❌ Não criar `Patient` com `source_system` diferente de `"tasy"`
- ❌ Não alterar `_process_admissions_only` ou `_process_full_sync`
- ❌ Não quebrar os testes existentes de `test_process_census_snapshot.py`
