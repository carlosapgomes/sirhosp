# Prompt Slice S1 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/proposal.md`
4. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
5. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/**/*.md`
6. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
7. Este arquivo (`slice-prompts/SLICE-S1.md`)

Se houver conflito, siga a ordem acima.

## Objetivo do slice

Entregar fundação de domínio com modelos `Patient`, `Admission`,
`ClinicalEvent`, `IngestionRun` e `PatientIdentifierHistory`, incluindo
migrações e testes.

## Escopo permitido

- Modelos do domínio clínico inicial.
- Constraints de unicidade por chave externa.
- Campos canônicos para eventos clínicos.
- Migrações do banco.
- Testes unitários/integração do slice.

## Limites rígidos

- Máximo de **8 arquivos alterados**.
- Não implementar ingestão completa neste slice.
- Não criar UI neste slice.
- Não introduzir Celery/Redis.
- Não usar dados reais.

## TDD obrigatório (red -> green -> refactor)

1. Criar teste(s) falhando para modelos/constraints.
2. Implementar mínimo necessário para passar.
3. Refatorar sem ampliar escopo.

## Critérios de aceite

- Testes do slice cobrindo criação/atualização e constraints principais.
- Migrações geradas e aplicáveis.
- `uv run python manage.py check` sem erro.
- Escopo e limite de arquivos respeitados.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S1-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código **antes/depois** por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos, pendências e recomendação para S2.

Também atualizar `tasks.md` marcando apenas itens do S1 concluídos.
