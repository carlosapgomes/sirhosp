# Slice SIRS-S1: Worker heartbeat persistence

## Handoff for zero-context executor

Read `AGENTS.md` and `PROJECT_CONTEXT.md` first. Then read the OpenSpec change:

- `openspec/changes/stale-ingestion-run-recovery/proposal.md`
- `openspec/changes/stale-ingestion-run-recovery/design.md`
- `openspec/changes/stale-ingestion-run-recovery/tasks.md`
- `openspec/changes/stale-ingestion-run-recovery/specs/ingestion-run-observability/spec.md`
- `openspec/changes/stale-ingestion-run-recovery/specs/ingestion-run-stale-recovery/spec.md`

Implement only this slice. Do not implement stale recovery command or
orchestrator integration yet.

## Goal

Persist a worker heartbeat on `IngestionRun` while
`process_ingestion_runs` processes a run, so another process can later decide
whether a `running` run is alive without checking Docker/PID.

## Expected behavior

- Add nullable `worker_heartbeat_at` to `IngestionRun`.
- When a queued run is claimed/started, set `worker_heartbeat_at` to now.
- While the run is processing, refresh `worker_heartbeat_at` periodically.
- Stop refreshing when processing exits or the run reaches terminal state.
- Do not expose patient names, clinical text or credentials in logs.
- Preserve all existing retry, attempt and batch behavior.

## Suggested implementation boundaries

Maximum intended changed files: 6.

Likely files:

- `apps/ingestion/models.py`
- new migration in `apps/ingestion/migrations/`
- `apps/ingestion/management/commands/process_ingestion_runs.py`
- focused tests under `tests/unit/`

If you need more than 6 files, stop and explain why in the report.

## TDD instructions

Follow red → green → refactor.

1. Write failing tests first.
2. Prove the failure is due to missing heartbeat behavior.
3. Implement the smallest clean solution.
4. Refactor only after tests pass.

Prefer a small helper/context manager for heartbeat rather than scattering update
statements throughout business logic. Keep YAGNI: no Docker/PID checks, no stale
recovery and no new scheduler in this slice.

## Acceptance criteria

- Tests prove heartbeat is populated when a run starts processing.
- Tests prove heartbeat refresh can be triggered without real sleeping.
- Tests prove heartbeat helper stops cleanly on success/failure path.
- Existing worker status transitions still pass focused tests.
- Migration is present and safe: nullable field, no backfill required.
- No patient-sensitive data is added to logs or output.

## Validation gates

Run the most focused useful commands first, then official gates for touched
scope when feasible:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate stale-ingestion-run-recovery --type change --strict
```

Also run focused tests in container for the new/changed tests. If full unit
suite fails due to known pre-existing `mupdf` issue, document it and include the
focused passing evidence.

If any Markdown file is edited, run markdown lint for the changed files.

## Required report

Create `/tmp/sirhosp-slice-SIRS-S1-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for each changed production file;
- tests and commands executed with results;
- risks and pending items;
- suggested next step.

Do not include real patient data, credentials or sensitive logs.
