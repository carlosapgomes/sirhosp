# Tasks: demographics-pipeline-integration

## 1. Slice DI-1 — Worker `demographics_only`: enfileiramento + processamento

Escopo: criar `queue_demographics_only_run()` e o handler
`_process_demographics_only()` no worker.

Limite: até **4 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-DI-1.md`.

- [x] 1.1 Criar `queue_demographics_only_run()` em `apps/ingestion/services.py`
- [x] 1.2 Criar método `_process_demographics_only()` em `process_ingestion_runs.py`
      — executa `extract_patient_demographics.py` como subprocess,
      lê JSON de saída, chama `upsert_patient_demographics()`
- [x] 1.3 Adicionar branch `demographics_only` no `_process_run()` dispatcher
- [x] 1.4 (RED) Criar `tests/unit/test_demographics_worker.py`: - `queue_demographics_only_run` cria `IngestionRun` com intent correto - `_process_demographics_only` com mock de subprocess bem-sucedido - `_process_demographics_only` com mock de subprocess falho (timeout) - `_process_demographics_only` com mock de subprocess falho (exit code ≠ 0) - `_process_demographics_only` com mock de subprocess falho (JSON inválido) - `_process_demographics_only` com paciente inexistente (get_or_create) - `_process_demographics_only` com paciente existente (update)
- [x] 1.5 **Gate DI-1**: `./scripts/test-in-container.sh check unit lint`
- [x] 1.6 Gerar `/tmp/sirhosp-slice-DI-1-report.md`

## 2. Slice DI-2 — Integrar `demographics_only` no `process_census_snapshot`

Escopo: adicionar enfileiramento de `demographics_only` no processador de
censo e atualizar testes existentes.

Limite: até **3 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-DI-2.md`.

- [x] 2.1 Modificar `process_census_snapshot()` em `apps/census/services.py`: - Importar `queue_demographics_only_run` - Adicionar chamada `queue_demographics_only_run(patient_record=prontuario)`
      no loop de pacientes (ao lado do `queue_admissions_only_run` existente) - Adicionar `demographics_runs_enqueued` ao dict de retorno
- [x] 2.2 (RED) Atualizar `tests/unit/test_process_census_snapshot.py`: - `test_new_patient_enqueues_demographics_run`: verificar
      `IngestionRun` com `intent="demographics_only"` e `status="queued"` - `test_existing_patient_also_enqueues_demographics_run` - `test_demographics_count_in_return_dict`: métrica `demographics_runs_enqueued`
      presente e correta - Garantir que todos os testes existentes continuam passando
- [x] 2.3 **Gate DI-2**: `./scripts/test-in-container.sh check unit lint`
- [x] 2.4 Gerar `/tmp/sirhosp-slice-DI-2-report.md`

## Stop Rule

- Implementar **um slice por vez**.
- Cada slice com ciclo TDD (red → green → refactor).
- Ao concluir um slice, parar e aguardar decisão explícita para o próximo.
- Relatório obrigatório em `/tmp/sirhosp-slice-<ID>-report.md` com:
  - resumo do slice
  - checklist de aceite
  - lista de arquivos alterados
  - fragmentos de código antes/depois por arquivo alterado
  - comandos executados e resultados
  - riscos, pendências e próximo passo sugerido
