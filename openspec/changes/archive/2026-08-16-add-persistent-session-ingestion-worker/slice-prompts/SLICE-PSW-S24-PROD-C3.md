# Slice Prompt — PSW-S24-PROD-C3

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production-proven login-flow correction.

## Live evidence

The corrected persistent Chromium reached the real login page, but both the
button-first and role-based Enter paths failed. A production probe then copied
the established discharge extractor exactly and succeeded through authenticated
readiness:

```text
EXACT LEGACY LOGIN PATH OK
```

The proven path sets a 180-second Playwright default timeout, locates username
and password by exact placeholder CSS selectors, presses Enter in the password
field, and waits for `#tempoSessao`.

## Scope

Maximum six versioned files:

1. `apps/ingestion/extractors/legacy_session_bootstrap.py`;
2. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
3. `tests/unit/test_legacy_session_bootstrap.py`;
4. `tests/unit/test_persistent_worker_command.py`;
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
6. this slice prompt.

Do not change proxy handling, credentials, readiness evidence, queue behavior,
extraction behavior, Compose services, retry semantics, or rollout status.

## TDD contract

1. Replace speculative button/fallback tests with a failing contract for the
   exact production-proven CSS selectors and password Enter submission.
2. Require `page.set_default_timeout(timeout_ms)` before navigation so fill,
   submission, and waits share the established operational budget.
3. Change the bootstrap default and real command timeout to 180 seconds.
4. Keep `#tempoSessao` as the sole authenticated-readiness boundary.
5. Preserve sanitized errors for timeout configuration, navigation, fill,
   submission, and readiness failures.
6. Add command-level proof that the real bridge receives 180 seconds.

## Acceptance

- RED tests fail because the prior bootstrap omits the page default timeout and
  exact locator/Enter path.
- Focused bootstrap and command tests pass.
- The official container quality gate passes.
- LSP diagnostics are clean for all changed Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C3-report.md` with summary, acceptance
  checklist, changed files, literal before/after snippets, commands/results,
  risks, and next step.
- PSW-S24 remains incomplete until production deploys this commit and the
  standard bridge bootstrap probe prints `Persistent real bootstrap OK`.
