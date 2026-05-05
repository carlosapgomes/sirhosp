# SLICE STP-S5 — Biblioteca de prompts (modelo + CRUD + permissões)

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
9. este arquivo `SLICE-STP-S5.md`

## Objetivo

Criar biblioteca de prompts customizados com título obrigatório, visibilidade
público/privado e regras de ownership no CRUD.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/models.py`
- `apps/summaries/migrations/*` (somente nova migração)
- `apps/summaries/views.py`
- `apps/summaries/urls.py`
- `tests/integration/test_user_prompt_templates_http.py`

## Escopo proibido

- tela de configuração de resumo (fica no próximo slice);
- orquestração de fase 1/2;
- logs de execução.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes HTTP de CRUD/permissões.
2. **GREEN:** implementar modelo e endpoints mínimos.
3. **REFACTOR:** extrair validações e reduzir duplicações.

## Critérios de sucesso

- `UserPromptTemplate` com `title`, `content`, `is_public`, `owner`;
- título obrigatório em create/update;
- usuário só edita/apaga prompts próprios;
- prompts públicos aparecem em listagem para usuários autenticados.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S5-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S5-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S6`.
