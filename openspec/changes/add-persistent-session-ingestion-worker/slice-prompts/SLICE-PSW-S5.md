# SLICE PSW-S5: Full-Sync Evolution Extraction Through Persistent Session

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S5 for OpenSpec change
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
5. All specs under
   `openspec/changes/add-persistent-session-ingestion-worker/specs/`
6. The code and reports from PSW-S1 through PSW-S4

Implement full-sync evolution extraction through the persistent session path.
This slice should make the persistent worker useful for the same main ingestion
workload as the current worker, while preserving the admissions-only behavior
from PSW-S4.

## PSW-S4 Verification Notes to Address

The PSW-S4 verifier confirmed the command now reuses one shared adapter across
claims and performs teardown, but documented one formal blocker before any
realistic rollout:

- The real Playwright `SessionHandle` and `ExclusiveBrowserProfile` wiring do
  not exist yet. The command is therefore still an operational skeleton until a
  real handle can open legacy tabs, wait with propagated timeouts, expose the
  snapshot/evolution containers expected by the adapter, and close/recover the
  shared session safely.

PSW-S5 must address this blocker before or together with full-sync extraction.
If implementing the real handle plus full-sync exceeds the slice limits, stop
and report a blocker proposing a dedicated wiring slice before full-sync.

## Current Code to Inspect

Inspect these files before coding:

- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `apps/ingestion/gap_planner.py`
- `apps/ingestion/extractors/playwright_extractor.py`
- `apps/ingestion/extractors/ports.py`
- persistent session/controller/adapter modules from PSW-S1 through PSW-S4
- tests for full-sync, gap planning, event persistence, and stage metrics
- tests/reports added in PSW-S4, especially timeout propagation, cleanup, and
  shared adapter lifecycle tests

## Scope

Target maximum changed files: 10.

Expected files:

- real Playwright `SessionHandle` and exclusive profile wiring, if it can fit
  in this slice without broad refactor;
- persistent adapter updates for `extract_evolutions(...)`;
- persistent worker command updates for full-sync intent;
- tests for full-sync success/failure with fake persistent source responses;
- tests for the real handle boundary using mocks/fakes, not real legacy access;
- small shared helper updates only if already introduced in previous slices.

Avoid broad refactors of the current worker. If substantial shared processor
extraction becomes necessary, stop and report a blocker.

Also stop and report a blocker if a production-usable real handle cannot be
implemented within this slice's file limit. Do not leave the persistent worker
looking rollout-ready while it still relies only on fake/session skeletons.

## Development Method

Use TDD strictly:

1. Write failing tests for the real handle boundary or explicitly stop with a
   blocker if it must be split out.
2. Write failing tests for full-sync persistent processing.
3. Implement the smallest real handle, extraction, and command wiring.
4. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- reuse existing gap planning and persistence services;
- keep Playwright/session details inside the persistent adapter/controller;
- keep the current worker untouched;
- do not add artificial keepalive unless required by tests/specs;
- do not change existing current-worker behavior.

## Required Behavior

First, ensure the persistent path has a real handle boundary that can:

- create an exclusive per-process browser profile;
- open a configured legacy tab and wait until it is fully rendered;
- propagate timeout values to Playwright waits/actions;
- supply the admission snapshot and evolution data containers expected by the
  adapter;
- close non-root tabs as cleanup only;
- expose recovery/restart hooks for the command's shared adapter lifecycle.

Then implement persistent adapter support for:

```python
extract_evolutions(
    *,
    patient_record: str,
    start_date: str,
    end_date: str,
    timeout: int = ...,
) -> list[dict]
```

Wire persistent full-sync processing so it preserves:

- admissions-first capture;
- cache-first gap planning;
- skipped extraction when coverage is complete;
- extraction over each planned gap window with timeout propagation;
- event persistence counters;
- stage metrics for admissions, gap planning, evolution extraction, and
  ingestion persistence;
- existing failure taxonomy and retry semantics;
- job-tab opening as the only proactive counter-reset signal;
- tab cleanup after success and recoverable errors, without treating close as
  renewal evidence;
- relogin/restart before next claim when cleanup is unsafe.

## Acceptance Criteria

- Tests prove the real handle boundary propagates timeout, uses an exclusive
  profile path, and does not require real legacy access.
- Tests prove successful full-sync with synthetic evolutions persists expected
  counters and stages.
- Tests prove full coverage skips source extraction and succeeds.
- Tests prove evolution extraction failure preserves admissions and fails/retries
  consistently with current semantics.
- Tests prove session checkpoints surround long extraction actions.
- Tests prove opening a job tab, not closing it, is the proactive renewal
  signal.
- Tests prove the persistent command is not documented or configured as
  rollout-ready if the real handle remains incomplete.
- Tests prove unsafe tab cleanup prevents claiming another run until recovery.
- Current worker behavior remains unchanged.

## Validation Commands

Run at minimum:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If container validation is unavailable, run the closest diagnostic command and
explain the limitation in the report. Host-only tests are diagnostic, not the
official gate.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S5-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
