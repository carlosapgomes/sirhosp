# SLICE STP-S9 — Status/leitura com custos por fase + hardening final

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/summary-llm-traceability/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-STP-S9.md`

## Objetivo

Exibir custos por fase no status/leitura final (USD/BRL), aplicar fallback
seguro de cotação e consolidar evidências finais da change.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/views.py`
- `apps/summaries/templates/summaries/run_status.html`
- `apps/summaries/templates/summaries/summary_read.html`
- `tests/integration/test_summary_cost_visibility_http.py`
- `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/*`
  (somente ajustes documentais finais se estritamente necessários)

## Escopo proibido

- novos modelos/migrations;
- mudanças arquiteturais fora do slice;
- avanço para nova feature não planejada.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes de visibilidade de custo no status e leitura.
2. **GREEN:** implementar contexto + templates + fallback.
3. **REFACTOR:** simplificar lógica de apresentação de custos.

## Critérios de sucesso

- status mostra custo fase1/fase2/total em USD e BRL;
- leitura final mostra custo total e indicador de reuso da fase 1;
- fallback robusto quando custos/tokens/cotação não existirem;
- quality gate completo verde no fim do slice.

## Gates obrigatórios

- `./scripts/test-in-container.sh quality-gate`
- `./scripts/markdown-lint.sh`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S9-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S9-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não iniciar nenhuma nova change/slice.
