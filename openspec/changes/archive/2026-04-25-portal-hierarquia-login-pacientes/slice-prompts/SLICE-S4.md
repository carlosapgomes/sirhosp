# SLICE-S4 — Hardening de autenticação do portal + regressão final

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp` e deve executar **apenas este slice**.

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/portal-hierarquia-login-pacientes/proposal.md`
4. `openspec/changes/portal-hierarquia-login-pacientes/design.md`
5. `openspec/changes/portal-hierarquia-login-pacientes/tasks.md`
6. `openspec/changes/portal-hierarquia-login-pacientes/specs/services-portal-navigation/spec.md`
7. `slice-prompts/SLICE-S4.md`

## Objetivo do slice

Fechar contrato de autenticação para páginas operacionais do portal e validar regressão completa do change.

Público deve permanecer:

- `/`
- `/health/`

Operacional deve exigir login:

- `/patients/`
- `/patients/<id>/admissions/`
- `/admissions/<id>/timeline/`
- `/ingestao/criar/`
- `/ingestao/status/<id>/`
- `/search/clinical-events/`

## Escopo permitido (somente)

- `apps/patients/views.py`
- `apps/search/views.py`
- `tests/integration/test_ingestion_http.py`
- `tests/unit/test_navigation_views.py`
- `tests/integration/test_search_http_auth.py` (novo)
- `README.md` (ajuste mínimo de mapa de endpoints, opcional)

## Escopo proibido

- mudanças no domínio de dados
- mudanças em scraping/worker
- criação de novos serviços fora do escopo de autenticação

## Limite de alteração

Máximo: **6 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: criar/ajustar testes para garantir redirecionamento de anônimos nas rotas operacionais.
2. **GREEN**: aplicar `login_required` e ajustar testes existentes.
3. **REFACTOR**: remover duplicação de setup de autenticação nos testes, sem ampliar escopo.

## Critérios de aceite

- rotas públicas continuam públicas (`/`, `/health/`);
- rotas operacionais exigem autenticação;
- regressão funcional do fluxo principal preservada.

## Gates obrigatórios S4 (DoD final do change)

Executar e registrar saída/exit code:

1. `uv run python manage.py check`
2. `uv run pytest -q`
3. `uv run ruff check config apps tests manage.py`
4. `uv run mypy config apps tests manage.py`
5. `./scripts/markdown-lint.sh` (se houver alteração em `.md`)

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-PHLP-S4-report.md`** contendo:

1. resumo final do slice;
2. checklist de aceite;
3. arquivos alterados;
4. snippets `ANTES`/`DEPOIS` por arquivo alterado;
5. comandos executados + resultados;
6. riscos residuais e pendências;
7. recomendação de fechamento/arquivo do change.

Pare ao concluir o slice.
