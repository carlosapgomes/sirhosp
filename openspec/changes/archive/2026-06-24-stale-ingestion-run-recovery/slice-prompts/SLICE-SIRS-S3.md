# Slice SIRS-S3: Orchestrator integration

## Handoff for zero-context executor

Read `AGENTS.md`, `PROJECT_CONTEXT.md` and all artifacts under:

```text
openspec/changes/stale-ingestion-run-recovery/
```

Confirm SIRS-S1 and SIRS-S2 are complete before coding:

- worker heartbeat exists and is refreshed;
- stale recovery service and `recover_stale_ingestion_runs` command exist;
- recovery service supports dry-run/apply semantics and circuit breaker.

Implement only this slice. Do not change deploy documentation yet except if a
small inline help string is part of the command behavior.

## Goal

Wire the adaptive census orchestrator loop to call the reusable stale recovery
service before it computes queue eligibility, so abandoned runs do not block
future census batches indefinitely.

## Expected behavior

In continuous loop mode:

1. close stale DB connections as before;
2. run stale recovery when enabled;
3. if recovery circuit breaker blocks mutation, log and sleep;
4. compute orchestrator state using updated DB state;
5. start a new cycle only if the normal rules allow it.

Recovery should be configurable but production loop should default to enabled
unless the design or existing command semantics make an explicit flag safer.
Provide a disable flag if recovery is enabled by default.

Dry-run and one-cycle behavior must remain safe. Do not unexpectedly mutate data
from a status-only dry-run.

## Suggested implementation boundaries

Maximum intended changed files: 5.

Likely files:

- `apps/census/orchestration.py`
- `apps/census/management/commands/run_adaptive_census_cycles.py`
- focused tests under `tests/unit/`

If you need more than 5 files, stop and explain why in the report.

## TDD instructions

Follow red → green → refactor.

Start with failing tests proving:

- loop calls stale recovery before `compute_orchestrator_state`;
- recovered state can allow the next cycle check to proceed;
- circuit breaker result prevents a cycle and logs/waits;
- dry-run does not apply stale recovery mutations;
- disabled recovery preserves prior stale-warning behavior.

Mock sleep and command calls. Do not use real sleeping. Keep orchestration logic
DRY by calling the SIRS-S2 service rather than duplicating detection rules.

## Acceptance criteria

- Orchestrator loop invokes stale recovery before eligibility checks.
- Orchestrator does not start a cycle if recovery aborts due to circuit breaker.
- Flags/defaults are explicit and visible in command help.
- Dry-run remains non-mutating.
- Logs are safe: ids, counts, statuses and timestamps only.
- Existing ACO behavior remains covered by focused tests.

## Validation gates

Run focused ACO/recovery tests in the official container. Also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate stale-ingestion-run-recovery --type change --strict
```

If full unit suite is blocked by unrelated pre-existing dependency issues,
document it and include focused passing evidence.

If Markdown changed, run markdown lint for changed files.

## Required report

Create `/tmp/sirhosp-slice-SIRS-S3-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- risks and operational caveats;
- suggested next step.

Do not include patient data, credentials or real clinical text.
