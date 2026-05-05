# SLICE STP-S2 — Prompts padrão em arquivo (fase 1 e fase 2)

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
9. este arquivo `SLICE-STP-S2.md`

## Objetivo

Externalizar os prompts padrão (fase 1 e fase 2) para arquivos versionados e
criar loader tipado com erro explícito para arquivo ausente.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/prompt_loader.py`
- `apps/summaries/llm_gateway.py`
- `apps/summaries/prompts/phase1_canonical_v1.md`
- `apps/summaries/prompts/phase2_default_v1.md`
- `tests/unit/test_summary_prompt_loader.py`

## Escopo proibido

- alteração de env/config de modelos;
- orquestrador/services;
- migrations/modelos de banco;
- views/templates.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes de loader (sucesso + arquivo ausente).
2. **GREEN:** implementar loader e integrar no gateway.
3. **REFACTOR:** manter API simples e legível.

## Critérios de sucesso

- prompts padrão existem em arquivos versionados dedicados;
- loader retorna conteúdo correto para fase 1 e fase 2;
- erro é explícito quando arquivo obrigatório faltar;
- gateway deixa de depender de prompt hardcoded.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S2-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S2-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S3`.
