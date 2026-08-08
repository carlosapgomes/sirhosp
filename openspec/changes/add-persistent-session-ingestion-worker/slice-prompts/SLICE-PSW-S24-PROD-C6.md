# Slice Prompt — PSW-S24-PROD-C6

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production restart-lifecycle correction.

## Production evidence

Production single-run admissions extraction succeeded after C5 and naturally
enqueued both demographics and `full_sync` follow-ups. The four-ID bounded run
then completed only its first admissions row and emitted:

```text
Error stopping Playwright during restart (sanitized)
Persistent session restart failed (sanitized)
Persistent session restart failed during bounded validation;
stopping the bounded sequence.
```

The handle's normal shutdown already uses the public `Playwright.stop()` API,
but `restart_browser()` still calls the invalid `__exit__()` method on the
public Playwright object. Its relaunched persistent context also drops the
production proxy and HTTPS-tolerance options that initial startup applies.

## Scope

Maximum four versioned files:

1. `apps/ingestion/extractors/playwright_session_handle.py`;
2. `tests/unit/test_playwright_session_handle.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
4. this slice prompt.

Do not change login, navigation, extraction, queue selection, claim discipline,
intents, persistence services, Compose, or rollout defaults.

## TDD Contract

1. Add a failing restart regression requiring the old public Playwright object
   to receive `stop()` exactly once and forbidding `__exit__()`.
2. Add a failing restart regression requiring the relaunched context to retain
   the configured production proxy and `ignore_https_errors=True`.
3. Preserve browser close, profile release/reacquire, fresh Playwright startup,
   and fresh persistent-context launch.
4. Keep startup and shutdown behavior unchanged.
5. Preserve sanitized lifecycle warnings.

## Acceptance

- RED: both restart contracts fail before implementation.
- Targeted restart tests pass after implementation.
- Unit suite passes in the official container.
- Official quality gate passes.
- LSP diagnostics are clean for changed Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C6-report.md` with summary, checklist,
  changed files, literal before/after fragments, commands/results, risks, and
  next step.
- Commit and push the four-file slice before production rebuild.
- PSW-S24 remains incomplete until the same four selected rows complete in
  order, including restart/rebootstrap before row four.
