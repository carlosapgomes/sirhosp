# Prompt Slice S2 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/proposal.md`
4. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
5. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/**/*.md`
6. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
7. `/tmp/sirhosp-slice-S1-report.md` (se não existir, reportar bloqueio)
8. Este arquivo (`slice-prompts/SLICE-S2.md`)

## Objetivo do slice

Entregar ingestão on-demand em memória para evoluções, com idempotência por
`event_identity_key + content_hash` e rastreamento em `IngestionRun`.

## Escopo permitido

- Serviço de ingestão em memória.
- Upsert de paciente e internação.
- Persistência idempotente de evento.
- Registro de execução em `IngestionRun`.
- Comando mínimo para disparo on-demand.
- Testes do fluxo.

## Limites rígidos

- Máximo de **10 arquivos alterados**.
- Não introduzir busca FTS neste slice.
- Não criar UI neste slice.
- Não depender de `source_file`.

## TDD obrigatório (red -> green -> refactor)

1. Criar testes falhando para identity key, hash e timezone.
2. Implementar mínimo necessário para passar.
3. Refatorar sem expandir escopo.

## Critérios de aceite

- Fluxo de ingestão em memória funcionando.
- Dedupe por identidade/hash validado por teste.
- `IngestionRun` com status e métricas básicas.
- Escopo e limite de arquivos respeitados.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S2-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código **antes/depois** por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos, pendências e recomendação para S3.

Também atualizar `tasks.md` marcando apenas itens do S2 concluídos.
