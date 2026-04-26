# SLICE-S4 — `/ingestao/criar/` como rota secundária contextual

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
7. este arquivo `slice-prompts/SLICE-S4.md`

## Pré-condição de branch

Executar e registrar no relatório:

```bash
git checkout feature/admission-first-missing-patient-flow
git fetch origin
git status --short --branch
```

## Objetivo do slice

Manter `/ingestao/criar/` para extração por período apenas no fluxo contextual de admissão; acesso solto deve redirecionar para `/patients/`.

## Escopo permitido (somente)

- `apps/ingestion/views.py`
- `apps/ingestion/templates/ingestion/create_run.html`
- `apps/ingestion/urls.py` (se necessário)
- `tests/integration/test_ingestion_http.py`
- `tests/unit/test_navigation_views.py`

## Escopo proibido

- alterar semântica de admissions-only (S2)
- alterar sincronização completa por admissão (S3)
- mexer em chunking do conector (S5)

## Limite de alteração

Máximo: **8 arquivos**.
Se precisar exceder, **parar** e reportar bloqueio.

## Protocolo anti-drift (obrigatório)

1. Implementar **somente este slice**.
2. Mudanças estritamente no comportamento contextual de `/ingestao/criar/`.
3. Não antecipar S5.

## TDD obrigatório

1. **RED**: testes para redirect sem contexto e prefill contextual.
2. **GREEN**: validações e prefill respeitando limites da internação.
3. **REFACTOR**: simplificação de validações sem ampliar escopo.

## Gates obrigatórios S4

Executar e registrar **todos** os comandos com exit code:

1. `./scripts/test-in-container.sh check`
2. `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/integration/test_ingestion_http.py tests/unit/test_navigation_views.py"`
3. `./scripts/test-in-container.sh lint`
4. `./scripts/test-in-container.sh typecheck`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-AFMF-S4-report.md` contendo obrigatoriamente:

1. Resumo do slice.
2. Checklist de aceite.
3. Lista de arquivos alterados.
4. **Snippet before/after para cada arquivo alterado**.
5. Tabela de **todos os comandos executados** (incluindo RED) com comando, objetivo, exit code e status.
6. Seção explícita "Testes executados no slice" com lista completa dos testes rodados e resultado.
7. Riscos, pendências e próximo passo sugerido (S5).

Não incluir dados sensíveis. Parar ao concluir.
