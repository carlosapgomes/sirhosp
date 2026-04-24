<!-- markdownlint-disable MD013 -->
# SLICE-S3 — Seleção de internação e sincronização completa

## Handoff de entrada (contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-first-missing-patient-flow/proposal.md`
4. `openspec/changes/admission-first-missing-patient-flow/design.md`
5. `openspec/changes/admission-first-missing-patient-flow/tasks.md`
6. specs da change:
   - `openspec/changes/admission-first-missing-patient-flow/specs/services-portal-navigation/spec.md`
   - `openspec/changes/admission-first-missing-patient-flow/specs/evolution-ingestion-on-demand/spec.md`
   - `openspec/changes/admission-first-missing-patient-flow/specs/ingestion-run-observability/spec.md`
7. este arquivo `slice-prompts/SLICE-S3.md`

## Pré-condição de branch

Executar e registrar no relatório:

```bash
git checkout feature/admission-first-missing-patient-flow
git fetch origin
git status --short --branch
```

## Objetivo do slice

Após sincronização de internações, conduzir para lista de admissões e permitir sincronização completa por internação selecionada.

## Escopo permitido (somente)

- `apps/patients/views.py`
- `apps/patients/templates/patients/admission_list.html`
- `apps/ingestion/views.py`
- `apps/ingestion/services.py`
- `apps/ingestion/templates/ingestion/run_status.html`
- `tests/unit/test_navigation_views.py`
- `tests/integration/test_ingestion_http.py`

## Escopo proibido

- mudar comportamento de `/ingestao/criar/` sem contexto (isso é S4)
- mexer em chunking do conector (isso é S5)

## Limite de alteração

Máximo: **7 arquivos**.
Se precisar exceder, **parar** e reportar bloqueio.

## Protocolo anti-drift (obrigatório)

1. Implementar **somente este slice**.
2. Não antecipar S4/S5.
3. Manter mudança restrita à seleção de internação + run de sincronização completa.

## TDD obrigatório

1. **RED**: testes para CTA de sincronização completa por admissão.
2. **GREEN**: criação de run com faixa derivada da admissão (`start=admission_date`, `end=discharge_date||hoje`).
3. **REFACTOR**: limpeza de duplicações nas views/templates.

## Gates obrigatórios S3

Executar e registrar **todos** os comandos com exit code:

1. `./scripts/test-in-container.sh check`
2. `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit/test_navigation_views.py tests/integration/test_ingestion_http.py"`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-AFMF-S3-report.md` contendo obrigatoriamente:

1. Resumo do slice.
2. Checklist de aceite.
3. Lista de arquivos alterados.
4. **Snippet before/after para cada arquivo alterado**.
5. Tabela de **todos os comandos executados** (incluindo RED) com comando, objetivo, exit code e status.
6. Seção explícita "Testes executados no slice" com lista completa dos testes rodados e resultado.
7. Riscos, pendências e próximo passo sugerido (S4).

Não incluir dados sensíveis. Parar ao concluir.
