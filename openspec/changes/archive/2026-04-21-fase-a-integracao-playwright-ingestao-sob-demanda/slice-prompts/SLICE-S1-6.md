<!-- markdownlint-disable MD013 -->

# Prompt Slice S1.6 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/slice-prompts/SLICE-S1-5.md`
5. `/tmp/sirhosp-slice-S1-5-report.md`
6. Este arquivo (`slice-prompts/SLICE-S1-6.md`)

## Objetivo do slice

Completar a validação obrigatória do extractor, incluindo os campos que faltaram no S1.5: `createdBy` e `signatureLine`.

## Escopo permitido

- Ajustar `_validate_item` em `apps/ingestion/extractors/playwright_extractor.py` para exigir:
  - `createdAt`
  - `content`
  - `createdBy`
  - `type`
  - `signatureLine`
  - `admissionKey`
- Criar/ajustar testes unitários para ausência e vazio de `createdBy` e `signatureLine`.
- Garantir mensagens de erro com nomes claros dos campos faltantes.

## Limites rígidos

- Máximo de **4 arquivos alterados**.
- Não alterar semântica de conversão de datas.
- Não alterar fluxo de subprocesso.
- Não iniciar itens do S2.

## TDD obrigatório (red -> green -> refactor)

1. Criar testes falhando para ausência/vazio de `createdBy` e `signatureLine`.
2. Implementar mínimo necessário para passar.
3. Refatorar sem ampliar escopo.

## Critérios de aceite

- `_validate_item` exige todos os campos obrigatórios definidos no S1.5.
- Testes cobrem ausência e vazio de `createdBy` e `signatureLine`.
- `uv run pytest -q tests/unit/test_evolution_extractor.py` passando.
- `uv run python manage.py check` sem erro.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit/test_evolution_extractor.py
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S1-6-report.md`

Também atualizar `tasks.md` marcando apenas itens do S1.6 concluídos.
