# SLICE-AUP-S2 — Senha provisória e troca obrigatória no primeiro login

## Objetivo

Operador provisiona usuários comuns por comando sem escolher senha
(sistema gera provisória, exibe uma única vez, marca flag
`must_change_password`); usuário com flag é forçado a trocar a senha em
`/perfil/` antes de usar qualquer outra página do portal (middleware
centralizado com allowlist); a troca bem-sucedida (implementada no
SLICE-AUP-S1) passa a limpar a flag. Perda de senha é resolvida com
`--reset-password`.

## Contexto necessário (leia antes de editar)

- `openspec/changes/add-user-profile-and-self-service-password/design.md`
  — decisões D1/D3/D4/D5 (perfil 1:1; middleware com allowlist;
  `secrets.token_urlsafe(12)`; admin nunca é criado pelo comando).
- O slice anterior entregou `/perfil/` com troca funcional
  (`apps/accounts/views.py`, `templates/accounts/profile.html`,
  `tests/integration/test_accounts_profile.py`).
- `config/settings.py` — `MIDDLEWARE` (o novo middleware entra após os
  de sessão/auth — posição mínima que garante `request.user`
  populado).
- Padrão de management command do projeto: ver qualquer comando curto
  em `apps/*/management/commands/` (ex. `apps/discharges/management/
  commands/refresh_daily_discharge_counts.py`) para estilo de
  `BaseCommand`/`add_arguments`/stdout.

## Requisitos verificáveis

- R1: `UserProfile` OneToOne com `User`, campos `must_change_password`
  (bool, default `False`) e `created_at`; migration criada e aplicável.
- R2: middleware — autenticado com flag → qualquer path fora da
  allowlist responde redirect para `/perfil/`; paths da allowlist
  (`/perfil/`, `/login/`, `/logout/`, `/admin/`, `/static/`, `/health/`)
  seguem normais; anônimos nunca são redirecionados pelo middleware
  (o `/health/` fica na allowlist para que probes de monitoramento,
  mesmo autenticados, nunca recebam redirect).
- R3: sem flag (ou sem perfil) → nenhuma interferência (resposta
  idêntica ao comportamento pré-slice).
- R4: troca de senha bem-sucedida em `/perfil/` limpa a flag (perfil
  existente) — depois, `/painel/` responde normal.
- R5: `create_portal_user <username> --full-name "..."` cria usuário
  ativo comum (`is_staff=False`, `is_superuser=False`), com nome
  completo armazenado segundo a regra `--full-name` (abaixo), senha
  provisória aleatória aplicada com `set_password`, e perfil com
  `must_change_password=True`; o stdout contém exatamente uma
  ocorrência do token em uma linha estável no formato
  `temporary_password=<token>` (nenhuma outra linha contém o token).
- R6: a senha impressa autentica o usuário (login funcional) e o
  usuário é imediatamente forçado à troca (R2).
- R7: `create_portal_user --reset-password <username>` reemite senha
  provisória (impressa uma vez) e religa a flag para usuário existente;
  username inexistente → erro claro.
- R8: username duplicado no modo create → erro explícito e nenhuma
  mutação.
- R9: nenhuma senha em claro é persistida (banco guarda apenas o hash)
  nem impressa fora da linha `temporary_password=` do stdout do
  comando.

Regra `--full-name`: a PRIMEIRA palavra vira `User.first_name`, o
restante (strip) vira `User.last_name`; com uma palavra só,
`last_name` fica vazio. O perfil exibe `user.get_full_name()`.

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/accounts/models.py                 # novo: UserProfile
  - apps/accounts/migrations/__init__.py    # novo (app sem migrations hoje)
  - apps/accounts/migrations/0001_initial.py  # novo (makemigrations)
  - apps/accounts/middleware.py             # novo
  - apps/accounts/views.py                  # limpeza da flag na troca
  - apps/accounts/management/commands/create_portal_user.py  # novo
  - config/settings.py                      # registro do middleware
  - tests/integration/test_accounts_profile.py       # casos novos (troca limpa flag)
  - tests/integration/test_accounts_provisional.py   # novo: middleware + comando
  - tests/unit/test_create_portal_user.py    # novo: unidade do comando (opcional se tudo coberto em integração)
allowed_incidental_files: []
out_of_scope:
  - alterar templates do S1 além de mensagens já existentes
  - custom user, AUTH_ settings/backends, admin
  - recuperação por e-mail, papéis/grupos novos
  - specs, tasks.md
```

Se precisar tocar algo fora desta lista, PARE e reporte bloqueio.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| R1 | `apps/accounts/models.py` + migration | `test_userprofile_flag_and_onetoone` (ou assert de campos + `migrate` no container check) |
| R2 | `apps/accounts/middleware.py`, `tests/integration/test_accounts_provisional.py` | `test_flagged_user_redirected_from_painel`, `test_allowlisted_paths_pass` (inclui `/health/`), `test_anonymous_never_redirected` |
| R3 | idem | `test_unflagged_user_unaffected` |
| R4 | `apps/accounts/views.py`, `tests/integration/test_accounts_profile.py` | `test_password_change_clears_flag_and_releases_portal` |
| R5 | `apps/accounts/management/commands/create_portal_user.py`, `tests/integration/test_accounts_provisional.py` | `test_create_user_common_active_with_flag_and_printed_password` (inclui: stdout tem exatamente 1 linha `temporary_password=<token>`; `first_name`/`last_name` seguem a regra split) |
| R6 | idem | `test_printed_password_authenticates_and_forces_change` |
| R7 | idem | `test_reset_password_reissues_and_reflags` |
| R8 | idem | `test_duplicate_username_fails_without_mutation` |
| R9 | idem | `test_no_plaintext_password_persisted` (hash check com `check_password`) |

## Plano de testes do slice

### RED

- comando: `uv run pytest -q tests/integration/test_accounts_provisional.py tests/integration/test_accounts_profile.py`
- falha esperada: `test_accounts_provisional.py` — `ImportError` em
  `apps.accounts.middleware`/`create_portal_user` e/ou `UserProfile`
  inexistente; o caso novo de `test_accounts_profile.py`
  (`test_password_change_clears_flag_and_releases_portal`) falha por
  ausência de modelo — provando que o comportamento não existe.

### GREEN

- o mesmo comando — exit 0 com todos os casos passando.

### Verificação do slice

- `uv run pytest -q tests/integration/test_portal_entry_auth.py
  tests/integration/test_accounts_profile.py` — exit 0 (regressão).
- `./scripts/test-in-container.sh check` (inclui `migrate` no stack de
  teste — valida a migration nova)
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`
- `uv run openspec validate add-user-profile-and-self-service-password --strict`

## Notas de implementação

- Middleware: verifique `request.user.is_authenticated` com try/except
  (acesse o perfil sob demanda; ausência de perfil = sem flag);
  allowlist por prefixos de path — constantes explícitas no módulo.
- Ordem em `MIDDLEWARE`: depois de `AuthenticationMiddleware` (linha
  seguinte é suficiente).
- Comando: `secrets.token_urlsafe(12)`; `--reset-password` é modo
  exclusivo (não cria); use `call_command` nos testes de integração
  capturando stdout; assert de senha: `client.login(username=...,
  password=printed)`.
- A flag nunca é limpa por nenhum caminho além da troca bem-sucedida
  em `/perfil/` (nem pelo reset, que religa).

## Critérios de aceitação

- [ ] R1..R9 verdes
- [ ] Regressões (`test_portal_entry_auth.py`, `test_accounts_profile.py`) verdes
- [ ] Migration aplicável (`check` no container verde)
- [ ] Gates do slice verdes
- [ ] Relatório em `/tmp/sirhosp-slice-AUP-S2-report.md`
