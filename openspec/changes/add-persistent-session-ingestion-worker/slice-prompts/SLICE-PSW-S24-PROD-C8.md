# Slice Prompt — PSW-S24-PROD-C8

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production rebootstrap-readiness timing correction.

## Production evidence

After C7 removed stale bridge page-type state, the guarded bounded run still
stopped after a successful row when restart/rebootstrap immediately checked
controller readiness. A sanitized isolated probe reproduced the exact timing:

```text
RESTART_PROBE rebootstrap: OK
RESTART_PROBE sample 0 True False
RESTART_PROBE sample 0.1 True True
```

The authenticated `#tempoSessao` element becomes attached before its three
countdown spans contain parseable values. `bootstrap_legacy_session()` currently
returns after element attachment, while the controller correctly requires a
valid countdown immediately afterward.

## Scope

Maximum four changed files:

1. `apps/ingestion/extractors/legacy_session_bootstrap.py`
2. `tests/unit/test_legacy_session_bootstrap.py`
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
4. this prompt

Do not add arbitrary sleeps, alter queue selection, weaken controller
readiness, change rollout defaults, or touch clinical extraction behavior.

## TDD contract

Add regressions that fail before implementation and prove:

1. bootstrap waits for a browser predicate after `#tempoSessao` attachment;
2. the predicate requires at least three numeric span values;
3. the configured login timeout is propagated to that wait;
4. predicate failure raises only the existing sanitized bootstrap error.

Then extend the authenticated-readiness boundary with a Playwright
`wait_for_function` predicate. The wait must be event-driven and bounded by the
existing login timeout.

## Acceptance

- Focused RED and GREEN evidence exists.
- The bootstrap unit module, official unit suite, and quality gate pass.
- LSP diagnostics are clean for changed Python files.
- Strict OpenSpec and targeted Markdown validation pass.
- Commit and push the four-file slice before production rebuild.
- Re-run a sanitized restart-readiness probe after deploy; sample zero must be
  valid because bootstrap now owns the timing boundary.
- Repeat guarded bounded validation. PSW-S24 remains incomplete unless all four
  selected rows succeed in order with restart/rebootstrap observed.
