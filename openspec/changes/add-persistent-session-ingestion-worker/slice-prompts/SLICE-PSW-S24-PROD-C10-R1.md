# Slice Prompt — PSW-S24-PROD-C10-R1 Renewal Completion Wait

## Handoff

Start from zero context. Read `AGENTS.md`, the active OpenSpec change,
PSW-S24-PROD-C10, commit `a331703`, the concrete Playwright handle, and its
focused tests. Implement only the post-click completion wait proven necessary
by the production retest.

## Production RED

At minute 30 the real popup was visible. The popup-scoped action plus DOM
fallback executed: three seconds later the popup was absent and the countdown
had advanced. However, the controller's immediate verification ran before the
PrimeFaces update completed and returned false. The browser action therefore
worked, but the session was incorrectly rejected during the asynchronous UI
transition.

## Goal

Make the concrete renewal click return only after its scoped control becomes
hidden. Preserve the controller's fail-closed re-read, typed timeout semantics,
sanitation, and the absence of arbitrary sleeps.

## Allowed Scope

At most four versioned files:

1. `apps/ingestion/extractors/playwright_session_handle.py`;
2. `tests/unit/test_playwright_session_handle.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`; and
4. this prompt.

No controller, policy, queue, extraction, retry, deployment, or configuration
changes are allowed.

## TDD

Add focused tests proving both the normal click and DOM fallback wait for the
scoped control to become hidden with a bounded timeout. Prove a real Playwright
timeout from that completion wait becomes the existing sanitized typed
`ExtractionTimeoutError`. Capture RED, implement the minimum wait, and run the
whole handle/controller/session-policy focused set.

## Verification

Run official unit, integration, and quality gates; strict OpenSpec; Markdown
lint; and diff checks. Commit and push before rebuilding production.

Repeat one authorized production login with no activity for 30 to 35 minutes.
Success requires the popup to be observed, the handler to return ready, the
popup to be absent, the countdown to advance, teardown to complete, exit code
zero, no queue mutation, and no continuous worker left running.

Update `/tmp/sirhosp-slice-PSW-S24-PROD-C10-report.md` with sanitized evidence
and stop.
