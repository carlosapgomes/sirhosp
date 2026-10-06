---
name: verify-sirhosp
description: Drive the SIRHOSP dev portal (Django + HTMX) the way a user does with Chrome DevTools MCP and ephemeral accounts: doctor, open, login journeys on prismadev, evidence, close. Use for assisted browser verification of the dev portal when the scripted Playwright run is not the right tool.
---

# Skill: verify-sirhosp

Drive the real SIRHOSP dev portal with Chrome DevTools MCP, read-only, with
ephemeral accounts owned by one verification session. This skill teaches a
zero-context executor to open a session, drive mapped features, capture
evidence, and close without leaving accounts or pages behind.

Authoritative references (read before driving):

- `docs/dev-verification.md` — session runbook (doctor/open/status/close/run).
- `.pi/skills/verify-sirhosp/features/` — feature map (recipes per feature).
- `openspec/changes/add-dev-browser-verification-suite/design.md` — D3, D4, D8.

Canonical target:

- The dev portal origin comes only from the validated `doctor` JSON
  (`origin` field): drive exactly that value, never a memorized address.
- The configured production origin is forbidden. Never navigate there.
- Before navigating, confirm `open.origin == doctor.origin`. On any
  divergence, close the owned session with the canonical `close` command
  and return BLOCKED for operator revalidation; never silently follow
  the new origin.

## Launch

There is no app server to start. The dev portal already runs on the dev
checkout (web on host 8001 behind the edge, database in the dev engine).
A verification run creates one ephemeral session, not infrastructure:

```bash
uv run python scripts/verify_portal.py open --target dev --confirm-fictitious
```

The command prints one JSON object with `run_id`, `target`, and `passwords`
exactly once. Keep passwords in memory. Never store them in state, reports,
argv, or logs. Never retransmit: after an interruption, close and open anew.

MCP browser precondition: the Chrome DevTools MCP server runs headless with
its own browser profile (`chrome-devtools-mcp --headless`). It never attaches
to the operator's personal browser session. If the MCP tools are unavailable,
return BLOCKED, do not reconfigure `.pi/mcp.json`, do not install a browser,
and do not silently substitute Playwright.

Coverage honesty: this skill maps features; the map marks each feature as
proven by the scripted Playwright run (`verify_portal.py run`), demonstrated
with MCP in a specific round, or future. Documenting a feature is not proving
it. Do not claim a feature verified through a path that was never executed.

## Doctor

Run the read-only preflight before every open, and whenever anything looks off:

```bash
uv run python scripts/verify_portal.py doctor --target dev --confirm-fictitious
```

Require `{"status":"PASS"}`. Doctor confirms the private origin profile,
the dev target, the checkout, the database fingerprint, pending migrations,
`DEBUG` false, stopped workers, and the owned-pair state, without writing
anything. Record the `origin` value from the JSON: it is the only target
this round may drive. A non-PASS doctor is BLOCKED before any account is
written. Confirm with the operator that the dev dataset is fictitious;
`--confirm-fictitious` is that attestation.

## Drive

Drive only mapped read-only journeys from `features/`, one exclusive MCP
browser context per run and role:

1. Create the run page with an isolated context named after the run id, e.g.
   `sirhosp-<run-id>-user`. Request one context per run and role via
   `new_page` `isolatedContext`; never reuse the operator's session or any
   pre-existing page. Storage isolation of distinct `isolatedContext`
   values was demonstrated on the installed server (`chrome_devtools
   1.10.1`): a marker stored in context A (`localStorage` plus a test
   cookie) read back absent in context B and present on re-read in A —
   evidence `/tmp/sirhosp-verification-mcp/isolation-probe/notes.json`.
   If isolation cannot be confirmed on the installed server, treat it as
   BLOCKED per D8; never assume it.
2. Confirm `list_pages` before and after: only pages created by this run may
   be closed by this run.
3. Navigate only dev-portal reads: `/`, `/login/`, `/painel/`, `/censo/`,
   `/perfil/`, `/atualizacao-censo/`, `/static/`. POST only on `/login/` and
   `/logout/`.
4. Never visit mutating routes, even as GET: `/ingestao/*`, `/censo/exportar/`,
   `/statistics/export/`, `/reconciliacao/exportar/`, password change, CRUD,
   or summary runs. Workers stay stopped; never start ingestion to make a
   badge green.
5. Log in through the real form (`#id_username`, `#id_password`, button
   `Entrar`), never `force_login`, mocks, or internal setters. Take the empty
   form screenshot before filling.
6. Log out through the `Sair` button and confirm the return to the public
   Prisma landing (entry `Entrar no portal`, authenticated shell gone).

Concrete handles live in the feature files. Prefer accessible names
(`Usuário`, `Senha`, `Entrar`, `Censo`, `Perfil`, `Sair`, `Filtrar`) over
coordinates. Snapshot uids come from `take_snapshot`; resolve the element
role first (e.g. `textbox` + `Usuário`, `button` + `Entrar`), because labels
and fields are separate nodes.

This skill is not a firewall and does not apply the Playwright request
interceptor: MCP tools are unrestricted by nature. The route discipline above
is operator behavior, not mechanical enforcement. Supervise every navigation
and compare effects at close. Any deviation, unavailable isolation, or
missing tool is BLOCKED or FAIL, never silent.

## Evidence

Write MCP-run evidence to `/tmp/sirhosp-verification-mcp/<run-id>/`:

- Screenshots before and after relevant actions, starting with the empty
  login form. No screenshot may show a filled password field.
- Sanitized snapshots/notes JSON: methods, hosts, paths without query
  strings, filtered console errors. Never cookies, tokens, HAR, passwords,
  or storage state.
- The close/status/owned-status outputs proving revocation.

Capture the action and the resulting state, not just the final screen: login
form empty, authenticated shell with the `verify_user` identity, each mapped
page visited, and the post-logout public landing (`shot-logout.png` shows
  the Prisma landing with `Entrar no portal`, not the login form). A proof that drives one entry
point is incomplete when the map lists others; record the feature id and
entry point used with every artifact, and report unreachable paths with the
attempted command and the unmet precondition.

## Cleanup

Cleanup removes session state and run pages, never evidence:

1. `close_page` only for pages this run created (compare `list_pages`
   before/after). Never close foreign pages; never kill processes by generic
   pattern.
2. Close the session, which revokes both owned accounts first:

   ```bash
   uv run python scripts/verify_portal.py close --target dev
   ```

   Require `{"status":"PASS","revoked":true}`.
3. Confirm the durable record:

   ```bash
   uv run python scripts/verify_portal.py status --target dev
   ```

   Require `{"state":"CLOSED"}` for the run id.
4. Confirm the evidence directory still exists with screenshots and notes
   after cleanup. A cleanup that eats the proof fails the run.

`close` is repeatable and safe. If revocation fails, the record stays
`CLOSING`: contain web before stopping db, retry close, never report PASS.

## Helpers

Canonical commands (run from the repo root; every command targets dev only):

```bash
uv run python scripts/verify_portal.py doctor --target dev --confirm-fictitious
uv run python scripts/verify_portal.py open --target dev --confirm-fictitious
uv run python scripts/verify_portal.py status --target dev
uv run python scripts/verify_portal.py close --target dev
uv run python scripts/verify_portal.py close --target dev --run-id <run-id>
uv run python scripts/verify_portal.py close --target dev --recover
```

MCP tools used by this skill (server `chrome_devtools`, stdio, headless):

- `list_pages` — inventory before/after; the only close authority.
- `new_page` with `isolatedContext` — exclusive context per run/role.
- `navigate_page` — read-only route navigation.
- `take_snapshot` — resolve element uids by role plus accessible name.
- `fill`, `click` — real form interaction; passwords only in tool arguments,
  transiently, never in logs or files.
- `take_screenshot` with `filePath` — proof artifacts.
- `list_network_requests`, `list_console_messages` — read-only observations.
- `close_page` — owned pages only.
- `wait_for` — wait for user-visible text (`Sair`, `Perfil`), never a
  fixed sleep for product behavior.

Modes: assisted MCP driving (this skill) is implemented and demonstrated;
the repeatable scripted driver is the separate S2 command and stays the
proof of record for regression:

```bash
uv run python scripts/verify_portal.py run --feature auth --role both --confirm-synthetic-data
uv run python scripts/verify_portal.py run --feature smoke --role both --confirm-synthetic-data
```

Future and out of scope: driving mutating operations, new credentials flows,
attaching to a personal browser, and any production target. Those need
another scope, not an extension of this skill by habit.
