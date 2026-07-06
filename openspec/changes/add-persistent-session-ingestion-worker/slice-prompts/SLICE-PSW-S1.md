# SLICE PSW-S1: Session DOM Policy Primitives

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S1 for OpenSpec change
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
6. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`

Implement only the pure DOM policy primitives for the future persistent-session
worker. Do not implement Playwright/browser control and do not create the worker
command in this slice.

## Legacy HTML Facts

Session counter example:

```html
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
```

Renewal popup visible example:

```html
<div id="casca_renovasession" aria-hidden="false" style="display: block;">
  <button class="ui-confirmdialog-yes" type="submit">
    <span class="ui-button-text ui-c">Renovar</span>
  </button>
</div>
```

Root-only legacy tab has classes:

```text
tabs-first tabs-last tabs-selected
```

Opening and rendering a new legacy tab consistently resets the session counter.
Closing a tab does not consistently reset the counter. Therefore tab close is
cleanup only and must never be modeled as session renewal.

Operational job tab cleanup must close only the last tab when it is not also
`tabs-first`.

## Scope

Target maximum changed files: 4.

Expected files:

- one new small module under `apps/ingestion/` or
  `automation/source_system/` for pure policies;
- one new unit test file under `tests/unit/`;
- optional `__init__.py` only if required.

Do not touch:

- `apps/ingestion/management/commands/process_ingestion_runs.py`;
- Docker/Compose/systemd files;
- production docs except the required temporary report.

If you need more than 4 files, stop and report a blocker.

## Development Method

Use TDD strictly:

1. Write failing unit tests first.
2. Implement the smallest pure functions/value objects needed.
3. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- keep functions small and named by intent;
- centralize selector constants;
- avoid Playwright imports in this slice;
- avoid speculative abstractions not used by the tests.

## Required Behavior

Implement tested support for:

- parsing the `#tempoSessao` representation into remaining seconds;
- returning an unknown/invalid result for malformed or missing counters;
- deciding whether the renewal popup is visible;
- identifying the semantic popup button selector or target;
- deciding tab cleanup action:
  - preserve single root tab;
  - close last non-root tab;
  - return recovery-required for unsafe/ambiguous states;
  - never classify a close action as session renewal.

Use synthetic HTML only. Do not use real patient data.

## Acceptance Criteria

- Unit tests cover valid counter, malformed counter, visible popup, hidden
  popup, root-only tab, two-tab close target, unsafe tab state, and the rule
  that tab close is not renewal evidence.
- Pure policy code has no browser side effects and no Playwright dependency.
- Selectors are centralized and named.
- Existing worker behavior is untouched.
- No credentials, cookies, screenshots, PDFs, debug HTML, or real patient data
  are added.

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

Create `/tmp/sirhosp-slice-PSW-S1-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
