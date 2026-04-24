<!-- markdownlint-disable MD013 -->

# SLICE-S2 — Run admissions-only para sincronização de internações

## Handoff de entrada (contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-first-missing-patient-flow/proposal.md`
4. `openspec/changes/admission-first-missing-patient-flow/design.md`
5. `openspec/changes/admission-first-missing-patient-flow/tasks.md`
6. specs da change:
   - `openspec/changes/admission-first-missing-patient-flow/specs/evolution-ingestion-on-demand/spec.md`
   - `openspec/changes/admission-first-missing-patient-flow/specs/patient-admission-mirror/spec.md`
   - `openspec/changes/admission-first-missing-patient-flow/specs/ingestion-run-observability/spec.md`
7. este arquivo `slice-prompts/SLICE-S2.md`

## Pré-condição de branch

Executar e registrar no relatório:

```bash
git checkout feature/admission-first-missing-patient-flow
git fetch origin
git status --short --branch
```

## Objetivo do slice

Implementar sincronização de internações (admissions-only) como operação explícita, sem extração de evoluções.

## Escopo permitido (somente)

- `apps/ingestion/views.py`
- `apps/ingestion/services.py`
- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `apps/ingestion/templates/ingestion/run_status.html`
- `apps/ingestion/urls.py` (se necessário)
- `tests/integration/test_ingestion_http.py`
- `tests/integration/test_worker_lifecycle.py`

## Escopo proibido

- mudança estrutural de arquitetura assíncrona
- refactors amplos em módulos não relacionados
- implementação de seleção de internação (S3)

## Limite de alteração

Máximo: **8 arquivos**.
Se precisar exceder, **parar** e reportar bloqueio.

## Protocolo anti-drift (obrigatório)

1. Implementar **somente este slice**.
2. Não antecipar S3/S4/S5.
3. Preservar semântica atual de worker fora do que for necessário para admissions-only.

## TDD obrigatório

1. **RED**: testes de run admissions-only (sucesso/falha/snapshot vazio) falhando.
2. **GREEN**: worker processa admissions-only e expõe resultado no status.
3. **REFACTOR**: simplificar condicionais e mensagens sem alterar comportamento.

## Gates obrigatórios S2

Executar e registrar **todos** os comandos com exit code:

1. `./scripts/test-in-container.sh check`
2. `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/integration/test_ingestion_http.py tests/integration/test_worker_lifecycle.py"`
3. `./scripts/test-in-container.sh lint`
4. `./scripts/test-in-container.sh typecheck`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-AFMF-S2-report.md` contendo obrigatoriamente:

1. Resumo do slice.
2. Checklist de aceite.
3. Lista de arquivos alterados.
4. **Snippet before/after para cada arquivo alterado**.
5. Tabela de **todos os comandos executados** (incluindo RED) com comando, objetivo, exit code e status.
6. Seção explícita "Testes executados no slice" com lista completa dos testes rodados e resultado.
7. Riscos, pendências e próximo passo sugerido (S3).

Não incluir dados sensíveis. Parar ao concluir.
