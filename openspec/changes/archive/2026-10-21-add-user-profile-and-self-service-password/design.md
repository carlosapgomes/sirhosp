# Design: add-user-profile-and-self-service-password

## D1. Sem custom user: perfil 1:1 em `apps.accounts`

`AUTH_USER_MODEL` permanece `django.contrib.auth.models.User`. A flag de
senha provisória vive em `apps.accounts.UserProfile` (OneToOne com
`User`, campo `must_change_password`, `created_at`), criada sob demanda.
Trocar para custom user numa base de produção em uso não justifica o
risco; o perfil 1:1 resolve o requisito com uma migration pequena e
isolada em `apps.accounts` (nenhuma tabela de `auth` é tocada).

## D2. Troca de senha com primitivas nativas

- Formulário: `django.contrib.auth.forms.PasswordChangeForm` (exige senha
  atual; aplica `AUTH_PASSWORD_VALIDATORS` já configurados).
- View: `PasswordChange` em `apps/accounts/views.py`, disponível apenas
  para autenticados (`LoginRequiredMixin`); em caso de sucesso chama
  `update_session_auth_hash` (o usuário não é deslogado da sessão
  corrente) e limpa `must_change_password` quando o perfil existir
  (comportamento completo no SLICE-AUP-S2).
- Templates: `templates/accounts/profile.html` estende
  `base_sidebar.html` — mesma linguagem visual do portal (cards, bi
  icons, `form-label small fw-semibold text-muted` como em
  `registration/login.html`). Nenhum template default do Django é
  usado; nada depende de `django.contrib.auth.urls` além do que já
  existe (login/logout).
- Identidade (username, nome completo, e-mail, último login, papel) é
  exibida somente leitura na mesma página.

## D3. Força de troca no primeiro login via middleware centralizado

`apps/accounts/middleware.py::RequirePasswordChangeMiddleware`: se o
usuário está autenticado, tem perfil com `must_change_password=True` e o
path não está na allowlist, responde redirect para `/perfil/`.
Allowlist (prefixos): `/perfil/`, `/login/`, `/logout/`, `/admin/`,
`/static/`, `/health/`, `/accounts/` (futuro). O `/health/` fica na
allowlist para que probes de monitoramento — mesmo autenticados —
nunca recebam redirect. Middleware é o ponto único — não se
decora cada view do portal; views novas herdam a regra
automaticamente. `/admin/` fica na allowlist como break-glass do
operador (admin com senha provisória consegue operar o Django admin,
mas o portal continua forçando a troca).

## D4. Provisionamento sem escolha de senha

`manage.py create_portal_user <username> --full-name "..."`:

- cria `User` ativo, **sem** `is_staff`/`is_superuser` (usuário comum —
  os únicos dois papéis do sistema são admin e comum; admin é criado
  pelo Django admin, nunca por este comando);
- `--full-name`: a primeira palavra vira `first_name`, o restante
  (strip) vira `last_name`; uma palavra só deixa `last_name` vazio; o
  perfil exibe `user.get_full_name()`;
- senha provisória `secrets.token_urlsafe(12)` aplicada com
  `set_password` (hash normal; validadores NÃO se aplicam à provisória
  — ela existe para ser trocada à força no primeiro login);
- cria `UserProfile` com `must_change_password=True`;
- stdout com contrato estável: uma linha `temporary_password=<token>`
  — o token aparece exatamente uma vez em todo o stdout (nunca em
  logs, nunca duplicado).

Modo `--reset-password <username>`: reemite senha provisória para
usuário existente e religa a flag (substitui a recuperação por e-mail,
que não existe no hospital). Idempotência: recriar username existente
falha com erro claro.

## D5. Segurança e auditoria

- Nenhuma senha (provisória ou nova) é persistida em claro ou
  registrada em log; a provisória existe apenas no stdout do comando.
- Falha de validação na troca re-renderiza o form com erros por campo
  (padrão Django); mensagens não revelam dados de outros usuários.
- O middleware nunca redireciona requisições não autenticadas (o
  `@login_required` das views decide o fluxo para anônimos).
- Password check da troca usa `check_password` via form nativo
  (timing-safe).

## Plano de teste

- S1 (perfil + troca): integração com `django.test.Client` — anônimo →
  redirect login; autenticado vê próprios dados; senha atual errada →
  erro e senha intacta; troca válida → nova senha autentica, sessão
  corrente permanece autenticada; validador de senha rejeita senha
  fraca.
- S2 (provisória + middleware + comando): flag ativa → `/painel/`
  redireciona para `/perfil/`; allowlist passa direto; troca limpa a
  flag e libera o portal; comando cria usuário comum ativo com flag e
  senha exibida que autentica; `--reset-password` reemite e religa a
  flag; stdout não vaza em logs (assert no output capturado).
