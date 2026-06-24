# SLICE ACO-S3 - Continuous loop behavior

## Handoff for context-zero executor

You are implementing only Slice ACO-S3 of the OpenSpec change
`adaptive-census-orchestrator` in the SIRHOSP Django project.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/adaptive-census-orchestrator/proposal.md`
- `openspec/changes/adaptive-census-orchestrator/design.md`
- `openspec/changes/adaptive-census-orchestrator/tasks.md`
- `openspec/changes/adaptive-census-orchestrator/specs/adaptive-census-orchestration/spec.md`
- `openspec/changes/adaptive-census-orchestrator/specs/ingestion-run-observability/spec.md`
- Files changed by Slices ACO-S1 and ACO-S2

Start from a clean working tree. If ACO-S1 or ACO-S2 is not implemented, stop.

## Objective

Add continuous loop operation to the adaptive census orchestrator so it can run
as a long-lived service. The loop waits while blocked, respects cooldown,
applies backoff after failures and exits gracefully on shutdown signals.

## Expected behavior

Implement and test:

1. `--loop` repeatedly checks the S1 decision state.
2. While blocked by active queue, open batch or cooldown, it logs a safe reason
   and sleeps `--sleep-seconds`.
3. When eligible, it executes the S2 single-cycle path.
4. After cycle failure, it sleeps `--failure-backoff-minutes` before retrying.
5. `--sleep-seconds`, `--min-interval-minutes`,
   `--failure-backoff-minutes` and `--stale-running-minutes` are configurable.
6. SIGTERM and SIGINT cause graceful shutdown at a sleep or cycle boundary.
7. Loop tests mock sleep and command calls; no test should wait in real time.

## Suggested files

Prefer no more than 4 changed files.

Likely files:

- `apps/census/orchestration.py` or the existing orchestration service module
- `apps/census/management/commands/run_adaptive_census_cycles.py`
- `tests/unit/test_adaptive_census_orchestrator.py`
- `openspec/changes/adaptive-census-orchestrator/tasks.md` only to mark S3

Do not modify deploy files in this slice.

## Engineering constraints

- Use TDD: write failing loop/backoff/signal tests before implementation.
- Clean code: isolate one loop iteration where possible so tests stay simple.
- DRY: reuse S2 single-cycle function; do not copy the extraction sequence.
- YAGNI: no daemon framework, no UI, no persistent orchestrator state.
- Keep logs safe and compact: aggregate counts, run ids and timestamps only.
- Ensure database connections are kept healthy in long-running mode, following
  the pattern already used by `process_ingestion_runs` where appropriate.

## Acceptance checklist

- Loop mode does not busy-spin.
- Failure backoff is honored and tested without real waiting.
- Shutdown handling is graceful and does not leave partial mutation outside the
  existing single-cycle behavior.
- The command remains usable in dry-run and single-cycle modes.
- No Celery, Redis, migrations or persistent orchestrator tables are added.

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

Create `/tmp/sirhosp-slice-ACO-S3-report.md` with:

- summary of loop/backoff/shutdown behavior;
- proof of TDD red/green/refactor sequence;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- confirmation that tests mock sleep and avoid real long waits;
- risks, pending work and next suggested step.

Stop after the report. Do not implement S4 in this slice.
