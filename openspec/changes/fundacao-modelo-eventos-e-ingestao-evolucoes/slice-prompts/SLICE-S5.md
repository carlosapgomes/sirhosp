# Prompt Slice S5 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/proposal.md`
4. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
5. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/**/*.md`
6. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
7. `/tmp/sirhosp-slice-S4-report.md` (se não existir, reportar bloqueio)
8. Este arquivo (`slice-prompts/SLICE-S5.md`)

## Objetivo do slice

Consolidar hardening final, cobertura de regressão, atualização de artefatos
OpenSpec/ADR e evidências para arquivamento do change.

## Escopo permitido

- Testes de regressão focados em riscos já observados.
- Ajustes pontuais para estabilização.
- Atualização de `proposal.md`, `design.md`, specs e `tasks.md` para refletir o
  implementado.
- Registro/atualização de ADR relacionada à modelagem canônica.

## Limites rígidos

- Máximo de **6 arquivos alterados**.
- Não adicionar novas funcionalidades de produto.
- Foco em consistência, evidência e encerramento do change.

## TDD obrigatório (red -> green -> refactor)

1. Criar teste(s) de regressão falhando para casos críticos remanescentes.
2. Corrigir o mínimo necessário para passar.
3. Refatorar sem criar novo escopo.

## Critérios de aceite

- Qualidade final validada (check, testes, lint, mypy, markdown lint).
- Artefatos OpenSpec sincronizados com a implementação real.
- Evidências completas para decisão de `/opsx:archive`.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q
uv run ruff check config apps tests manage.py
uv run mypy config apps tests manage.py
./scripts/markdown-lint.sh
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S5-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código **antes/depois** por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos residuais e recomendação objetiva sobre arquivamento do change.

Também atualizar `tasks.md` marcando apenas itens do S5 concluídos.
