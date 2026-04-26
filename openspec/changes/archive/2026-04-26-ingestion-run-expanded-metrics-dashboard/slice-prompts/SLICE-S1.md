# SLICE-S1 — Contrato base de lifecycle no `IngestionRun`

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-observability/spec.md`
7. este arquivo `slice-prompts/SLICE-S1.md`

## Pré-condição de branch

```bash
git checkout -b feature/ingestion-run-expanded-metrics-dashboard
```

Se a branch já existir:

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Decisões congeladas para este change

- `started_at` permanece por compatibilidade legada.
- Neste slice, expandir apenas `IngestionRun` (sem estágio 1:N ainda).
- Novos campos alvo:
  - `queued_at`
  - `processing_started_at`
  - `failure_reason`
  - `timed_out`
  - `worker_label`

## Objetivo do slice

Expandir o modelo `IngestionRun` com campos de observabilidade de lifecycle e falha, com migração compatível e testes de unidade para defaults e cálculos de duração.

## Escopo permitido (somente)

- `apps/ingestion/models.py`
- `apps/ingestion/migrations/*` (somente a nova migração)
- `tests/unit/test_ingestion_run_metrics_model.py` (novo)

## Escopo proibido

- worker (`process_ingestion_runs.py`)
- command de censo
- views/templates
- admin

## Limite de alteração

Máximo: **4 arquivos**.

## Requisitos funcionais do slice

1. Adicionar campos novos no `IngestionRun` com defaults seguros e sem quebrar criação existente.
2. Garantir que `queued_at` represente enfileiramento/criação do run.
3. `processing_started_at` deve ser opcional (`null=True`, `blank=True`).
4. `failure_reason` deve aceitar vazio por padrão.
5. `timed_out` deve iniciar como `False`.
6. `worker_label` opcional para diagnóstico operacional.
7. Adicionar helpers no modelo para durações (fila, execução, total) retornando `None` quando dados insuficientes.

## TDD obrigatório

1. **RED**: criar testes do modelo cobrindo defaults e helpers de duração.
2. **GREEN**: implementar campos/métodos até testes passarem.
3. **REFACTOR**: limpar nomes e duplicações sem ampliar escopo.

## Gates obrigatórios S1

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S1-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S2).

Pare ao concluir.
