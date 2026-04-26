
# Prompt Slice S2.1 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/slice-prompts/SLICE-S2.md`
5. `/tmp/sirhosp-slice-S2-report.md`
6. Este arquivo (`slice-prompts/SLICE-S2-1.md`)

## Objetivo do slice

Resolver pendência de migração introduzida no S2 para manter consistência entre modelo Django e schema do banco.

## Escopo permitido

- Gerar migração para alteração de `IngestionRun.status`.
- Aplicar migração localmente.
- Confirmar ausência de drift com `makemigrations --check --dry-run`.
- Atualizar `tasks.md` marcando somente itens do S2.1.

## Limites rígidos

- Máximo de **4 arquivos alterados**.
- Não alterar regras de negócio, worker ou extractor.
- Não iniciar itens do S3.
- Não alterar outros arquivos OpenSpec fora de `tasks.md`.

## Protocolo obrigatório de execução (sem pular etapas)

1. **Red obrigatório**
   - Executar `uv run python manage.py makemigrations --check --dry-run`.
   - Confirmar falha atual e registrar saída no relatório.
2. **Green obrigatório**
   - Gerar a migração necessária (`makemigrations ingestion` ou equivalente).
   - Aplicar (`uv run python manage.py migrate`).
3. **Confirmação de fechamento**
   - Reexecutar `uv run python manage.py makemigrations --check --dry-run` e comprovar que passa.
4. **Validação final do slice**
   - `check`, `pytest` focado no S2 e `ruff`.

## Critérios de aceite (gate de saída)

Só considere o slice concluído se **todos** os itens abaixo forem verdadeiros:

- Migração de `IngestionRun.status` criada e versionada.
- `uv run python manage.py makemigrations --check --dry-run` passa após migração.
- `uv run python manage.py check` sem erro.
- Testes relevantes do slice passam (`tests/integration/test_worker_lifecycle.py` e `tests/unit/test_ingestion_service.py`).
- `uv run ruff check config apps tests manage.py` sem erro.
- `tasks.md` atualizado apenas no bloco do S2.1.

## Comandos mínimos de validação

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest -q tests/integration/test_worker_lifecycle.py tests/unit/test_ingestion_service.py
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S2-1-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Evidência Red -> Green da pendência de migração (incluindo saída dos comandos).
3. Arquivos alterados.
4. Fragmento da migração criada.
5. Comandos executados com resultado (exit code + resumo).
6. Auto-auditoria final (confirmar que não alterou escopo indevido).
7. Confirmação de prontidão para S3.
