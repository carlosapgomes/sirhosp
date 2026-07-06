# SLICE PSW-S7: Shared Evolution Ingestion Service

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S7 for OpenSpec change
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
  openspec/changes/add-persistent-session-ingestion-worker/slice-prompts/SLICE-PSW-S7.md
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
7. Reports from PSW-S1 through PSW-S6, especially PSW-S5 blocker 5.8
8. `apps/ingestion/management/commands/process_ingestion_runs.py`
9. `apps/ingestion/services.py`
10. Existing tests covering full-sync, event persistence, admission resolution,
    and current worker behavior

## Context

PSW-S5 intentionally left full-sync persistence blocked. The current legacy
worker has `_ingest_evolutions(...)` inside its management command. The
persistent worker cannot safely implement full-sync while that persistence logic
is trapped in the current command.

This slice extracts that evolution persistence behavior into a shared service
that both workers can call. It must preserve current worker behavior.

## Scope

Target maximum changed files: 8.

Expected files:

- one new shared service module, for example
  `apps/ingestion/evolution_ingestion.py`;
- unit tests for the shared service;
- minimal update to `process_ingestion_runs.py` so the current worker delegates
  to the service while preserving its public behavior;
- optional update to persistent worker imports/types, but do not implement
  persistent full-sync in this slice.

Do not touch deployment docs or Compose/systemd files in this slice.

If extracting the service requires more than 8 files or a broad rewrite of the
current worker, stop and report a blocker.

## Development Method

Use TDD strictly:

1. Add failing characterization tests for the shared service behavior.
2. Implement the smallest service extraction.
3. Update the current worker to delegate to the service.
4. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- no new queue, Celery, Redis, or daemon;
- no business logic in the new management command;
- preserve current persistence semantics exactly;
- do not implement persistent full-sync yet.

## Required Behavior

Create a shared service equivalent to the current `_ingest_evolutions(...)`
method. It should expose a clear API, for example:

```python
ingest_evolutions(
    evolutions: list[dict],
    run: IngestionRun,
    patient: Patient,
) -> tuple[int, int, int]
```

The service must preserve:

- patient upsert behavior;
- deterministic admission resolution by `admission_key` and `happened_at`;
- fallback admission upsert behavior when resolution fails;
- `_persist_event(...)` behavior;
- created/skipped/revised counters;
- transaction boundaries equivalent to current behavior;
- timezone handling for naive `happened_at` values.

The current worker's `_ingest_evolutions(...)` may remain as a thin delegating
wrapper or be replaced by direct service calls if tests prove behavior is
unchanged.

## Acceptance Criteria

- Tests prove the shared service returns created/skipped/revised counters.
- Tests prove admission resolution and fallback behavior remain equivalent to
  the current worker implementation.
- Tests prove the current `process_ingestion_runs` full-sync path still calls
  equivalent persistence behavior and existing tests pass.
- Persistent worker still does not claim full-sync as implemented in this slice.
- No unrelated files are changed.
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

Create `/tmp/sirhosp-slice-PSW-S7-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- Markdown files validated, if any;
- risks, pending items, and suggested next step.

Stop after this slice.
