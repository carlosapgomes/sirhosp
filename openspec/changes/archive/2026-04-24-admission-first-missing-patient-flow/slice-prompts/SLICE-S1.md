<!-- markdownlint-disable MD013 -->

# SLICE-S1 — Estado "não encontrado" com CTA admission-first

## Handoff de entrada (contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-first-missing-patient-flow/proposal.md`
4. `openspec/changes/admission-first-missing-patient-flow/design.md`
5. `openspec/changes/admission-first-missing-patient-flow/tasks.md`
6. `openspec/changes/admission-first-missing-patient-flow/specs/services-portal-navigation/spec.md`
7. este arquivo `slice-prompts/SLICE-S1.md`

## Pré-condição de branch

Executar e registrar no relatório:

```bash
git checkout feature/admission-first-missing-patient-flow || git checkout -b feature/admission-first-missing-patient-flow
git fetch origin
git status --short --branch
```

Se houver working tree suja ou branch divergente sem contexto claro, **parar** e reportar bloqueio.

## Objetivo do slice

Quando a busca em `/patients/` não encontrar paciente local, exibir CTA primária para sincronizar internações do registro pesquisado.

## Escopo permitido (somente)

- `apps/patients/templates/patients/patient_list.html`
- `apps/patients/views.py` (apenas se necessário para contexto da busca)
- `tests/unit/test_patient_list_view.py`

## Escopo proibido

- Worker/ingestion pipeline
- migrations
- automação Playwright
- qualquer refactor fora do fluxo de estado vazio/CTA da lista de pacientes

## Limite de alteração

Máximo: **6 arquivos**.
Se precisar exceder, **parar** e reportar bloqueio.

## Protocolo anti-drift (obrigatório)

1. Implementar **somente este slice**.
2. Mudanças mínimas e verticais (teste + implementação + template necessário).
3. Não antecipar itens de S2+.
4. TDD obrigatório com evidência RED -> GREEN -> REFACTOR.

## TDD obrigatório

1. **RED**: criar teste falhando para estado vazio com query + CTA primária.
2. **GREEN**: template exibe CTA com registro buscado.
3. **REFACTOR**: limpeza mínima sem ampliar escopo.

## Gates obrigatórios S1

Executar e registrar **todos** os comandos com exit code:

1. `./scripts/test-in-container.sh check`
2. `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit/test_patient_list_view.py"`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-AFMF-S1-report.md` contendo obrigatoriamente:

1. Resumo do slice.
2. Checklist de aceite.
3. Lista de arquivos alterados.
4. **Snippet before/after para cada arquivo alterado** (sem exceção).
5. Tabela de **todos os comandos executados** no slice (inclusive tentativas RED):
   - ordem,
   - comando exato,
   - objetivo,
   - exit code,
   - status (PASS/FAIL).
6. Seção explícita "Testes executados no slice" listando arquivos/casos de teste rodados e resultado.
7. Riscos, pendências e próximo passo sugerido (S2).

Não incluir dados sensíveis. Parar ao concluir.
