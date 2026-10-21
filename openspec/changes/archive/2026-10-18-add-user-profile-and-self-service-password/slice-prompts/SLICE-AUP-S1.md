# SLICE-AUP-S1 — Página de perfil e troca de senha própria

## Objetivo

Usuário autenticado do portal abre `/perfil/`, vê a própria identidade
(somente leitura: username, nome completo, e-mail, último login, papel)
e troca a própria senha com o formulário (senha atual + nova +
confirmação), com validadores do projeto aplicados e sem perder a
sessão corrente. Link "Perfil" aparece na área do usuário no sidebar.

## Contexto necessário (leia antes de editar)

- `openspec/changes/add-user-profile-and-self-service-password/design.md`
  — decisões D1/D2 (sem custom user; `PasswordChangeForm` nativo +
  `update_session_auth_hash`).
- `apps/accounts/` — app vazia (apenas `apps.py`), já registrada em
  `INSTALLED_APPS` (`config/settings.py:35`).
- `config/urls.py` — inclui apps por `include("apps.<app>.urls")`;
  login nativo em `/login/` (`auth_views.LoginView`) e
  `django.contrib.auth.urls` na raiz (`logout` name existe).
- `templates/registration/login.html` — referência de estilo
  (card Bootstrap, `bi` icons, `form-label small fw-semibold
  text-muted`, botões padrão).
- `templates/base_sidebar.html` + `templates/includes/sidebar.html` —
  layout do portal autenticado; o bloco do usuário autenticado
  (`{% if user.is_authenticated %}`, ~linha 65) é onde entra o link
  "Perfil".
- `tests/integration/test_portal_entry_auth.py` — referência de estilo
  de testes (fixtures `client`/`registered_user`, classes por grupo,
  `pytest.mark.django_db` por teste quando necessário).
- Settings: `AUTH_PASSWORD_VALIDATORS` padrão (similarity, length,
  common, numeric), `LOGIN_URL="/login/"`.

## Requisitos verificáveis

- R1: `GET /perfil/` anônimo → redirect para `/login/` (com `next`).
- R2: `GET /perfil/` autenticado → 200 renderizando username, nome
  completo e último login do usuário logado; nenhum campo de
  identidade editável (form só de senha).
- R3: `POST /perfil/` com senha atual errada → re-render com erro de
  campo e senha armazenada inalterada (login antigo continua válido).
- R4: `POST /perfil/` válido → nova senha autentica em novo login; a
  sessão corrente permanece autenticada (sem re-login) —
  `update_session_auth_hash`.
- R5: `POST /perfil/` com nova senha fraca (ex.: `abc123` — falha em
  `CommonPasswordValidator`/`MinimumLengthValidator`) → erro de
  validação e senha inalterada.
- R6: sucesso exibe mensagem amigável (messages framework ou banner no
  template) e o sidebar logado contém link para `/perfil/`
  (`{% url 'accounts:profile' %}`).

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/accounts/views.py            # novo
  - apps/accounts/urls.py             # novo (app_name="accounts")
  - config/urls.py                    # include "perfil/" -> apps.accounts.urls
  - templates/accounts/profile.html   # novo (estende base_sidebar)
  - templates/includes/sidebar.html   # link "Perfil" no bloco do usuário
  - tests/integration/test_accounts_profile.py  # novo
allowed_incidental_files: []
out_of_scope:
  - UserProfile/model/migration/middleware/command (SLICE-AUP-S2)
  - custom user, AUTH_ settings, admin, specs, tasks.md
  - qualquer mudança em apps/services_portal ou outros templates
```

Se precisar tocar algo fora desta lista, PARE e reporte bloqueio.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| R1 | `apps/accounts/views.py`, `tests/integration/test_accounts_profile.py` | `test_anonymous_profile_redirects_to_login` |
| R2 | idem + `templates/accounts/profile.html` | `test_profile_shows_own_identity_readonly` |
| R3 | idem | `test_wrong_current_password_is_rejected` |
| R4 | `apps/accounts/views.py` | `test_successful_change_keeps_session_and_new_password_works` |
| R5 | idem | `test_weak_new_password_is_rejected` |
| R6 | `templates/accounts/profile.html`, `templates/includes/sidebar.html` | `test_success_message_is_shown`, `test_sidebar_links_to_profile` |

## Plano de testes do slice

### RED

- comando: `uv run pytest -q tests/integration/test_accounts_profile.py`
- falha esperada: falhas por ausência de rota/comportamento (`/perfil/`
  não existe; app sem urls) — os testes falham porque o comportamento
  não existe, provando que nada foi entregue antes da implementação.

### GREEN

- o mesmo comando — exit 0 com os testes R1–R6 passando.

### Verificação do slice

- `uv run pytest -q tests/integration/test_portal_entry_auth.py` —
  exit 0 (regressão de auth do portal: login/logout/redirect intactos).
- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`
- `uv run openspec validate add-user-profile-and-self-service-password --strict`

## Notas de implementação

- View: `LoginRequiredMixin` + `PasswordChangeForm`; POST válido →
  `form.save()` + `update_session_auth_hash(request, request.user)` +
  message + redirect para a própria `/perfil/` (PRG).
- Papel exibido: `admin` se `is_superuser`, senão `usuário comum`
  (os dois únicos papéis do sistema — design/proposal).
- Template: uma página, dois cards Bootstrap (identidade readonly;
  troca de senha) — siga a linguagem de `registration/login.html`;
  renderize erros por campo como o Django entrega.
- Não use templates default do Django para password change: a página é
  esta, com o estilo do portal.

## Critérios de aceitação

- [ ] R1..R6 verdes
- [ ] Regressão `test_portal_entry_auth.py` verde
- [ ] Gates do slice verdes
- [ ] Relatório em `/tmp/sirhosp-slice-AUP-S1-report.md` com
      before/after, comandos e resultados
