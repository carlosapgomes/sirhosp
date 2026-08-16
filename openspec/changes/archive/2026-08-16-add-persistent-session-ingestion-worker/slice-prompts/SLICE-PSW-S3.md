# SLICE PSW-S3: Persistent Extraction Adapter for Admissions-Only Path

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S3 for OpenSpec change
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
6. `openspec/changes/add-persistent-session-ingestion-worker/specs/ingestion-run-observability/spec.md`
7. The code and reports from PSW-S1 and PSW-S2

Implement only the persistent extraction adapter path needed for admission
snapshot capture. Do not create the new worker command and do not implement full
evolution extraction in this slice.

## Current Code to Inspect

Inspect these files before coding:

- `apps/ingestion/extractors/playwright_extractor.py`
- `apps/ingestion/extractors/admission_snapshot_parser.py`
- `apps/ingestion/extractors/errors.py`
- `apps/ingestion/management/commands/process_ingestion_runs.py`

The existing worker uses `get_admission_snapshot(...)` during admissions-only
and full-sync flows. This slice should provide a persistent adapter with a
compatible admission snapshot method.

## Scope

Target maximum changed files: 6.

Expected files:

- one persistent extraction adapter module;
- unit tests for adapter behavior with fake session/page responses;
- minimal updates to shared ports/types only if necessary;
- optional small fixture strings with synthetic non-patient data.

Avoid touching the current worker command. If you believe a change to
`process_ingestion_runs.py` is required, stop and report a blocker with the
smallest proposed refactor.

## Development Method

Use TDD strictly:

1. Write failing adapter tests first.
2. Implement the smallest adapter admission path.
3. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- reuse existing parser/normalization behavior where safe;
- keep source-system browser mechanics behind the session controller;
- do not duplicate large blocks from existing scripts unless unavoidable;
- do not implement full-sync evolution extraction yet.

## Required Behavior

Implement a persistent adapter exposing:

```python
get_admission_snapshot(
    *,
    patient_record: str,
    start_date: str,
    end_date: str,
    timeout: int = ...,
) -> list[dict]
```

The adapter must:

- call session readiness/renewal checkpoints before source-system actions;
- obtain admission snapshot data through the persistent session abstraction;
- parse/normalize data consistently with existing admission snapshot behavior;
- map failures to existing typed extraction exceptions;
- avoid persisting or logging credentials, cookies, screenshots, PDFs, debug
  HTML, or raw patient artifacts.

Use fake source-system responses in tests. Do not require real legacy access.

## Acceptance Criteria

- Tests prove successful admission snapshot extraction through the persistent
  adapter with synthetic data.
- Tests prove session checkpoints are called before/after source actions.
- Tests prove renewal/session failures map to existing extraction errors.
- Tests prove no real browser is launched.
- Existing worker command remains untouched.
- No full-sync/evolution extraction behavior is added in this slice.

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

Create `/tmp/sirhosp-slice-PSW-S3-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
