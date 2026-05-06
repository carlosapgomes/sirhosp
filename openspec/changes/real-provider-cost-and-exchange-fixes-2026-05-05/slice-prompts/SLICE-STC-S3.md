# SLICE STC-S3 — Fase 1: custo cumulativo por chunk

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/proposal.md`
4. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/design.md`
5. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/tasks.md`
6. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/specs/real-provider-cost/spec.md`
7. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/specs/admission-progressive-summary/spec.md`
8. `/tmp/sirhosp-slice-STC-S1-report.md` (contrato de parsing descoberto)
9. `/tmp/sirhosp-slice-STC-S2-report.md` (resultado da fase 2)
10. este arquivo `SLICE-STC-S3.md`

## Objetivo

Capturar tokens e custo real por chunk durante a Fase 1 (`execute_summary_run`),
persistir em cada `AdmissionSummaryVersion`, e acumular no `SummaryPipelineRun`
para que o custo da Fase 1 deixe de ser zero.

## Contexto técnico

- `call_llm_gateway` (fase 1) chama o LLM mas hoje não retorna tokens nem custo
  — só conteúdo + `_meta` (provider/model).
- `execute_summary_run` processa chunks e cria `AdmissionSummaryVersion` sem
  `input_tokens` e `output_tokens`.
- `execute_two_phase_pipeline` soma tokens dos versions e calcula custo com
  tabela fixa. Como os tokens são None, o custo sempre é zero.
- O mesmo provider (OpenRouter) usado na fase 1 retorna `usage.cost` —
  mesma extração do Slice S2, via `getattr(completion.usage, 'cost', None)`.

## Escopo permitido (máx 8 arquivos)

- `apps/summaries/llm_gateway.py` — `call_llm_gateway` retornar tokens + custo
- `apps/summaries/models.py` — `AdmissionSummaryVersion` ganhar campos de custo
- `apps/summaries/migrations/*` — nova migração
- `apps/summaries/services.py` — `execute_summary_run` persistir;
  `execute_two_phase_pipeline` acumular
- `tests/unit/test_phase1_cost.py` — testes unitários novos
- `tests/unit/test_phase1_gateway.py` — (se necessário)
- `tests/integration/test_summary_two_phase_orchestration.py` — ajustar stubs

## Escopo proibido

- Não mexer na Fase 2 (código do Slice STC-S2 é intocável).
- Não mexer nos providers de câmbio (Slice STC-S5).
- Não mexer na UI de transparência (Slice STC-S6).

## Estratégia de execução (TDD)

1. **RED:** testes unitários para `call_llm_gateway` retornando tokens + custo.
2. **RED:** teste unitário para `_compute_phase1_cost_from_tokens` com
   múltiplos chunks.
3. **GREEN:** alterar `call_llm_gateway` para extrair e retornar tokens e custo.
4. **GREEN:** migration para `input_tokens`, `output_tokens`,
   `cost_usd_reported`, `cost_usd_estimated` em `AdmissionSummaryVersion`.
5. **GREEN:** `execute_summary_run` persistindo tokens e custo por version.
6. **GREEN:** `execute_two_phase_pipeline` acumulando custo da fase 1.
7. **REFACTOR:** revisar consistência.

## Critérios de sucesso

- `call_llm_gateway` retorna `input_tokens`, `output_tokens`,
  `cost_usd_reported`, `cost_usd_estimated` em cada chamada.
- `AdmissionSummaryVersion` armazena `input_tokens`, `output_tokens`,
  `cost_usd_reported`, `cost_usd_estimated` por chunk.
- `execute_two_phase_pipeline` soma `cost_usd_reported` de todos os versions
  para `phase1_cost_total`.
- Run com 3 chunks no banco mostra `phase1_cost_total > 0` (quando há custo
  real do provider).
- Pipeline existente no banco continua funcional após migration.
- Testes de integração de orquestração passam com custo de fase 1 correto.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STC-S3-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STC-S3-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STC-S4`.
