# SLICE-S4 — Portal: cobertura de internações (pacientes + admissões)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-representation/proposal.md`
4. `openspec/changes/admission-period-representation/design.md`
5. `openspec/changes/admission-period-representation/tasks.md`
6. `openspec/changes/admission-period-representation/specs/services-portal-navigation/spec.md`
7. `/tmp/sirhosp-slice-APR-S3-report.md`
8. este arquivo `slice-prompts/SLICE-S4.md`

## Pré-condição de branch

Obrigatório estar em:

```bash
git checkout feature/admission-period-representation
```

## Objetivo do slice

Melhorar representação de cobertura no portal:

- lista de pacientes mostra resumo de cobertura por internações;
- lista de admissões marca explicitamente internações sem eventos extraídos.

## Escopo permitido (somente)

- `apps/patients/services.py`
- `apps/patients/views.py`
- `apps/patients/templates/patients/patient_list.html`
- `apps/patients/templates/patients/admission_list.html`
- `tests/unit/test_patient_list_view.py`
- `tests/unit/test_navigation_views.py`

## Escopo proibido

- alterações no worker e extractor
- mudanças de modelos neste slice

## Limite de alteração

Máximo: **7 arquivos**.

## Regras obrigatórias deste slice

1. Em `/patients/`, por paciente, exibir:
   - internações conhecidas;
   - internações com eventos;
   - sem eventos (diferença).
2. Em `/patients/<id>/admissions/`, quando `event_count == 0`, exibir badge textual **"Sem eventos extraídos"**.
3. Manter layout Bootstrap 5.3 e responsividade.

## TDD obrigatório

1. **RED**: testes falhando para resumo de cobertura e badge sem eventos.
2. **GREEN**: implementação mínima.
3. **REFACTOR**: manter queries enxutas e evitar N+1.

## Gates obrigatórios S4

Registrar comando + exit code + resultado (formato containerizado oficial):

1. `./scripts/test-in-container.sh check`
2. `POSTGRES_PORT=${SIRHOSP_TEST_DB_PORT:-55432} docker compose -p ${SIRHOSP_TEST_PROJECT:-sirhosp-test} -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit/test_patient_list_view.py tests/unit/test_navigation_views.py"`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-APR-S4-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S5).

Pare ao concluir.
