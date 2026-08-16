# Slice Prompt — PSW-S24-PROD-C10 Renewal Popup Correction

## Handoff

Start from zero context. Read `AGENTS.md`, the active OpenSpec change, the
PSW-S24 prompt and reports, the session policy/controller, the concrete
Playwright handle, and their focused tests. Implement only the production-proven
renewal-popup correction described here.

## Production RED

An authenticated real session was left completely idle. At minute 30 the
renewal popup and session countdown were both present. The controller attempted
`.ui-confirmdialog-yes`, the concrete handle logged a sanitized click failure,
and `ensure_ready()` still returned true because it accepted the stale counter.
After three seconds the popup remained visible and the counter had not advanced.
No queue row was claimed or mutated.

## Goal

Make defensive renewal use the popup-scoped affirmative action and fail closed
when the popup remains visible. Retain typed timeout propagation and sanitized
logging. Prove the real popup clears and the countdown advances after another
30-minute idle production probe.

## Allowed Scope

At most seven versioned files:

1. `apps/ingestion/extractors/session_policy.py`;
2. `apps/ingestion/extractors/session_controller.py`;
3. `apps/ingestion/extractors/playwright_session_handle.py`;
4. `tests/unit/test_session_controller.py`;
5. `tests/unit/test_playwright_session_handle.py`;
6. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`; and
7. this prompt.

Do not change queue, claim, retry, extraction, persistence, deployment, or
continuous-worker defaults. If more files are required, stop and report the
blocker.

## TDD

### RED

Add focused tests proving:

- the renewal selector is scoped to `#casca_renovasession`;
- a visible popup plus valid countdown cannot return ready when the click leaves
  the popup visible;
- `renew_if_needed()` also fails closed when the popup remains visible;
- a normal Playwright click failure receives one DOM-click fallback while a
  typed Playwright timeout still propagates without fallback; and
- successful popup dismissal retains the existing ready path.

Run the focused tests and capture the initial failures.

### GREEN

Implement the minimum correction:

- scope the affirmative selector to the renewal popup;
- use one direct DOM-click fallback only for non-timeout Playwright click
  failures; and
- re-read the DOM and reject readiness/renewal while the popup remains visible.

Keep all errors and logs constant and sanitized.

### REFACTOR

Remove duplicated popup-handling logic only if it clarifies the fail-closed
invariant. Do not widen the browser API or add sleeps to production code.

## Verification

Run focused tests, official unit, integration, quality gate, strict OpenSpec,
and Markdown lint for every changed Markdown file. Then commit and push before
rebuilding production.

Repeat the authorized production probe with one login, no activity for 30 to
35 minutes, no queue claim, and sanitized output. Success requires:

- popup observed;
- handler reports ready;
- popup absent after handling;
- countdown advanced;
- teardown and command exit zero; and
- no continuous worker left running.

Create `/tmp/sirhosp-slice-PSW-S24-PROD-C10-report.md` with literal before/after
fragments, commands/results, sanitized production evidence, risks, and next
step. Stop after this slice.
