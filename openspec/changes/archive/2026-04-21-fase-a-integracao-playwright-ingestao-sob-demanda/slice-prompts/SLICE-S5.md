<!-- markdownlint-disable MD013 -->
# Prompt Slice S5 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. Relatórios anteriores em `/tmp/sirhosp-slice-S*.md` (S1, S1.5, S1.6, S2, S2.1, S3, S4, S4.1 quando existirem)
8. Este arquivo (`slice-prompts/SLICE-S5.md`)

## Objetivo do slice

Consolidar hardening e documentação final da fase A, registrando explicitamente o backlog da fase B sem ampliar escopo de implementação.

## Escopo permitido

- Teste de regressão para falha operacional relevante do conector.
- Ajustes finais de docs/specs/tasks para consistência com o implementado.
- Atualização do documento de roadmap da fase B.
- Ajustes mínimos de robustez (sem adicionar features novas).

## Limites rígidos

- Máximo de **6 arquivos alterados**.
- Não iniciar implementação de sincronização periódica de internados.
- Não alterar arquitetura aprovada sem ADR nova.

## Protocolo obrigatório de execução (sem pular etapas)

1. **Red obrigatório**
   - Criar teste de regressão falhando para falha operacional realista (timeout/JSON inválido).
2. **Green obrigatório**
   - Implementar correção mínima para passar.
3. **Consistency pass**
   - Revisar coerência entre `proposal.md`, `design.md`, `tasks.md`, specs e código real.
4. **Quality gate completo**
   - Rodar todos os comandos definidos neste prompt.

## Critérios de aceite (gate de saída)

Só considere o slice concluído se **todos** os itens abaixo forem verdadeiros:

- Regressão de falha operacional coberta por teste.
- Artefatos OpenSpec consistentes com implementação atual.
- `uv run python manage.py makemigrations --check --dry-run` passa.
- `uv run python manage.py check` sem erro.
- `uv run pytest -q` sem falhas.
- `uv run ruff check config apps tests manage.py` sem erro.
- `uv run mypy config apps tests manage.py` sem erro relevante.
- `./scripts/markdown-lint.sh` sem erro.
- `tasks.md` atualizado apenas no bloco do S5 (itens 9.x).

## Comandos mínimos de validação

```bash
uv run python manage.py makemigrations --check --dry-run
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
2. Evidência TDD da regressão (red -> green).
3. Lista de arquivos alterados.
4. Antes/depois dos trechos críticos alterados.
5. Quadro de consistência OpenSpec vs código (item a item).
6. Comandos executados com resultado (exit code + resumo).
7. Riscos remanescentes, pendências e recomendação final.
8. Auto-auditoria final (confirmação de escopo e limites).
