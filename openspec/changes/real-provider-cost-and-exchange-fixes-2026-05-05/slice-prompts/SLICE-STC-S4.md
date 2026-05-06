# SLICE STC-S4 — Vínculo PipelineRun → SummaryRun

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/proposal.md`
4. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/design.md`
5. `openspec/changes/real-provider-cost-and-exchange-fixes-2026-05-05/tasks.md`
6. `/tmp/sirhosp-slice-STC-S1-report.md`
7. `/tmp/sirhosp-slice-STC-S2-report.md`
8. `/tmp/sirhosp-slice-STC-S3-report.md`
9. este arquivo `SLICE-STC-S4.md`

## Objetivo

Vincular `SummaryPipelineRun` ao `SummaryRun` que o originou via FK explícita,
eliminando o risco de a UI mostrar custo do run errado quando há múltiplos
runs da mesma internação.

## Contexto técnico

Hoje as views `run_status` e `summary_read` buscam `SummaryPipelineRun`
filtrando por `admission=run.admission`, pegando o mais recente. Isso pode
vazar custo entre runs distintos da mesma admissão. A solução é adicionar
`summary_run = ForeignKey(SummaryRun, null=True)` e consultar por ele.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/models.py` — FK `summary_run` em `SummaryPipelineRun`
- `apps/summaries/migrations/*` — nova migração
- `apps/summaries/services.py` — preencher FK ao criar pipeline
- `apps/summaries/views.py` — consultar por `summary_run=run`
- `tests/integration/test_summary_cross_run_isolation.py` — teste HTTP

## Escopo proibido

- Não mexer em templates (Slice STC-S6).
- Não mexer em providers de câmbio (Slice STC-S5).
- Não alterar lógica de custo (já concluída em S2/S3).

## Estratégia de execução

1. Adicionar FK `summary_run` ao modelo + migration.
2. Preencher `summary_run` em `execute_two_phase_pipeline`.
3. Alterar views para consultar por `summary_run=run`.
4. Teste de integração HTTP: 2 runs mesma admissão → custo isolado.

## Critérios de sucesso

- `SummaryPipelineRun` tem FK `summary_run` (nullable).
- Pipeline criado por `execute_two_phase_pipeline` preenche `summary_run`.
- `run_status` consulta pipeline por `summary_run=run`.
- `summary_read` consulta pipeline por `summary_run=run`.
- Teste HTTP confirma isolamento de custo entre 2 runs.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STC-S4-report.md`
