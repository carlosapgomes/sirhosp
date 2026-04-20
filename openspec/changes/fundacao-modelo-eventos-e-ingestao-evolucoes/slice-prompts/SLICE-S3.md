# Prompt Slice S3 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/proposal.md`
4. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
5. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/**/*.md`
6. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
7. `/tmp/sirhosp-slice-S2-report.md` (se não existir, reportar bloqueio)
8. Este arquivo (`slice-prompts/SLICE-S3.md`)

## Objetivo do slice

Entregar busca global FTS (MVP) em `content_text` com filtros por paciente,
internação, período e tipo profissional.

## Escopo permitido

- Query/service de busca FTS.
- Filtros combinados.
- Endpoint/view inicial para busca global.
- Payload de rastreabilidade (`event_id`, `patient_id`, `admission_id`,
  `happened_at`).
- Testes da busca.

## Limites rígidos

- Máximo de **8 arquivos alterados**.
- Não construir timeline completa neste slice.
- Não refatorar ingestão fora do necessário para busca.

## TDD obrigatório (red -> green -> refactor)

1. Criar teste falhando para busca por relevância e filtros.
2. Implementar mínimo necessário para passar.
3. Refatorar sem ampliar escopo.

## Critérios de aceite

- Busca FTS global funcionando com filtros combinados.
- Resultado com campos de rastreabilidade.
- Testes cobrindo happy path e pelo menos um caso de filtro combinado.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit
uv run mypy config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S3-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código **antes/depois** por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos, pendências e recomendação para S4.

Também atualizar `tasks.md` marcando apenas itens do S3 concluídos.
