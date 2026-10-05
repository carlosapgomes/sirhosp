# SIRHOSP verification map

This directory is the maintained source for verifying the user-facing
behavior of the SIRHOSP dev portal. Read this index before driving, then use
the matching feature file as the recipe.

## Baseline preconditions

- Target is dev at `https://portal-dev.verification.invalid`. Production
  `https://portal-prod.verification.invalid` is forbidden.
- The operator confirms the dataset is fictitious
  (`--confirm-fictitious` / `--confirm-synthetic-data` is that attestation).
- `verify_portal.py doctor --target dev --confirm-fictitious` reports PASS.
- One session per target: `open` emits ephemeral passwords for `verify_user`
  and `verify_admin` once; keep them in memory, never in state or reports.
- MCP runs use one exclusive browser context per run and role
  (`new_page` with `isolatedContext`); never drive a session that was not
  started by this verification run.
- Workers stay stopped. Never start ingestion to make a badge green.

## Driving conventions

- Start every recipe from the baseline state unless its preconditions say
  otherwise.
- Prefer accessible names and stable handles over coordinates or DOM
  position: `Usuário`, `Senha`, `Entrar`, `Censo`, `Perfil`, `Sair`,
  `Filtrar`, `#id_username`, `#id_password`, `#sidebar`, `#sidebarToggle`,
  `#sidebarOverlay`, `.sirhosp-topbar-sync`, `#q`, `#unidade`,
  `#especialidade`.
- Treat every command as literal. Keep quoted names and flags unchanged.
- Read-only routes only: `/`, `/login/`, `/painel/`, `/censo/`, `/perfil/`,
  `/atualizacao-censo/`, `/static/`. POST only on `/login/` and `/logout/`.
- Mutating routes are forbidden even as GET: `/ingestao/*`, exports
  (`/censo/exportar/`, `/statistics/export/`, `/reconciliacao/exportar/`),
  password change, CRUD, summary runs.
- This skill is not a firewall and does not apply the S2 Playwright request
  interceptor to MCP tools; route discipline is operator behavior. Supervise
  every navigation and compare effects at close.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final
  screen: empty form, authenticated shell with the run identity, each mapped
  page, post-logout public landing.
- MCP proof includes a screenshot plus a sanitized snapshot or notes entry
  with the portal identity visible. Snapshots never contain passwords,
  cookies, tokens, HAR, or storage state.
- Record the feature id and entry point used with every artifact.
- Report an unreachable path with the attempted command and the unmet
  precondition. A positive census filter without the operator-supplied
  synthetic descriptor is BLOCKED, never PASS.
- Do not report a skipped entry point as verified through a different path.
- Coverage honesty: `proven: playwright` means the S2 scripted run covers
  it; `demonstrated: mcp` means one assisted round drove it; `future` means
  mapped but not yet executed. Documenting is not proving.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the
user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short ids with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with Chrome DevTools MCP` starts with `Preconditions:` and
   uses labeled bullets that pair each user action with an exact command and
   observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable
handles, required state, commands, and observable proof.

## Features

- [Authentication](./authentication.md) covers the login form, both roles,
  the authenticated shell, and logout. Proven: playwright. Demonstrated: mcp.
- [Navigation](./navigation.md) covers the sidebar, active menu, profile
  page, and per-role visibility. Proven: playwright (shell, role
  visibility). Demonstrated: mcp (shell, profile read).
- [Census](./census.md) covers filters, TomSelect, and the patient table.
  Proven: playwright (TomSelect init, filter round-trip). Demonstrated: mcp
  (page read). Positive filter with operator descriptor: future for MCP.
- [HTMX](./htmx.md) covers the periodic sync badge and the mobile menu.
  Proven: playwright (two real 60 s polls, mobile open/close). Demonstrated:
  mcp (badge read). Timed poll observation: future for MCP.
