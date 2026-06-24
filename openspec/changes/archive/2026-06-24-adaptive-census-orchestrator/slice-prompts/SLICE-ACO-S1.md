# SLICE ACO-S1 - Operational state and dry-run

## Handoff for context-zero executor

You are implementing only Slice ACO-S1 of the OpenSpec change
`adaptive-census-orchestrator` in the SIRHOSP Django project.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/adaptive-census-orchestrator/proposal.md`
- `openspec/changes/adaptive-census-orchestrator/design.md`
- `openspec/changes/adaptive-census-orchestrator/tasks.md`
- `openspec/changes/adaptive-census-orchestrator/specs/adaptive-census-orchestration/spec.md`
- `openspec/changes/adaptive-census-orchestrator/specs/ingestion-run-observability/spec.md`
- `apps/ingestion/models.py`
- `apps/census/management/commands/process_census_snapshot.py`
- `apps/ingestion/management/commands/process_ingestion_runs.py`

Start from a clean working tree. If unrelated files are modified, stop and ask
for guidance.

## Objective

Deliver a vertical, read-only first slice: the system can evaluate whether an
adaptive census cycle would be allowed and expose that decision through a
non-mutating CLI dry-run.

This slice must not execute `extract_census` or `process_census_snapshot`.

## Expected behavior

Implement and test:

1. Queue is eligible when there are no `IngestionRun` rows with status
   `queued` or `running` and no open `CensusExecutionBatch`.
2. Queue is blocked when active runs exist; output includes aggregate counts.
3. Queue is blocked when an open batch exists.
4. Cooldown blocks a new cycle when the latest successful
   `census_extraction` run is newer than `--min-interval-minutes`.
5. Stale `running` runs are detected when older than
   `--stale-running-minutes` and are reported without mutation.
6. `python manage.py run_adaptive_census_cycles --dry-run` prints a safe
   operational decision and creates no database rows.

## Suggested files

Prefer no more than 4 changed files.

Likely files:

- `apps/census/orchestration.py` or similar small service module
- `apps/census/management/commands/run_adaptive_census_cycles.py`
- `tests/unit/test_adaptive_census_orchestrator.py`
- `openspec/changes/adaptive-census-orchestrator/tasks.md` only to mark S1
  tasks if your workflow requires it

Do not modify deploy files in this slice.

## Engineering constraints

- Use TDD: write a failing test first, then implement the minimum code.
- Keep code clean, small and explicit.
- Follow DRY, but do not over-abstract.
- Apply YAGNI: implement only S1 behavior, no real extraction and no loop.
- Keep output credential-safe and patient-data-safe.
- Do not add Celery, Redis, migrations, new persistent models or external
  dependencies.
- Do not change existing worker behavior.

## Acceptance checklist

- `--dry-run` is non-mutating.
- Tests cover eligible, blocked by active run, blocked by open batch, cooldown
  and stale-running states.
- Output contains only aggregate counts, run ids or timestamps; no patient names
  or clinical text.
- Existing manual commands still work unchanged.
- File changes stay within the suggested scope or the report explains why not.

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

Create `/tmp/sirhosp-slice-ACO-S1-report.md` with:

- summary of the slice;
- proof of TDD red/green/refactor sequence;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- confirmation that dry-run creates no rows and runs no extraction;
- risks, pending work and next suggested step.

Stop after the report. Do not implement S2 in this slice.
