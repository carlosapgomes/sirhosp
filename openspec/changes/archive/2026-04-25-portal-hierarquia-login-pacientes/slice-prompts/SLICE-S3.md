# SLICE-S3 — Hierarquia operacional + ações contextuais (extração e busca JSON)

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp` e deve executar **apenas este slice**.

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/portal-hierarquia-login-pacientes/proposal.md`
4. `openspec/changes/portal-hierarquia-login-pacientes/design.md`
5. `openspec/changes/portal-hierarquia-login-pacientes/tasks.md`
6. `openspec/changes/portal-hierarquia-login-pacientes/specs/services-portal-navigation/spec.md`
7. `slice-prompts/SLICE-S3.md`

## Objetivo do slice

Conectar páginas já existentes à jornada operacional:

- de admissões/timeline, disponibilizar CTA para nova extração;
- manter busca em JSON, mas com link contextual para endpoint existente;
- permitir pré-preenchimento de `patient_record` em `/ingestao/criar/`;
- corrigir pendência herdada do S1/S2: asserts de redirect de anônimo em `tests/integration/test_ingestion_http.py` não podem mais esperar `/admin/login/`.

## Escopo permitido (somente)

- `apps/ingestion/views.py`
- `apps/ingestion/templates/ingestion/create_run.html`
- `apps/patients/templates/patients/admission_list.html`
- `apps/patients/templates/patients/timeline.html`
- `tests/integration/test_ingestion_http.py`
- `tests/unit/test_navigation_views.py`

## Escopo proibido

- criar tela HTML de busca
- alterar parser/ingestão/worker
- alterar modelos e migrações

## Limite de alteração

Máximo: **6 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: criar/ajustar testes para:
   - prefill de `patient_record` em `GET /ingestao/criar/?patient_record=...`;
   - presença de CTA "Nova extração" em admissões/timeline;
   - presença de link "Busca JSON" contextual;
   - redirects de anônimo no módulo de ingestão alinhados com `LOGIN_URL` atual (`/login/`), preferindo assert desacoplado de path hardcoded quando possível.
2. **GREEN**: implementar mínimo necessário.
3. **REFACTOR**: manter templates simples sem criar componentes complexos.

## Critérios de aceite

- prefill funcional no formulário de extração;
- admissões e timeline exibem ação de nova extração;
- admissões e timeline exibem link para busca JSON;
- pendência de redirects de anônimo em `tests/integration/test_ingestion_http.py` corrigida (sem assert legado de `/admin/login/`);
- sem criação de nova página de busca.

## Gates obrigatórios S3

Executar e registrar saída/exit code:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/integration/test_ingestion_http.py tests/unit/test_navigation_views.py`
3. `uv run ruff check config apps tests manage.py`

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-PHLP-S3-report.md`** contendo:

1. resumo do slice;
2. checklist de aceite;
3. arquivos alterados;
4. snippets `ANTES`/`DEPOIS` por arquivo alterado;
5. comandos executados + resultados;
6. riscos/pendências;
7. próximo passo sugerido (S4).

Pare ao concluir o slice.
