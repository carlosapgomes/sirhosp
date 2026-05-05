# SLICE STP-S7 — UI de configuração de resumo (origem: internações)

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/services-portal-navigation/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/admission-progressive-summary/spec.md`
8. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
9. este arquivo `SLICE-STP-S7.md`

## Objetivo

Adicionar tela de configuração antes de enfileirar resumo, com seleção de LLM
fase 2 e prompt padrão/custom/salvo.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/views.py`
- `apps/summaries/urls.py`
- `apps/summaries/templates/summaries/*` (somente template(s) do fluxo)
- `apps/patients/templates/*` (ajuste mínimo do CTA)
- `tests/integration/test_summary_config_http.py`

## Escopo proibido

- mudanças em modelos/migrations;
- mudanças em command de worker;
- páginas de logs.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes HTTP do fluxo GET/POST.
2. **GREEN:** implementar view/template/URL e validações.
3. **REFACTOR:** simplificar validações e reduzir ramificações.

## Critérios de sucesso

- tela mostra opções LLM fase 2 habilitadas;
- seletor mostra prompt padrão + customizados disponíveis;
- POST com prompt padrão enfileira run;
- POST com prompt custom enfileira run;
- `salvar_prompt=true` exige título e persiste template.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S7-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S7-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S8`.
