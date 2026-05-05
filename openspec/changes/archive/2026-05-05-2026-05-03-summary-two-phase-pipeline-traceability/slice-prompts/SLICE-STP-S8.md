# SLICE STP-S8 — Logs públicos/admin com USD + BRL

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/services-portal-navigation/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/summary-llm-traceability/spec.md`
8. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
9. este arquivo `SLICE-STP-S8.md`

## Objetivo

Implementar páginas de logs com dois níveis de permissão e custos em USD/BRL
(convertidos pela cotação mais recente disponível).

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/views.py`
- `apps/summaries/urls.py`
- `apps/summaries/templates/summaries/*` (somente templates de logs)
- `apps/summaries/exchange_rates.py` (ajuste mínimo de consulta, se necessário)
- `tests/integration/test_summary_logs_http.py`

## Escopo proibido

- alterações de modelos/migrations;
- orquestrador/worker;
- fluxo de configuração do resumo.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes HTTP para logs públicos e admin.
2. **GREEN:** implementar views/templates/ACL + conversão BRL.
3. **REFACTOR:** extrair helpers de formatação de custo.

## Critérios de sucesso

- logs públicos acessíveis a autenticados sem dados sensíveis;
- logs admin restritos a staff/superuser;
- custos exibidos em USD e BRL;
- conversão BRL usa cotação mais recente disponível;
- prompt/payload/response completos só na visão admin.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S8-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S8-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S9`.
