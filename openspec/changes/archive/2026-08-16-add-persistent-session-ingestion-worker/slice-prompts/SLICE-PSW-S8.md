# SLICE PSW-S8: Real Handle Contract and Persistent Full-Sync

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S8 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

## Branch Isolation

This feature MUST continue on branch
`feature/add-persistent-session-ingestion-worker`.

Before coding, verify:

```bash
git branch --show-current
git status --short
```

If not already on that branch, stop when unrelated changes are present. Do not
mix this feature with other OpenSpec changes, unrelated fixes, or opportunistic
refactors. Include the active branch and `git status --short` in the report.

Active OpenSpec change directories are ignored by `.gitignore`. If committing
planning artifacts, force-add this change directory explicitly on the feature
branch.

## Markdown Validation Policy

Do not run global Markdown formatters or linters that rewrite unrelated files.
In particular, do **not** run `./scripts/markdown-format.sh` for this slice.

If you create or modify Markdown files, validate only those files, for example:

```bash
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  deploy/README.md \
  openspec/changes/add-persistent-session-ingestion-worker/slice-prompts/SLICE-PSW-S8.md
```

Do not fix Markdown files outside this change unless explicitly requested.

## Read First

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. All specs under
   `openspec/changes/add-persistent-session-ingestion-worker/specs/`
6. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
7. Reports from PSW-S1 through PSW-S7
8. `apps/ingestion/management/commands/process_ingestion_runs.py`
9. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
10. `apps/ingestion/extractors/persistent_extraction_adapter.py`
11. `apps/ingestion/extractors/playwright_session_handle.py`
12. `automation/source_system/medical_evolution/path2.py`
13. `apps/ingestion/evolution_ingestion.py`
14. `/tmp/sirhosp-slice-PSW-S7-report.md`

## Context

PSW-S5 created a real `PlaywrightSessionHandle` boundary, but it remains
non-rollout-ready because it does not satisfy the adapter's synthetic
snapshot/evolution container contract against the real legacy UI.

PSW-S7 completed the shared persistence extraction in
`apps/ingestion/evolution_ingestion.py`. The current worker delegates to that
service through its preserved `_ingest_evolutions(evolutions, run, patient)`
wrapper. The persistent worker still returns terminal
`full_sync_not_implemented` and must be wired to the shared service here.

This slice resolves the remaining production blocker for functional persistent
full-sync, or stops with a precise blocker if real legacy selectors/flows are
insufficiently known.

## Scope

Target maximum changed files: 12.

Expected files:

- persistent worker command updates for real `_process_full_sync`;
- persistent adapter or handle updates to satisfy the real legacy data contract;
- tests for full-sync success, skipped extraction, extraction failure, cleanup,
  timeout propagation, and shared service usage;
- optional documentation updates only if rollout status changes;
- no broad rewrite of the current worker.

If the real handle contract cannot be implemented safely within 12 files, stop
and report a blocker. Do not fake production readiness.

## Development Method

Use TDD strictly:

1. Add failing tests for the real handle/adapter contract using mocks/fakes, not
   real legacy access.
2. Add failing tests for persistent full-sync command behavior.
3. Implement the smallest handle/adapter and command wiring.
4. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- reuse `ingest_evolutions` from `apps.ingestion.evolution_ingestion`;
- reuse existing gap planning and stage metric semantics;
- keep Playwright details behind the handle/adapter boundary;
- do not reintroduce subprocess-per-job behavior in the persistent worker;
- keep the current worker behavior unchanged.

## Required Behavior

Implement or validate a real persistent source-system contract that can provide
admissions and evolution data without relying on fake-only synthetic containers.
Acceptable approaches:

- update `PlaywrightSessionHandle` to extract real legacy DOM/download results
  and return the JSON payload shape expected by the adapter;
- or update the adapter/handle boundary so the handle returns already-extracted
  normalized data, with tests proving the contract;
- or reuse stable helper functions from `path2.py` against the already-open
  persistent page/context without invoking `path2.py` as a subprocess and
  without launching a fresh browser per job.

Then wire persistent full-sync so it preserves:

- admissions-first capture;
- cache-first gap planning;
- skipped extraction when coverage is complete;
- extraction over each planned gap window;
- shared-service evolution persistence via
  `apps.ingestion.evolution_ingestion.ingest_evolutions`;
- event counters;
- stage metrics for admissions, gap planning, extraction, and persistence;
- existing failure taxonomy and retry semantics;
- tab cleanup after success and recoverable errors;
- recovery/relogin/restart before next claim when cleanup is unsafe;
- opening a job/safe tab as the only proactive counter-reset signal.

If production readiness remains blocked, keep the command guarded and update the
runtime docs to say exactly what remains blocked.

## Acceptance Criteria

- Tests prove persistent full-sync success persists expected counters and stage
  metrics using `apps.ingestion.evolution_ingestion.ingest_evolutions`.
- Tests prove full coverage skips source extraction and succeeds.
- Tests prove evolution extraction failure preserves admissions and fails or
  retries consistently with current semantics.
- Tests prove the real handle/adapter contract no longer depends on fake-only
  synthetic containers, or the slice stops with a documented blocker.
- Tests prove timeouts propagate to source waits/actions.
- Tests prove cleanup and unsafe-cleanup recovery happen before the next claim.
- Tests prove current `process_ingestion_runs` behavior remains unchanged.
- Terminal `full_sync_not_implemented` behavior is removed only after real
  persistent full-sync is implemented; otherwise the slice stops with a blocker.
- Runtime docs are updated if the rollout status changes.
- No real legacy access is required in automated tests.
- No real patient data, credentials, cookies, screenshots, PDFs, or debug HTML
  are added.

## Validation Commands

Run at minimum:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If Markdown files were changed, run `markdownlint-cli2` only on the changed
Markdown files. Do not run global Markdown format/lint commands for this slice.

If container validation is unavailable, run the closest diagnostic command and
explain the limitation in the report. Host-only tests are diagnostic, not the
official gate.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S8-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- Markdown files validated, if any;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
