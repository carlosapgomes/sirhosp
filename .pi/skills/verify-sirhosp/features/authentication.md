# Authentication

Login through the real form gets each ephemeral role into the authenticated
shell, and `Sair` ends the session back on the public landing. Proven:
playwright (`verify_portal.py run --feature auth`). Demonstrated: mcp
(login as `verify_user`, shell, logout).

## Sub-features

- `auth-form-empty` shows the empty login form with `Usuário`, `Senha`,
  and `Entrar`.
- `auth-login-user` logs `verify_user` in through the real form.
- `auth-login-admin` logs `verify_admin` in through the real form.
- `auth-shell` renders the authenticated shell with the run identity.
- `auth-logout` ends the session through `Sair` back on the public Prisma
  landing (`Entrar no portal`), with authenticated access ended.
- `auth-protected` redirects an unauthenticated `/painel/` visit to login.

## How to get to it (user POV)

- Open `https://portal-dev.verification.invalid/login/` in a fresh exclusive
  browser context.
- Fill `Usuário` (`#id_username`) and `Senha` (`#id_password`).
- Choose `Entrar` (the form submit button).
- Land on `/painel/` with the sidebar footer showing the username.
- Choose `Sair` (sidebar footer, `form[action='/logout/']`) to leave.

## Driving it with Chrome DevTools MCP

Preconditions:

- Doctor PASS; session ACTIVE with in-memory passwords for the run.
- One exclusive context, e.g. `sirhosp-<run-id>-user`; `list_pages`
  recorded before creating the run page.

- **Empty form.** Navigate to `/login/`. Run `take_snapshot` and confirm
  `textbox Usuário`, `textbox Senha`, and `button Entrar`. Run
  `take_screenshot` with `filePath` to the run evidence dir before any fill.
  End state: `shot-login-empty.png` with `Acesso ao portal` and empty fields.
- **Fill.** Run `fill` on the `textbox Usuário` uid with the username, then
  `fill` on the `textbox Senha` uid with the in-memory password. Passwords
  travel only in tool arguments, never in logs or files. Resolve uids by
  role plus name: labels (`StaticText Usuário`) and fields are separate
  nodes, and filling the label silently proves nothing.
- **Submit.** Run `click` on the `button Entrar` uid. Run `wait_for` with
  text `["Sair", "Perfil"]`. End state: `RootWebArea` url ends in `/painel/`.
- **Shell proof.** Run `take_snapshot` and confirm the footer shows the run
  username plus `Perfil` and `Sair`. Run `take_screenshot` to the evidence
  dir. End state: authenticated shell with the run identity visible.
- **Logout.** Run `click` on the `button Sair` uid. Run `wait_for` with text
  `["Acesso ao portal", "Usuário"]`. Run `take_screenshot` to the evidence
  dir. End state: public Prisma landing with `Entrar no portal` (proving
  authenticated access ended), no authenticated shell.
- **Protected route.** In a logged-out context, navigate to `/painel/` and
  confirm the redirect to the login route. End state: `Acesso ao portal`.
- **Proof.** Screenshots `shot-login-empty.png`, `shot-painel.png`,
  `shot-logout.png` plus sanitized snapshots, all under
  `/tmp/sirhosp-verification-mcp/<run-id>/`, surviving `close`.

## Gotchas

- Filling the `StaticText` label uid instead of the `textbox` uid submits an
  empty form and yields `Usuário ou senha inválidos.` Always match the role.
- Uid prefixes change after navigation (`1_7` becomes `2_9`); re-snapshot
  after every navigation instead of reusing uids.
- `wait_for` on shell words can match stale content; assert the snapshot
  `RootWebArea` url (`/painel/`) and the footer identity, not just the wait.
- An interrupted run loses its passwords. Never retransmit: `close` the run
  and `open` a new one.
- Login writes the session and `last_login`: the only expected writes. Any
  other mutation fails the run.
