# SLICE STP-S1 — Modelo de dados de pipeline e rastreabilidade

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/summary-llm-traceability/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-STP-S1.md`

## Objetivo

Criar os modelos base de rastreabilidade do pipeline de duas fases com custos
em USD e snapshots completos de prompt/payload.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/models.py`
- `apps/summaries/migrations/*` (somente nova migração)
- `apps/summaries/admin.py`
- `tests/unit/test_summary_pipeline_models.py`

## Escopo proibido

- views/templates;
- comandos de management;
- services de orquestração;
- mudanças fora de `apps/summaries` + teste unitário do slice.

## Estratégia de execução (TDD + clean code)

1. **RED:** escrever testes para os novos modelos e relações.
2. **GREEN:** implementar mínimo necessário para os testes passarem.
3. **REFACTOR:** melhorar nomes/cohesão sem ampliar escopo.

Aplicar clean code: funções pequenas, nomes explícitos, sem duplicação.

## Critérios de sucesso

- `SummaryPipelineRun` criado com custos fase1/fase2/total e `currency='USD'`.
- `SummaryPipelineStepRun` criado com dados de fase, prompt snapshot e payloads.
- Relação `pipeline_run -> step_runs` funcionando.
- Migração consistente e admin registrando os novos modelos.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S1-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S1-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S2`.
