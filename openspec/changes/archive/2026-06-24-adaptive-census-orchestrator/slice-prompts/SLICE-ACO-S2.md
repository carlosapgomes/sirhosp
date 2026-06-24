# SLICE ACO-S2 - One safe real cycle

## Handoff for context-zero executor

You are implementing only Slice ACO-S2 of the OpenSpec change
`adaptive-census-orchestrator` in the SIRHOSP Django project.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/adaptive-census-orchestrator/proposal.md`
- `openspec/changes/adaptive-census-orchestrator/design.md`
- `openspec/changes/adaptive-census-orchestrator/tasks.md`
- `openspec/changes/adaptive-census-orchestrator/specs/adaptive-census-orchestration/spec.md`
- `openspec/changes/adaptive-census-orchestrator/specs/census-snapshot-processing/spec.md`
- `apps/census/management/commands/extract_census.py`
- `apps/census/management/commands/process_census_snapshot.py`
- `apps/census/services.py`
- Files changed by Slice ACO-S1

Start from a clean working tree. If ACO-S1 is not implemented, stop.

## Objective

Add one real adaptive cycle. When the system is eligible, the command runs
`extract_census`, identifies the exact census extraction run created by that
command, and runs `process_census_snapshot --run-id=<id>`.

This slice should still not implement continuous loop behavior.

## Expected behavior

Implement and test:

1. `--once` or default single-run mode skips safely when S1 says the queue is
   blocked.
2. The command acquires a PostgreSQL advisory lock before starting the cycle.
3. If the lock is already held, the command does not run extraction.
4. A successful eligible cycle calls `extract_census` once.
5. After extraction, the command identifies exactly one new successful
   `IngestionRun(intent="census_extraction")` created during the cycle.
6. The command calls `process_census_snapshot` with that run id.
7. If extraction fails, snapshot processing is not called and the command
   returns a failure outcome.
8. If zero or multiple new census extraction runs are detected, snapshot
   processing is not called and the command fails safe.

## Suggested files

Prefer no more than 5 changed files.

Likely files:

- `apps/census/orchestration.py` or the S1 service module
- `apps/census/management/commands/run_adaptive_census_cycles.py`
- `tests/unit/test_adaptive_census_orchestrator.py`
- Optionally one integration test file if command behavior needs DB-level proof
- `openspec/changes/adaptive-census-orchestrator/tasks.md` only to mark S2

Do not modify deploy files in this slice.

## Engineering constraints

- Use TDD: add failing tests for successful cycle, extraction failure, lock
  rejection and ambiguous run detection before implementation.
- Clean code: keep orchestration decisions in a small service/helper and keep
  the management command thin.
- DRY: reuse S1 decision logic; do not duplicate queue checks.
- YAGNI: no loop, no service unit, no UI, no persistent orchestrator model.
- Do not refactor `extract_census` unless a focused test proves it is required.
- Do not print patient names, clinical text or credentials.

## Acceptance checklist

- Single-cycle command never enqueues a batch while active queue work exists.
- `process_census_snapshot` is called with explicit `run_id` from the current
  extraction.
- Lock behavior is fail-safe and tested.
- Extraction failure and ambiguous run detection leave no new census batch from
  this orchestrated cycle.
- Existing manual commands remain compatible.

## Validation commands

Run focused diagnostics first, then official gates where relevant:

```bash
uv run pytest -q tests/unit/test_adaptive_census_orchestrator.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
openspec validate adaptive-census-orchestrator --type change --strict
```

Host-only `uv run pytest` is diagnostic only. Official evidence comes from the
container scripts.

## Required report

Create `/tmp/sirhosp-slice-ACO-S2-report.md` with:

- summary of the single-cycle implementation;
- proof of TDD red/green/refactor sequence;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- confirmation that no loop, timer or external queue was added;
- risks, pending work and next suggested step.

Stop after the report. Do not implement S3 in this slice.
