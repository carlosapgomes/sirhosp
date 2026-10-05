# HTMX

The topbar sync badge (`.sirhosp-topbar-sync`) polls the census badge
endpoint every 60 s via HTMX and swaps itself without reload; the mobile
sidebar opens and closes by click. Proven: playwright (two real polls on the
real interval, mobile toggle/overlay/Escape). Demonstrated: mcp (badge
read). Timed poll observation: future for MCP.

## Sub-features

- `htmx-badge-present` renders exactly one `.sirhosp-topbar-sync` badge.
- `htmx-badge-polls` observes real poll responses on the 60 s interval.
- `htmx-badge-swaps` shows the badge label after swaps without reload.
- `htmx-no-login-insert` never inserts login markup into the badge area.
- `htmx-mobile-toggle` opens and closes the sidebar by click and Escape.

## How to get to it (user POV)

- Log in on desktop (1440x900): the topbar shows `Censo: --:--` or a time.
- Wait: every 60 s the badge refreshes in place from
  `/atualizacao-censo/` without a page reload.
- On mobile (390x844): choose `Menu` (`#sidebarToggle`) to open the
  sidebar; choose the overlay or press Escape to close.

## Driving it with Chrome DevTools MCP

Preconditions:

- Authenticated on `/painel/`; snapshot confirms one `.sirhosp-topbar-sync`
  node (badge markup in `templates/includes/topbar_sync.html`: `hx-get`
  census badge, `hx-trigger="every 60s"`, `hx-swap="outerHTML"`).

- **Badge present.** From the snapshot, confirm the `Censo:` label node and
  screenshot the topbar. End state: badge read, no login markup inside.
- **Polls (future for MCP).** Observe two real `GET /atualizacao-censo/`
  200 responses on the real 60 s interval (no DOM substitution), then
  confirm one badge and no inserted login. The scripted S2 run proves this
  today with `POLL_COUNT = 2`; an MCP round has only read the badge so far.
  End state: two timed responses plus post-swap badge, recorded in notes.
- **Mobile toggle (future for MCP).** In a 390x844 context, click
  `#sidebarToggle`, confirm the menu opens; click `#sidebarOverlay` and
  confirm it closes; reopen and press Escape with the same result. End
  state: open/close states observed by click, not by class assignment.
- **Observations.** `list_console_messages` with type `error` must be empty;
  `list_network_requests` must show no POST outside `/login/`/`/logout/`
  and no export or `/ingestao/` navigation. End state: notes entry with the
  finding (including an honestly empty listing).
- **Proof.** Screenshots plus notes under
  `/tmp/sirhosp-verification-mcp/<run-id>/`.

## Gotchas

- The badge has a class, not an id: select `.sirhosp-topbar-sync`, never a
  `#sync` id that does not exist.
- Waiting a fixed sleep instead of the real 60 s interval proves nothing
  about polling; S2 waits for the actual responses with a 90 s timeout.
- The edge-injected telemetry request is refused and recorded separately in
  S2; it is telemetry, not product behavior, and never fails a clean run.
- The badge self-rearms by swapping `outerHTML` with identical attributes;
  asserting on a stale node after a swap reads a detached element.
- Topbar markup lives in `templates/includes/topbar_sync.html` and
  `templates/includes/topbar.html`; changes there must update this file and
  its proof.
