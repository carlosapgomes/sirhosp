# SLICE PSW-S4: New Persistent-Session Worker Command

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S4 for OpenSpec change
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
6. The code and reports from PSW-S1, PSW-S2, and PSW-S3

Implement the new management command for the persistent-session worker and wire
it to the admissions-only persistent adapter. Do not implement full-sync
evolution extraction in this slice.

## Current Code to Inspect

Inspect these files before coding:

- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `apps/ingestion/models.py`
- tests touching `IngestionRun`, worker heartbeat, attempts, retries, and
  admissions-only processing

The new command must preserve external queue/run semantics while leaving the
current command available.

## PSW-S3 Verification Notes to Address

The PSW-S3 verifier reported non-blocking items that become explicit PSW-S4
handoff requirements:

- The adapter intentionally does not close job tabs on data failures such as a
  missing snapshot container or invalid JSON. The PSW-S4 command/controller
  orchestration must call `close_job_tab_if_present()` in a `finally`-style path
  after admissions-only success and after recoverable admissions-only errors,
  before claiming another run.
- If tab cleanup is unsafe, the worker must recover the session, relog, or
  restart before claiming another run. Do not treat tab close as session
  renewal evidence.
- The PSW-S3 adapter depends on a synthetic snapshot container such as
  `<div id="admission-snapshot-data">`. The real or fake `SessionHandle` wired
  in PSW-S4 must explicitly provide that adapter contract, either by extracting
  or injecting the expected container or by passing already-normalized content
  through a clearly tested boundary.
- The `timeout` parameter accepted by the adapter must be propagated to the real
  handle/wait path or the command must stop and report a blocker. Do not leave a
  production command that accepts timeout while silently ignoring it.
- URL templates or navigation parameters using `patient_record`, `start_date`,
  or `end_date` must be safely encoded before real navigation. Add tests for
  encoded patient/date parameters if PSW-S4 introduces real URL formatting.

## Scope

Target maximum changed files: 8.

Expected files:

- one new management command file;
- unit/integration tests for command behavior;
- small shared helper module only if it avoids duplication without changing
  current worker behavior;
- minimal adapter wiring from PSW-S3.

Do not remove or rewrite `process_ingestion_runs.py`. A minimal import-only or
helper reuse is acceptable only if tests prove current command behavior remains
unchanged. If a larger refactor is needed, stop and report a blocker.

## Development Method

Use TDD strictly:

1. Write failing tests for claim, label, heartbeat, admissions-only success or
   failure, cleanup on recoverable error, timeout propagation, and URL encoding
   when real navigation formatting is introduced.
2. Implement the smallest command behavior.
3. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- keep management command orchestration thin;
- put browser/session logic in the adapter/controller from previous slices;
- do not add Celery, Redis, a new queue, or a daemon outside Django command;
- do not implement full-sync in this slice.

## Required Behavior

Add command tentatively named:

```bash
uv run python manage.py process_ingestion_runs_persistent_session
```

The command must support:

- `--loop`;
- `--sleep-seconds`;
- `--headless` and `--no-headless` if applicable;
- graceful shutdown on SIGTERM/SIGINT;
- safe worker label behavior using `SIRHOSP_WORKER_LABEL` or a persistent-worker
  default prefix;
- session readiness before claiming runs, using safe tab opening for proactive
  renewal when renewal is needed;
- PostgreSQL-safe claim semantics equivalent to the current worker;
- `WorkerHeartbeat`-equivalent refresh while processing;
- admissions-only processing through the persistent adapter;
- `close_job_tab_if_present()` after admissions-only success and recoverable
  admissions-only failures before claiming another run;
- real/fake `SessionHandle` contract that supplies the admission snapshot
  container/content expected by the PSW-S3 adapter;
- timeout propagation to source-system waits/actions;
- safe encoding for real navigation parameters if URL templates are used;
- existing attempt/status/stage/failure/batch closure semantics.

## Acceptance Criteria

- Tests prove two workers cannot claim the same queued run.
- Tests prove persistent worker labels are safe and distinguishable.
- Tests prove heartbeat is populated/refreshed during processing.
- Tests prove admissions-only success persists lifecycle and stage metrics.
- Tests prove admissions-only failure preserves retry/failure taxonomy.
- Tests prove tab cleanup is attempted after success and recoverable data
  failures before the next claim.
- Tests prove unsafe cleanup forces recovery, relogin, or restart before the
  next claim.
- Tests prove timeout is propagated to the session handle/wait path.
- Tests prove URL parameters are encoded if real URL formatting is introduced.
- Tests prove current `process_ingestion_runs` remains executable.
- No full-sync evolution extraction is added in this slice.

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

Create `/tmp/sirhosp-slice-PSW-S4-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
