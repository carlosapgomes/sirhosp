# Tasks: portal-hierarquia-login-pacientes

## 1. Slice S1 - Entrada autenticada e redirecionamento padrão

Escopo: landing com CTA de login, rota de login/logout, redirect pós-login para `/patients/`.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED) Criar testes de comportamento para landing/login/redirect pós-login.
- [x] 1.2 Implementar rota `/login/` e `/logout/` com template simples.
- [x] 1.3 Ajustar `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL` para o fluxo desejado.
- [x] 1.4 Atualizar landing (`/`) com botão de login visível.
- [x] 1.5 **Gate obrigatório S1**: testes do slice passando + `manage.py check`.
- [x] 1.6 Gerar `/tmp/sirhosp-slice-PHLP-S1-report.md` com snippets before/after por arquivo alterado.

## 2. Slice S2 - Lista de pacientes como hub principal

Escopo: nova página `/patients/` autenticada com filtro por nome/registro e paginação simples.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (RED) Criar testes para listagem, filtro por nome, filtro por registro, estado vazio e acesso anônimo.
- [x] 2.2 Implementar service/query para busca por `name` e `patient_source_key`.
- [x] 2.3 Implementar view + rota `/patients/`.
- [x] 2.4 Implementar template da lista com navegação para admissões.
- [x] 2.5 **Gate obrigatório S2**: testes do slice passando + `ruff` no escopo alterado + `manage.py check`.
- [x] 2.6 Gerar `/tmp/sirhosp-slice-PHLP-S2-report.md` com snippets before/after por arquivo alterado.

## 3. Slice S3 - Navegação hierárquica e ações contextuais

Escopo: nas telas de admissões/timeline, expor ação de nova extração e link para busca JSON; pré-preencher registro em `/ingestao/criar/` quando fornecido por querystring; corrigir pendência de testes de redirect legado (`/admin/login/`) no módulo de ingestão.

Limite: até **7 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (RED) Criar/ajustar testes para pré-preenchimento de registro em extração, presença de ações contextuais nas páginas hierárquicas e redirects de anônimo alinhados ao `LOGIN_URL` atual (`/login/`).
- [x] 3.2 Ajustar `create_run` para aceitar prefill de `patient_record` via querystring (GET).
- [x] 3.3 Atualizar templates de admissões/timeline com CTA "Nova extração" e link "Busca JSON".
- [x] 3.4 Garantir breadcrumb/links mínimos de retorno na hierarquia.
- [x] 3.5 **Gate obrigatório S3**: `uv run python manage.py check` + `uv run pytest -q tests/integration/test_ingestion_http.py tests/unit/test_navigation_views.py` + `uv run ruff check config apps tests manage.py`.
- [x] 3.6 Gerar `/tmp/sirhosp-slice-PHLP-S3-report.md` com snippets before/after por arquivo alterado.

## 4. Slice S4 - Hardening de autenticação + regressão final

Escopo: garantir que páginas de portal operacional estejam protegidas por autenticação (exceto `/` e `/health/`), ajustar regressões de testes e validar suite final.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 (RED) Criar/ajustar testes para redirecionamento de anônimos em páginas operacionais (`/patients/`, admissões, timeline, busca JSON).
- [x] 4.2 Implementar proteção com `login_required` nas views de portal operacional do escopo.
- [x] 4.3 Ajustar testes existentes afetados para o novo contrato de autenticação.
- [x] 4.4 **Gate obrigatório S4**:
  - `uv run python manage.py check`
  - `uv run pytest -q`
  - `uv run ruff check config apps tests manage.py`
  - `uv run mypy config apps tests manage.py`
- [x] 4.5 Gerar `/tmp/sirhosp-slice-PHLP-S4-report.md` com snippets before/after por arquivo alterado.

## Stop Rule

- Implementar **um slice por vez**.
- Ao concluir um slice, parar e aguardar decisão explícita para o próximo.
