<!-- markdownlint-disable MD013 -->
# Prompt Slice S1 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. Este arquivo (`slice-prompts/SLICE-S1.md`)

## Objetivo do slice

Definir contrato do conector de extração e implementar adapter inicial Playwright por transição controlada (subprocesso + parse JSON).

## Escopo permitido

- Interface `EvolutionExtractorPort`.
- Implementação `PlaywrightEvolutionExtractor` com adaptação do JSON.
- Tratamento de erros do conector.
- Testes unitários do adapter.
- Preparação do conector externo via clone em `/tmp`:
  - `git clone https://github.com/carlosapgomes/resumo-evolucoes-clinicas /tmp/resumo-evolucoes-clinicas`
  - usar `/tmp/resumo-evolucoes-clinicas/path2.py` como entrada inicial da integração transitória.

## Limites rígidos

- Máximo de **8 arquivos alterados**.
- Não alterar UI neste slice.
- Não implementar fila completa neste slice.
- Não introduzir Celery/Redis.
- Não usar dados reais.

## TDD obrigatório (red -> green -> refactor)

1. Criar testes falhando para parse e validação do contrato.
2. Implementar mínimo necessário para passar.
3. Refatorar sem ampliar escopo.

## Critérios de aceite

- Porta e adapter implementados com testes passando.
- Falhas de execução/JSON inválido mapeadas para erro de domínio.
- `uv run python manage.py check` sem erro.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S1-report.md`

Também atualizar `tasks.md` marcando apenas itens do S1 concluídos.
