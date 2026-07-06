# SLICE PSW-S9: Real Handle Bridge for Legacy UI Extraction

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S9 for OpenSpec change
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
  docs/operations/persistent-worker-rollout.md \
  openspec/changes/add-persistent-session-ingestion-worker/slice-prompts/SLICE-PSW-S9.md
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
7. `/tmp/sirhosp-slice-PSW-S8-report.md`
8. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
9. `apps/ingestion/extractors/persistent_extraction_adapter.py`
10. `apps/ingestion/extractors/playwright_session_handle.py`
11. `apps/ingestion/extractors/session_controller.py`
12. `apps/ingestion/evolution_ingestion.py`
13. `apps/ingestion/services.py`
14. `automation/source_system/medical_evolution/path2.py`
15. Tests for persistent adapter, persistent command, and Playwright handle

## Context

After PSW-S8, persistent full-sync persistence is wired and has ward/bed
backfill parity with the current worker. The remaining blocker is the real
handle contract:

- `PersistentExtractionAdapter` currently expects synthetic containers:
  `#admission-snapshot-data` and `#evolution-data`.
- The real legacy UI does not produce those containers.
- `PlaywrightSessionHandle` is opt-in via `--real-handle` and remains guarded.

This slice must implement a bridge/translation layer so the real persistent
handle can provide admissions and evolutions to the adapter contract, or stop
with a precise blocker if the real legacy selectors/flows are insufficiently
known from the repository.

## Scope

Target maximum changed files: 12.

Expected files:

- `apps/ingestion/extractors/playwright_session_handle.py` updates;
- `apps/ingestion/extractors/persistent_extraction_adapter.py` updates if the
  boundary is adjusted;
- focused helper module if it keeps bridge logic small and testable;
- unit tests using mocked Playwright pages, synthetic anonymous HTML, or stable
  helper outputs;
- rollout docs update only if the blocker is resolved or clarified.

Do not touch unrelated docs or archived OpenSpec changes. Do not introduce a
new queue, Celery, Redis, microservice, or subprocess-per-job fallback.

If the bridge cannot be implemented safely within 12 files, stop and report a
blocker. Do not fake production readiness.

## Development Method

Use TDD strictly:

1. Add failing tests for the bridge contract using mocks/fakes, not real legacy
   access.
2. Implement the smallest bridge/adapter boundary that satisfies the tests.
3. Add regression tests for timeout propagation, tab cleanup, and guarded
   rollout status.
4. Refactor only after tests pass.

Follow clean code, DRY, and YAGNI:

- keep Playwright mechanics behind the handle;
- keep clinical persistence in shared services;
- do not copy large blocks from `path2.py` unless the copied unit is small,
  pure, and tested;
- prefer reusing stable helper functions from `path2.py` over subprocess calls;
- do not launch a fresh browser per job.

## Required Behavior

Implement one of these contracts:

1. **Synthetic-container bridge:** `PlaywrightSessionHandle` extracts real
   legacy DOM/download data and returns HTML containing the expected synthetic
   containers for the existing adapter.
2. **Normalized-data boundary:** adjust `PersistentExtractionAdapter` and the
   session handle protocol so the handle returns already-normalized admissions
   and evolutions directly.
3. **Path2 helper reuse:** reuse stable extraction/parsing helpers from
   `path2.py` against the already-open persistent page/context, without running
   `path2.py` as a subprocess and without launching a new browser per job.

The chosen approach must preserve:

- admissions snapshot extraction contract;
- evolution extraction contract;
- timeout propagation to source waits/actions;
- session renewal through opening/rendering tabs, not tab close;
- tab cleanup after success and recoverable failures;
- exclusive browser profile behavior;
- safe failure taxonomy with no credential or patient-data leakage;
- no real legacy access in automated tests.

## Acceptance Criteria

- Tests prove `--real-handle` can satisfy admissions and evolution extraction
  contracts using representative mocked legacy UI/download data.
- Tests prove no fake-only synthetic containers are required from the real
  legacy UI itself.
- Tests prove timeout values reach the Playwright wait/action boundary.
- Tests prove tab cleanup remains cleanup only and is not renewal evidence.
- Tests prove persistent full-sync can use the real-handle bridge in a mocked
  end-to-end path through adapter and command.
- If rollout status changes, docs clearly state the new status and remaining
  prerequisites. If rollout remains blocked, docs state the exact blocker.
- Current `process_ingestion_runs` behavior remains unchanged.
- No real patient data, credentials, cookies, screenshots, PDFs, debug HTML, or
  source-system secrets are added.

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

Create `/tmp/sirhosp-slice-PSW-S9-report.md` with:

- slice summary;
- chosen bridge approach and rationale;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- Markdown files validated, if any;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
