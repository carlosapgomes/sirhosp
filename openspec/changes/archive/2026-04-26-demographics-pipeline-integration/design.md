# Design: demographics-pipeline-integration

## Context

O SIRHOSP possui três ativos já implementados e testados que não estão
conectados ao pipeline operacional:

- **Script Playwright de extração demográfica** — em
  `automation/source_system/patient_demographics/extract_patient_demographics.py`
  — ✅ Funcional, aceita `--patient-record`, `--json-output`, `--headless`
- **Função de upsert** — `apps/ingestion/services.py::upsert_patient_demographics()`
  — ✅ Implementada com 20+ testes unitários
- **Modelo Patient completo** — `apps/patients/models.py`
  — ✅ 30+ campos incluindo `mother_name`, `date_of_birth`, `cns`, `cpf`, etc.

O pipeline atual (`process_census_snapshot` → worker) só popula `Patient.name`.
Este change conecta os três ativos ao pipeline.

## Design Goals

1. **Mínimo de arquivos alterados** — o script Playwright e a função de upsert
   não precisam de alteração.
2. **Padrão de subprocess existente** — mesmo contrato do `extract_census`:
   `subprocess.run()` com `sys.executable`, `capture_output=True`, timeout.
3. **Intent independente** — `demographics_only` é um intent separado de
   `admissions_only` e `full_sync`, processado pelo mesmo worker.
4. **Enfileiramento automático** — `process_census_snapshot()` enfileira
   ambos os intents para cada paciente.
5. **Falha não bloqueante** — se `demographics_only` falhar, o paciente
   continua existindo (com `name` apenas) e a run fica com `status=failed`
   para diagnóstico.

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│ systemd timer (3x/day)                                      │
│   │                                                         │
│   ├──▶ manage.py extract_census                             │
│   │      └──▶ CensusSnapshot (setor, leito, prontuario,     │
│   │              nome, especialidade)                        │
│   │                                                         │
│   └──▶ manage.py process_census_snapshot                    │
│          │                                                  │
│          ├──▶ Patient.objects.get_or_create(name=...)       │
│          │                                                  │
│          ├──▶ queue_admissions_only_run()     ← já existe   │
│          │                                                  │
│          └──▶ queue_demographics_only_run()   ← NOVO         │
│                                                              │
│ Worker: process_ingestion_runs --loop                        │
│   │                                                         │
│   ├──▶ _process_admissions_only()  (existente)              │
│   │                                                         │
│   ├──▶ _process_full_sync()        (existente)              │
│   │                                                         │
│   └──▶ _process_demographics_only()  (NOVO)                 │
│          │                                                  │
│          ├──▶ subprocess: extract_patient_demographics.py   │
│          │    --patient-record=<prontuario>                 │
│          │    --headless                                     │
│          │    --json-output=<tmpfile>                        │
│          │                                                  │
│          ├──▶ Lê JSON de saída                              │
│          │                                                  │
│          └──▶ upsert_patient_demographics(                  │
│                 patient_source_key=<prontuario>,            │
│                 demographics=<json_data>,                   │
│                 run=<ingestion_run>                          │
│               )                                             │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Intent separado `demographics_only`

**Decisão**: criar um intent independente em vez de embutir a extração
demográfica no `admissions_only` ou `full_sync`.

**Racional**:

- Mantém responsabilidade única por intent.
- Permite reprocessar demográficos sem reexecutar admissions.
- Falha de demográficos não bloqueia admissions (crítico).
- Facilita backfill futuro de pacientes existentes.

### 2. Subprocess (não import Python)

**Decisão**: executar `extract_patient_demographics.py` como subprocess,
igual ao `extract_census.py`.

**Racional**:

- O script Playwright depende de `playwright.sync_api` que inicia um
  event loop próprio — importar diretamente no worker Django causaria
  conflito.
- O script já é autocontido com `argparse`, `.env` via `dotenv`, e
  saída JSON.
- Padrão já validado no `extract_census`.

### 3. Política de overwrite (delegação)

**Decisão**: delegar toda a política de overwrite para
`upsert_patient_demographics()`, que já implementa:

- `get_or_create` por `(source_system, patient_source_key)`
- Campos não-vazios sobrescrevem existentes
- Campos vazios NÃO sobrescrevem dados existentes
- Mudanças em CNS/CPF registradas em `PatientIdentifierHistory`

**Racional**: a função já existe, está testada e cobre todos os casos.

### 4. Métricas enriquecidas em `process_census_snapshot`

**Decisão**: adicionar `demographics_runs_enqueued` ao dict de retorno.

**Racional**: visibilidade operacional — permite ao operador confirmar que
ambas as runs foram enfileiradas.

## Componentes alterados

### `apps/ingestion/services.py`

Adicionar:

```python
def queue_demographics_only_run(
    *,
    patient_record: str,
) -> IngestionRun:
    """Create an IngestionRun for demographics-only extraction."""
    return IngestionRun.objects.create(
        status="queued",
        intent="demographics_only",
        parameters_json={
            "patient_record": patient_record,
            "intent": "demographics_only",
        },
    )
```

### `apps/census/services.py`

Modificar `process_census_snapshot()`:

- Adicionar import de `queue_demographics_only_run`
- Dentro do loop de pacientes, após `queue_admissions_only_run()`:
  chamar `queue_demographics_only_run(patient_record=prontuario)`
- Adicionar chave `demographics_runs_enqueued` ao dict de retorno

### `apps/ingestion/management/commands/process_ingestion_runs.py`

Adicionar:

1. Constante `DEMOGRAPHICS_SCRIPT_PATH` apontando para o script Playwright
2. Método `_process_demographics_only()` seguindo o contrato de
   `_process_admissions_only()`:
   - Cria estágio `demographics_extraction`
   - Executa subprocess com `--patient-record`, `--headless`, `--json-output`
   - Lê JSON de saída
   - Chama `upsert_patient_demographics()`
   - Registra métricas e transiciona run
3. No `_process_run()`, adicionar branch `elif intent == "demographics_only"`

## Riscos e Mitigações

### Risco: script de scraping quebrar por mudança de UI

Mitigação: mesmo padrão do `extract_census.py` — subprocess com
`capture_output`, timeout, e `failure_reason` normalizado.

### Risco: volume de runs sobrecarregar o sistema fonte

Mitigação: o worker já processa sequencialmente com throttling natural.
2 intents por paciente (~340 runs/dia com ~170 pacientes) é viável com
o worker atual.

### Risco: paciente criado pelo censo mas demográficos falham

Mitigação: paciente continua existindo com `name` apenas. A run fica
`failed` para diagnóstico. O operador pode reenfileirar manualmente.

## Validation Strategy

- **Unit tests**: `queue_demographics_only_run()`, `_process_demographics_only()`
  com mock de subprocess, métricas de `process_census_snapshot()`
- **Integration tests**: worker lifecycle com intent `demographics_only`
- **Gates**: `check`, `unit`, `lint`, `typecheck` em container
