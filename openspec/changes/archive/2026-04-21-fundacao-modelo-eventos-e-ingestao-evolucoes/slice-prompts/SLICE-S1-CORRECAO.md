# Prompt de correção — fechamento do Slice S1

Você vai executar uma correção pontual de fechamento do Slice S1 (sem iniciar S2).

## Contexto

- Projeto: `/home/carlos/projects/sirhosp`
- Change: `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes`
- Relatório atual: `/tmp/sirhosp-slice-S1-report.md`
- Objetivo: corrigir inconsistências de escopo/evidência do S1.

## Leia antes

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
4. `/tmp/sirhosp-slice-S1-report.md`

## Tarefa

1. Verifique se houve alteração em `pyproject.toml` durante o S1.
2. Se houve, decida e execute UMA das opções abaixo (preferir Opção A):
   - **Opção A (preferida):** reverter mudança de `pyproject.toml` para manter escopo estrito do S1.
   - **Opção B:** manter mudança e corrigir o relatório para refletir arquivo extra e before/after.
3. Atualize o relatório S1 em `/tmp/sirhosp-slice-S1-report.md` para ficar 100% consistente com o git diff final do S1:
   - contagem correta de arquivos alterados;
   - tabela de arquivos alterados correta;
   - trechos before/after para TODO arquivo alterado;
   - comandos executados e status.
4. Não altere código funcional de domínio do S1 (modelos/migrações/testes), exceto o mínimo para cumprir a opção escolhida.
5. Não iniciar S2.

## Restrições

- Escopo mínimo (drift zero).
- No máximo 3 arquivos alterados nesta correção.
- Sem refactor.
- Sem nova funcionalidade.
- Sem dados reais.

## Validação obrigatória

Rode e registre resultado no relatório:

- `uv run python manage.py check`
- `uv run pytest -q tests/unit`
- `uv run ruff check config apps tests manage.py`

## Saída obrigatória

1. Arquivos alterados (lista objetiva).
2. Relatório corrigido em `/tmp/sirhosp-slice-S1-report.md`.
3. Resumo final curto:
   - qual opção foi usada (A ou B),
   - contagem final de arquivos do S1,
   - validações (pass/fail).
