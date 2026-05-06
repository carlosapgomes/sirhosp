# SLICE STC-S2 — Fase 2: custo real do provider (com fallback)

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/proposal.md`
4. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/design.md`
5. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/tasks.md`
6. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/specs/real-provider-cost/spec.md`
7. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/specs/summary-llm-traceability/spec.md`
8. `/tmp/sirhosp-slice-STC-S1-report.md` (contrato de parsing descoberto)
9. este arquivo `SLICE-STC-S2.md`

## Objetivo

Alterar `call_llm_phase2_render` para extrair o custo real faturado em USD
da resposta do provider (OpenRouter), com fallback para estimativa por tokens
quando o provider não retornar custo.

## Contexto técnico (do Slice S1)

OpenRouter retorna custo em `completion.usage.cost` (float, USD).
Acesso: `getattr(completion.usage, 'cost', None)`.
Conversão para Decimal: `Decimal(str(cost))`.

O campo `cost` está em `model_extra` do Pydantic (não em `model_fields`),
então `getattr` é a forma segura.

## Escopo permitido (máx 8 arquivos)

- `apps/summaries/llm_gateway.py` — alterar `call_llm_phase2_render`
- `apps/summaries/models.py` — migration via Django (campos novos em `SummaryPipelineStepRun`)
- `apps/summaries/migrations/*` — nova migração
- `apps/summaries/services.py` — `execute_two_phase_pipeline` (persistir novos campos)
- `apps/summaries/views.py` — ajustar leitura dos campos (se quebrar interface)
- `apps/summaries/templates/summaries/run_status.html` — (se necessário)
- `tests/unit/test_phase2_cost.py` — testes unitários novos
- `tests/integration/test_summary_two_phase_orchestration.py` — ajustar stubs + novos testes

## Escopo proibido

- Não mexer na Fase 1 (Slice STC-S3).
- Não mexer nos providers de câmbio (Slice STC-S5).
- Não mexer na UI de transparência (Slice STC-S6).

## Estratégia de execução (TDD)

1. **RED:** testes unitários para `call_llm_phase2_render` com custo real
   e sem custo (fallback).
2. **GREEN:** alterar `call_llm_phase2_render` para extrair
   `cost_usd_reported`.
3. **GREEN:** migration para novos campos em `SummaryPipelineStepRun`.
4. **GREEN:** `execute_two_phase_pipeline` persistindo novos campos.
5. **REFACTOR:** revisar consistência.

## Critérios de sucesso

- `call_llm_phase2_render` retorna `cost_usd_reported` (real) e
  `cost_usd_estimated` (estimado).
- `cost_usd_reported` é extraído de `completion.usage.cost` quando
  disponível.
- `cost_usd_reported` é `0.00` quando provider não retorna custo.
- `SummaryPipelineStepRun` persiste `cost_usd_reported` e
  `cost_usd_estimated`.
- `SummaryPipelineRun.phase2_cost_total` usa `cost_usd_reported`
  (fallback para `cost_usd_estimated` quando real ausente).
- Pipeline existente no banco continua funcional após migration.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STC-S2-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STC-S2-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STC-S3`.
