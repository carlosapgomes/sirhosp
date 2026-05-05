# SLICE STP-S6 — Orquestração duas fases + persistência de trilha

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/admission-progressive-summary/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/summary-llm-traceability/spec.md`
8. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
9. este arquivo `SLICE-STP-S6.md`

## Objetivo

Implementar orquestração em duas fases com reuso da fase 1, update
incremental e persistência de `SummaryPipelineStepRun` com custos em USD.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/services.py`
- `apps/summaries/management/commands/process_summary_runs.py`
- `apps/summaries/llm_gateway.py`
- `apps/summaries/models.py` (somente ajustes mínimos necessários)
- `tests/integration/test_summary_two_phase_orchestration.py`

## Escopo proibido

- UI de configuração/logs/status;
- CRUD de prompts;
- command de câmbio.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes de integração para run completo e reuso fase 1.
2. **GREEN:** implementar fluxo mínimo no serviço/worker.
3. **REFACTOR:** separar responsabilidades por função/fase.

## Critérios de sucesso

- execução chama fase 1 e fase 2 na ordem correta;
- reuso fase 1 gera step `skipped` com custo zero;
- update incremental em admissão aberta com novos eventos;
- cada fase persiste `prompt_text_snapshot`, payload e resposta;
- custos por fase e total persistidos em USD.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S6-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S6-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S7`.
