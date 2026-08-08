# Slice Prompt — PSW-S24-PROD-C7

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production restart-readiness correction.

## Production evidence

After C6 corrected the concrete Playwright restart lifecycle, the guarded
four-row bounded run completed admissions and demographics, restarted, and
then stopped before claiming `full_sync` with:

> Persistent session readiness marker missing after rebootstrap (sanitized)
>
> Persistent session restart failed during bounded validation; stopping the
> bounded sequence.

A separate fresh-session probe proved bootstrap, connectivity, page HTML, and
countdown parsing all succeed. The bridge retained its previous admissions URL
after restart, however, so `get_page_html()` incorrectly transformed the fresh
post-login page as an admissions page before the controller readiness check.

## Scope

Maximum four changed files:

1. `apps/ingestion/extractors/real_handle_bridge.py`
2. `tests/unit/test_real_handle_bridge.py`
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
4. this prompt

Do not change rollout defaults, production services, models, migrations,
command selection, or clinical extraction behavior.

## TDD contract

Add an observable regression that:

1. selects an admissions page through the bridge;
2. proves that page-type transformation is active;
3. restarts the wrapped browser;
4. proves fresh raw page HTML is no longer transformed using the stale page
   type.

The test must fail before production code changes. Then clear page-type state
only after the wrapped restart succeeds.

## Acceptance

- The focused regression passes.
- The relevant unit suite and official quality gate pass.
- LSP diagnostics are clean for changed Python files.
- Strict OpenSpec and targeted Markdown validation pass.
- Commit and push the four-file slice before production rebuild.
- Repeat the same sanitized four-row bounded validation. PSW-S24 remains
  incomplete unless all four selected rows succeed in order and the observed
  restart/rebootstrap happens before the later claim.
