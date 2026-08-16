# SLICE PSW-S2: Persistent Legacy Session Controller

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S2 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

## Branch Isolation

This feature MUST be implemented only on branch
`feature/add-persistent-session-ingestion-worker`.

Before coding, verify:

```bash
git branch --show-current
git status --short
```

If not already on that branch, stop when unrelated changes are present. If the
tree is clean or contains only this change's planning artifacts, switch or
create the branch:

```bash
git switch feature/add-persistent-session-ingestion-worker || \
  git switch -c feature/add-persistent-session-ingestion-worker
```

Do not mix this feature with other OpenSpec changes, unrelated fixes, or
opportunistic refactors. Include the active branch and `git status --short` in
the required report.

Active OpenSpec change directories are ignored by `.gitignore` here. If the
branch must carry planning artifacts, force-add this change directory
explicitly on the feature branch.

Read first:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. `openspec/changes/add-persistent-session-ingestion-worker/specs/persistent-session-ingestion-worker/spec.md`
6. `openspec/changes/add-persistent-session-ingestion-worker/slice-prompts/SLICE-PSW-S1.md`
7. The code and tests produced by PSW-S1

Implement only the persistent legacy session controller using faked
Playwright-like objects in tests. Do not create the worker command and do not
implement real extraction flows in this slice.

## Scope

Target maximum changed files: 5.

Expected files:

- the policy module from PSW-S1;
- one new session controller module;
- one new or expanded unit test file using fakes;
- optional package `__init__.py` only if required.

Do not touch:

- `apps/ingestion/management/commands/process_ingestion_runs.py`;
- deployment files;
- real legacy credentials/configuration;
- production docs except the required temporary report.

If you need more than 5 files, stop and report a blocker.

## Development Method

Use TDD strictly:

1. Write failing tests using fake page/browser/context objects.
2. Implement the smallest controller behavior needed.
3. Refactor to remove duplication after tests pass.

Follow clean code, DRY, and YAGNI:

- keep browser/session lifecycle separate from queue/run lifecycle;
- centralize selectors and thresholds;
- avoid adding a background popup watcher;
- implement renewal by opening a configured safe tab in fakes only;
- treat tab close as cleanup only, never as renewal evidence.

## Required Behavior

Implement tested support for a controller or service with methods equivalent to:

- `ensure_ready()`;
- `renew_if_needed()`;
- `open_safe_renewal_tab()` or equivalent configured renewal action;
- `close_job_tab_if_present()`;
- `mark_job_processed()` or equivalent job-count tracking;
- `restart_required()` or equivalent health decision.

The controller must:

- use PSW-S1 policy decisions;
- open a configured safe tab when proactive renewal is needed;
- verify renewal by observing the session counter after tab render;
- click the semantic popup target only when the popup is visible, as a
  defensive unblock path rather than counter-reset evidence;
- preserve root-only tab state;
- close only the last non-root tab as cleanup;
- never count tab close as session renewal;
- count consecutive renewal/login/tab-cleanup failures;
- support conservative configurable thresholds:
  - max jobs per browser session;
  - max browser lifetime;
  - max consecutive renewal/login/tab-cleanup failures;
- use an exclusive per-process profile/temp path abstraction;
- avoid destructive profile cleanup while browser is running.

## Acceptance Criteria

- Tests prove renewal by opening a configured safe tab through fakes.
- Tests prove popup click and wait behavior through fakes, without treating
  popup dismissal alone as counter-reset evidence.
- Tests prove root tab is preserved and last non-root tab is closed only as
  cleanup.
- Tests prove repeated failures trigger restart-required state.
- Tests prove max jobs/lifetime trigger restart at a safe point.
- No real Playwright browser is launched by unit tests.
- Existing worker behavior is untouched.
- No sensitive data or real patient data is added.

## Validation Commands

Run at minimum:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If container validation is unavailable, run the closest diagnostic command and
explain the limitation in the report. Host-only tests are diagnostic, not the
official gate.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S2-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
