<!-- markdownlint-disable MD013 -->
# SLICE-S1 — Entrada autenticada (landing + login + redirect)

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp` e deve executar **apenas este slice**.

Leia obrigatoriamente antes de codar:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/portal-hierarquia-login-pacientes/proposal.md`
4. `openspec/changes/portal-hierarquia-login-pacientes/design.md`
5. `openspec/changes/portal-hierarquia-login-pacientes/tasks.md`
6. `openspec/changes/portal-hierarquia-login-pacientes/specs/services-portal-navigation/spec.md`
7. este arquivo (`slice-prompts/SLICE-S1.md`)

## Objetivo do slice

Entregar fluxo inicial de autenticação:

- landing pública com CTA "Entrar";
- rota de login/logout dedicada;
- pós-login direcionando para `/patients/`.

## Escopo permitido (somente)

- `config/urls.py`
- `config/settings.py`
- `apps/core/templates/core/home.html`
- `templates/registration/login.html` (novo)
- `tests/integration/test_portal_entry_auth.py` (novo)

## Escopo proibido

- qualquer arquivo de domínio clínico (`models`, `services` clínicos, migrações)
- criação de `/patients/` (isso é S2)
- refactors não relacionados ao login/landing

## Limite de alteração

Máximo: **5 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: criar testes falhando para:
   - landing com botão/link para login;
   - `/login/` renderiza formulário;
   - login bem-sucedido redireciona para `/patients/`.
2. **GREEN**: implementar o mínimo para passar.
3. **REFACTOR**: limpeza mínima sem ampliar escopo.

## Critérios de aceite

- Landing pública mostra CTA de login.
- `/login/` e `/logout/` funcionam.
- `LOGIN_REDIRECT_URL` direciona para `/patients/`.
- nenhum endpoint novo além do escopo.

## Gates obrigatórios S1

Executar e registrar saída/exit code:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/integration/test_portal_entry_auth.py`
3. `uv run ruff check config apps tests manage.py`

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-PHLP-S1-report.md`** contendo:

1. resumo objetivo do que foi implementado;
2. checklist de aceite (itens marcados);
3. lista de arquivos alterados;
4. para **cada arquivo alterado**, snippets `ANTES` e `DEPOIS` do trecho modificado;
5. tabela de comandos executados (comando, exit code, resultado);
6. riscos/pendências;
7. próximo passo sugerido (S2).

Pare ao concluir o slice.
