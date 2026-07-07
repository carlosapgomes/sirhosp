# SLICE PSW-S10: Safe Real-Legacy Bootstrap Smoke

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S10 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

Continue on branch:

```bash
git branch --show-current
# expected: feature/add-persistent-session-ingestion-worker
```

Before coding, run:

```bash
git status --short
```

If unrelated changes are present, stop and report. Do not mix this slice with
other features, archived OpenSpec changes, or opportunistic refactors.

## Slice Goal

Make the persistent worker safe and practical for a **single controlled manual
smoke test against the real legacy system**, focused on session bootstrap and
admissions extraction only.

This slice does **not** make production rollout ready. It prepares a guarded
manual path so an operator can run one known queued run with `--real-handle`
without consuming the whole production queue.

## Why This Slice Exists

PSW-S9 implemented `RealHandleBridge`, but it only proved the bridge with
representative HTML fakes. The real handle still needs production-like
bootstrap mechanics:

- open the configured legacy base URL;
- authenticate using source-system credentials;
- wait for an authenticated page with `#tempoSessao`;
- use real URL templates instead of local placeholder paths;
- process at most one explicitly selected run during manual validation.

Keep this slice narrow. Do not implement the real evolution PDF flow here;
that belongs to PSW-S11.

## Read First

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
6. `openspec/changes/add-persistent-session-ingestion-worker/specs/`
7. `/tmp/sirhosp-slice-PSW-S9-report.md`
8. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
9. `apps/ingestion/extractors/playwright_session_handle.py`
10. `apps/ingestion/extractors/real_handle_bridge.py`
11. `apps/ingestion/extractors/persistent_extraction_adapter.py`
12. `apps/ingestion/extractors/session_controller.py`
13. `apps/ingestion/historical_extraction.py`
14. Existing source-system login examples under `automation/source_system/`
15. Tests for persistent worker command and Playwright/session handle

## Development Method

Use strict TDD:

1. Add failing tests for the guarded manual-run controls and real bootstrap
   behavior with mocks/fakes only.
2. Implement the smallest code needed to pass those tests.
3. Refactor only after green tests.

Apply clean code, DRY, and YAGNI:

- reuse existing credential resolution where possible;
- do not duplicate large automation scripts;
- do not introduce Celery, Redis, new services, or subprocesses;
- do not implement PDF evolution extraction in this slice;
- do not log passwords, cookies, debug HTML, screenshots, or patient data.

## Scope and File Budget

Target maximum changed files: 8.

Expected files:

- persistent worker command;
- `PlaywrightSessionHandle` or a focused bootstrap helper;
- unit tests for command guards and bootstrap;
- rollout docs only if needed for manual instructions.

If the implementation needs more than 8 files, stop and explain the proposed
split in the report.

## Required Behavior

### 1. Safe single-run manual validation controls

Add a guarded way to process exactly one selected queued run, suitable for a
manual real-legacy smoke test.

Preferred interface:

```bash
uv run python manage.py process_ingestion_runs_persistent_session \
  --real-handle \
  --run-id <INGESTION_RUN_ID> \
  --max-runs 1
```

Required semantics:

- `--run-id` claims only that run if it is eligible and queued;
- `--max-runs 1` stops after one processed run;
- with `--real-handle`, manual validation must not accidentally drain the
  general queue;
- the default stub path keeps current behavior unless guarded real-handle
  rules intentionally require safer options;
- failures before claim must not mutate queued runs.

### 2. Real legacy session bootstrap

When `--real-handle` is used, bootstrap the browser session before claims:

- resolve `SOURCE_SYSTEM_URL`, `SOURCE_SYSTEM_USERNAME`, and
  `SOURCE_SYSTEM_PASSWORD` through the existing project mechanism;
- navigate to the source URL once at startup;
- fill the username and password fields using selectors consistent with
  existing automation scripts;
- submit the login form;
- wait for authenticated readiness, preferably `#tempoSessao`;
- return a sanitized error if credentials or selectors are missing.

The bootstrap must not print or persist credentials. The tests must prove that
password values do not appear in exception strings or logs.

### 3. Real URL template configuration

For the real handle path, avoid fake local URLs such as
`/admissions/{patient_record}` unless an explicit base URL is configured by
Playwright.

Add a small, testable configuration path for real URL templates, for example
environment variables or Django settings:

- admissions URL template;
- evolutions URL template, even if PSW-S11 will use it later;
- safe renewal URL.

If these are missing during `--real-handle`, fail safely before claiming runs
with an actionable, sanitized message.

### 4. Preserve persistent-session invariants

Do not change these behaviors:

- one browser/session is reused across jobs;
- opening/rendering a tab is the renewal signal;
- closing a tab is cleanup only;
- exclusive browser profile behavior remains intact;
- current `process_ingestion_runs` worker is unchanged;
- automated tests do not access the real legacy system.

## Acceptance Criteria

- Tests prove `--run-id` claims only the selected queued run.
- Tests prove `--max-runs 1` stops after one processed run.
- Tests prove `--real-handle` manual mode cannot drain arbitrary queued runs.
- Tests prove bootstrap calls navigate, fill credentials, submit, and wait for
  `#tempoSessao` using mocked Playwright objects.
- Tests prove missing credentials or missing real URL templates fail before
  any run is claimed.
- Tests prove no password or cookie value appears in errors/log output.
- Tests prove timeout values still reach navigation/wait calls.
- Tests prove default stub behavior remains backward compatible where intended.
- Rollout docs, if modified, clearly say this is manual smoke only and not
  production rollout.

## Validation Commands

Run at minimum:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
```

If Markdown files changed, validate only those files with `markdownlint-cli2`.
Do not run global Markdown formatters or linters that rewrite unrelated files.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S10-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- branch and `git status --short`;
- manual smoke command example with placeholders only;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
