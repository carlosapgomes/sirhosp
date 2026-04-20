# Prompt Slice S4 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/proposal.md`
4. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
5. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/**/*.md`
6. `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/tasks.md`
7. `/tmp/sirhosp-slice-S3-report.md` (se não existir, reportar bloqueio)
8. Este arquivo (`slice-prompts/SLICE-S4.md`)

## Objetivo do slice

Entregar navegação inicial por internações do paciente e timeline da internação
selecionada, com filtro por tipo profissional e layout em cards.

## Escopo permitido

- View de lista de internações por paciente.
- View da timeline por internação.
- Filtro por tipo profissional na timeline.
- Template inicial mobile friendly com cards.
- Testes de integração da navegação.

## Limites rígidos

- Máximo de **10 arquivos alterados**.
- Não redesenhar frontend global.
- Não mexer na lógica de ingestão além do necessário para exibição.

## TDD obrigatório (red -> green -> refactor)

1. Criar teste(s) falhando para navegação e filtro da timeline.
2. Implementar mínimo necessário para passar.
3. Refatorar sem expansão de escopo.

## Critérios de aceite

- Lista de internações acessível por paciente.
- Timeline da internação com filtro por tipo profissional.
- UI em cards funcional e legível em mobile.
- Testes de integração passando.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S4-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código **antes/depois** por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos, pendências e recomendação para S5.

Também atualizar `tasks.md` marcando apenas itens do S4 concluídos.
