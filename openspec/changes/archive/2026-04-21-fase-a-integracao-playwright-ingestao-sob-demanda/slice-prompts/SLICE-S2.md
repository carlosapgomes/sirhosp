
# Prompt Slice S2 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. Este arquivo (`slice-prompts/SLICE-S2.md`)

## Objetivo do slice

Implementar orquestração assíncrona de `IngestionRun` sob demanda com worker via management command (sem Celery).

## Escopo permitido

- Transição de estados de run (`queued`, `running`, `succeeded`, `failed`).
- Worker de processamento de runs pendentes.
- Integração do worker com serviço de ingestão existente.
- Testes de integração de ciclo de vida da run.

## Limites rígidos

- Máximo de **9 arquivos alterados**.
- Não implementar cálculo de lacunas neste slice.
- Não implementar UI final neste slice.
- Não introduzir Celery/Redis.

## TDD obrigatório (red -> green -> refactor)

1. Criar teste falhando para transição de estados da run.
2. Implementar worker mínimo para passar.
3. Refatorar mantendo escopo.

## Critérios de aceite

- Worker processa runs queued e persiste estado final.
- Erros de execução levam a `failed` com mensagem rastreável.
- `uv run python manage.py check` sem erro.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit tests/integration
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S2-report.md`

Também atualizar `tasks.md` marcando apenas itens do S2 concluídos.
