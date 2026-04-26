# SLICE-S5 — Hardening final, gates completos e fechamento da change

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-representation/proposal.md`
4. `openspec/changes/admission-period-representation/design.md`
5. `openspec/changes/admission-period-representation/tasks.md`
6. `/tmp/sirhosp-slice-APR-S4-report.md`
7. este arquivo `slice-prompts/SLICE-S5.md`

## Pré-condição de branch

Obrigatório estar em:

```bash
git checkout feature/admission-period-representation
```

## Objetivo do slice

Finalizar a change com regressão completa, limpeza residual de testes/docs e artefatos finais de aceite.

## Escopo permitido (somente)

- ajustes residuais mínimos em testes afetados
- `openspec/changes/admission-period-representation/tasks.md` (marcar concluído)
- `.md` de suporte estritamente necessário

## Escopo proibido

- novas features
- mudanças arquiteturais
- alterações de modelo/schema além do já entregue nos slices anteriores

## Limite de alteração

Máximo: **5 arquivos**.

## TDD obrigatório

Se houver ajuste funcional residual: red -> green -> refactor em teste específico.

## Gates obrigatórios S5 (DoD final)

Registrar comando + exit code + resultado (formato containerizado oficial):

1. `./scripts/test-in-container.sh check`
2. `POSTGRES_PORT=${SIRHOSP_TEST_DB_PORT:-55432} docker compose -p ${SIRHOSP_TEST_PROJECT:-sirhosp-test} -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q"`
3. `./scripts/test-in-container.sh lint`
4. `./scripts/test-in-container.sh typecheck`
5. `./scripts/markdown-lint.sh` (se houver `.md` alterado)

## Critério de encerramento

- Todos os gates verdes.
- `tasks.md` da change atualizado com checkboxes concluídos.
- relatório final consolidado gerado.

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-APR-S5-report.md` com:

- resumo final da change;
- checklist de aceite consolidado;
- arquivos alterados no slice;
- snippets before/after por arquivo;
- tabela de comandos + resultados;
- riscos residuais (se houver);
- recomendação explícita de arquivamento da change.

Pare ao concluir.
