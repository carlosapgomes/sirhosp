# SLICE-S2 — Instrumentação do worker e taxonomia de falha

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-observability/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S1-report.md`
8. este arquivo `slice-prompts/SLICE-S2.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Instrumentar `process_ingestion_runs` para preencher lifecycle (`processing_started_at`, `finished_at`) e classificar falhas de forma determinística em `failure_reason` + `timed_out`.

## Escopo permitido (somente)

- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `tests/integration/test_worker_lifecycle.py`
- `tests/integration/test_worker_gap_planning.py` (apenas se necessário para regressão)

## Escopo proibido

- models/migrations
- tabela de estágio 1:N
- views/templates
- admin

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. Ao iniciar processamento real de run, preencher `processing_started_at` (uma única vez por run).
2. Em sucesso terminal, preencher `finished_at` e limpar estado de falha (`failure_reason=""`, `timed_out=False`).
3. Em falha terminal, preencher `finished_at` e classificar `failure_reason`.
4. Taxonomia obrigatória (string normalizada):
   - `timeout`
   - `source_unavailable`
   - `invalid_payload`
   - `validation_error`
   - `unexpected_exception`
5. Em timeout: `timed_out=True` e `failure_reason="timeout"`.
6. Preservar comportamento já validado de estados (`queued -> running -> succeeded|failed`).

## TDD obrigatório

1. **RED**: adicionar/ajustar testes em `test_worker_lifecycle.py` para lifecycle + classificação de falha.
2. **GREEN**: implementar mapeamento e preenchimento de campos até os testes passarem.
3. **REFACTOR**: extrair helper interno para classificação de exceção sem ampliar escopo.

## Gates obrigatórios S2

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh integration`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S2-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S3).

Pare ao concluir.
