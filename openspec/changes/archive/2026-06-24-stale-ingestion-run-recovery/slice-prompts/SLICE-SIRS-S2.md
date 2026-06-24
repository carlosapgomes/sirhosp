# Slice SIRS-S2: Stale recovery service and command

## Handoff for zero-context executor

Read `AGENTS.md` and `PROJECT_CONTEXT.md` first. Then read all artifacts in:

```text
openspec/changes/stale-ingestion-run-recovery/
```

Confirm Slice SIRS-S1 is complete before coding: `IngestionRun` must have a
nullable heartbeat field and the worker must refresh it while processing.

Implement only this slice. Do not wire recovery into the adaptive orchestrator
loop yet.

## Goal

Create reusable stale-run recovery logic and an operator command. The command
must support dry-run inspection and apply mode. Apply mode marks abandoned
`running` runs as terminal `failed` without requeue and attempts to close drained
batches.

## Expected behavior

A run is abandoned only when all are true:

1. `status = 'running'`;
2. age from `COALESCE(processing_started_at, queued_at, started_at)` exceeds the
   configured limit for its `intent`;
3. `worker_heartbeat_at` is null or older than heartbeat grace.

Initial default limits:

| Intent | Limit |
| --- | ---: |
| `admissions_only` | 20 min |
| `demographics_only` | 20 min |
| `full_sync` | 60 min |
| `census_extraction` | 120 min |
| unknown/empty | 60 min |

Apply mode must:

- set `status='failed'`;
- set `finished_at`;
- set `timed_out=True`;
- set `failure_reason='timeout'`;
- clear `next_retry_at`;
- write a safe error message identifying stale recovery;
- not requeue;
- not increment attempts;
- not overwrite a run that became terminal in a race.

## Suggested implementation boundaries

Maximum intended changed files: 7.

Likely files:

- new recovery module, for example `apps/ingestion/stale_recovery.py`;
- new command `apps/ingestion/management/commands/recover_stale_ingestion_runs.py`;
- optional small batch helper module if needed for DRY batch closure;
- `apps/ingestion/management/commands/process_ingestion_runs.py` only if moving
  existing batch closure to the shared helper;
- focused tests under `tests/unit/`.

If you need more than 7 files, stop and explain why in the report.

## TDD instructions

Follow red → green → refactor.

Start with tests for:

- candidate detection by age and heartbeat;
- per-intent limits and default limit;
- dry-run without mutation;
- apply mode terminal failure without requeue;
- batch closes when no queued/running runs remain;
- circuit breaker aborts with no mutation when candidate count exceeds limit.

Then implement the smallest service and command to satisfy tests. Keep the
service reusable by the orchestrator in the next slice. Avoid implementing
orchestrator integration now.

## Acceptance criteria

- `recover_stale_ingestion_runs --dry-run` reports candidates safely.
- `recover_stale_ingestion_runs --apply` marks only eligible running candidates.
- Abandoned runs are failed terminally and never requeued automatically.
- Batch closure after recovery matches existing worker semantics.
- Circuit breaker prevents mass mutation.
- Output/logs contain only safe operational identifiers and counts.

## Validation gates

Run focused tests in the official container. Also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate stale-ingestion-run-recovery --type change --strict
```

If full unit suite is blocked by unrelated pre-existing dependency issues,
document the evidence and focused passing tests.

If Markdown changed, run markdown lint for changed files.

## Required report

Create `/tmp/sirhosp-slice-SIRS-S2-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- risks, especially false-positive stale marking;
- pending items and next step.

Do not include patient data, credentials or real clinical text.
