# SLICE-S3 — Métricas por estágio (`IngestionRunStageMetric`)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-observability/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S2-report.md`
8. este arquivo `slice-prompts/SLICE-S3.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Criar modelo 1:N para estágios do run e instrumentar o worker para persistir estágios críticos com status e timestamps.

## Escopo permitido (somente)

- `apps/ingestion/models.py`
- `apps/ingestion/migrations/*` (somente a nova migração)
- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `tests/integration/test_worker_lifecycle.py`

## Escopo proibido

- command de censo
- views/templates
- admin

## Limite de alteração

Máximo: **4 arquivos**.

## Requisitos funcionais do slice

1. Criar modelo `IngestionRunStageMetric` relacionado a `IngestionRun`.
2. Campos mínimos obrigatórios por estágio:
   - `stage_name`
   - `started_at`
   - `finished_at`
   - `status` (`succeeded|failed|skipped`)
   - `details_json` (opcional, default dict)
3. Worker deve persistir estágios para:
   - `admissions_capture`
   - `gap_planning`
   - `evolution_extraction`
   - `ingestion_persistence`
4. Quando não houver extração por cobertura completa, registrar `evolution_extraction` como `skipped`.
5. Em falha de estágio, registrar estágio `failed` antes do `run.failed`.

## TDD obrigatório

1. **RED**: testes de integração cobrindo estágio em sucesso, falha e skip.
2. **GREEN**: implementar modelo + instrumentação mínima até testes passarem.
3. **REFACTOR**: reduzir duplicação com helper de registro de estágio.

## Gates obrigatórios S3

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh integration`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S3-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S4).

Pare ao concluir.
