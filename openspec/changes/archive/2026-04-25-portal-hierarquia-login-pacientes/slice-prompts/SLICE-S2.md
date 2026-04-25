<!-- markdownlint-disable MD013 -->
# SLICE-S2 — Lista de pacientes (`/patients/`) com busca por nome/registro

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp` e deve executar **apenas este slice**.

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/portal-hierarquia-login-pacientes/proposal.md`
4. `openspec/changes/portal-hierarquia-login-pacientes/design.md`
5. `openspec/changes/portal-hierarquia-login-pacientes/tasks.md`
6. `openspec/changes/portal-hierarquia-login-pacientes/specs/services-portal-navigation/spec.md`
7. `slice-prompts/SLICE-S2.md`

## Objetivo do slice

Implementar o hub de navegação autenticado em `/patients/` com:

- listagem de pacientes;
- filtro textual por `name` e `patient_source_key` (registro);
- paginação simples;
- link do paciente para admissões.

## Escopo permitido (somente)

- `apps/patients/urls.py`
- `apps/patients/views.py`
- `apps/patients/services.py`
- `apps/patients/templates/patients/patient_list.html` (novo)
- `tests/unit/test_patient_list_view.py` (novo)
- `tests/integration/test_patient_list_http.py` (novo, opcional se necessário)

## Escopo proibido

- alterar fluxo de ingestão
- alterar timeline clínica
- criar endpoint de busca HTML separado
- alterar autenticação de outras rotas fora de `/patients/`

## Limite de alteração

Máximo: **6 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: testes falhando para:
   - acesso autenticado retorna 200 em `/patients/`;
   - anônimo é redirecionado para login;
   - filtro por nome funciona;
   - filtro por registro funciona;
   - estado vazio sem resultados.
2. **GREEN**: implementar mínimo necessário.
3. **REFACTOR**: reduzir duplicação sem ampliar escopo.

## Critérios de aceite

- rota `/patients/` criada;
- busca cobre nome e registro;
- paginação simples aplicada;
- link para `/patients/<id>/admissions/` presente na lista;
- contrato de autenticação de `/patients/` coberto por teste.

## Gates obrigatórios S2

Executar e registrar saída/exit code:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/unit/test_patient_list_view.py`
3. `uv run ruff check config apps tests manage.py`

> Se criou teste de integração específico, incluir no gate também.

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-PHLP-S2-report.md`** contendo:

1. resumo do slice;
2. checklist de aceite;
3. arquivos alterados;
4. snippets `ANTES`/`DEPOIS` por arquivo alterado;
5. comandos executados + resultados;
6. riscos/pendências;
7. próximo passo sugerido (S3).

Pare ao concluir o slice.
