# SLICE STP-S3 — Config LLM por env (fase 1 fixa + fase 2 opções)

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/admission-progressive-summary/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-STP-S3.md`

## Objetivo

Implementar carregamento centralizado de config LLM por env para fase 1 e
opções da fase 2, atualizando env examples.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/llm_config.py`
- `apps/summaries/llm_gateway.py`
- `.env.example`
- `.env.docker.example`
- `tests/unit/test_summary_llm_env_config.py`

## Escopo proibido

- modelos/migrations;
- command de câmbio;
- views/templates;
- orquestração completa do pipeline.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes para parsing/validação de env.
2. **GREEN:** implementar config e adaptar consumo no gateway.
3. **REFACTOR:** remover duplicações e consolidar tipos.

## Critérios de sucesso

- fase 1 obrigatória carregada por env;
- até 4 opções de fase 2 lidas por env;
- somente opções habilitadas retornadas para UI;
- env examples atualizados com variáveis esperadas.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S3-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S3-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S4`.
