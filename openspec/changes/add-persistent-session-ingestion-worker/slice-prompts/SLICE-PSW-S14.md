# SLICE PSW-S14: Explicit Supported-Intent Contract

## Handoff for a Context-Zero Implementer

Implement only PSW-S14 on branch
`feature/add-persistent-session-ingestion-worker`.

Read first:

1. `AGENTS.md` and `PROJECT_CONTEXT.md`;
2. this change's `proposal.md`, `design.md`, `tasks.md`, and specs;
3. `/tmp/sirhosp-slice-PSW-S13-report.md`;
4. both ingestion worker commands;
5. `apps/ingestion/services.py` and every producer of queued
   `IngestionRun` rows;
6. focused worker, retry, and batch tests.

PSW-S13 must be committed and the tree must be clean. Stop if another slice or
unrelated work is present.

## Mandatory DeepSeek4-Flash Protocol

This slice is incomplete if any step below is missing or fails. If incomplete,
do not update `tasks.md`, commit, or push.

1. Record `BASE_REF=$(git rev-parse HEAD)` and a clean `git status --short`.
2. Write a report matrix `Requirement -> file(s) -> test(s)/inspection`.
3. Before editing, run `./scripts/test-in-container.sh unit`; record exit code,
   passed/failed/error summary, and warnings separately.
4. Write tests first. Run the unit gate and capture at least one new failure for
   the expected behavioral reason, not syntax or fixture failure.
5. Implement the minimum change, then rerun the unit gate to GREEN.
6. Run the inspection checks below and interpret every occurrence.
7. Run every validation command in this file. Any nonzero exit code means
   incomplete.
8. Update only PSW-S14 checkboxes after all evidence passes, create the report,
   commit, push, reply with `REPORT_PATH=...`, and stop.

## Objective

Make queue ownership and dispatch explicit. The final replacement target covers
`admissions_only`, `demographics_only`, `full_sync`, and
`full_admission_sync`, but this slice enables only intents with complete
persistent behavior at its start. `demographics_only` remains unclaimed until
PSW-S16 atomically adds its implementation and enables it. Empty or unknown
intents must never fall through to full-sync.

## Current Problem

The persistent command claims any queued row and uses `else -> full_sync`.
That can misprocess unsupported work. Empty intent has no approved action and is
not part of replacement scope.

## Requirements

- **R1:** Define one explicit enabled-intent contract used by both claim
  eligibility and dispatch.
- **R2:** Enable `admissions_only`, `full_sync`, and `full_admission_sync` during
  normal polling; dispatch `full_admission_sync` explicitly to full-sync.
- **R3:** Recognize `demographics_only` as required replacement scope but leave
  it unclaimed until PSW-S16 adds a complete persistent dispatch in the same
  change that enables its claim.
- **R4:** Do not claim empty, unknown, or not-yet-enabled intents during normal
  polling.
- **R5:** If `--run-id` selects an empty, unknown, or not-yet-enabled intent,
  fail validation without changing run status, attempts, stages, clinical data,
  or source-session state.
- **R6:** Characterize production enqueue helpers and prove they create explicit
  non-empty target intents. Do not add a default intent or migration.
- **R7:** Keep the current worker executable and unchanged for rollback, so it
  continues to consume demographics until PSW-S16 is complete.

## Expected Scope

Target maximum: 4 versioned files, including `tasks.md`.

Expected:

- `process_ingestion_runs_persistent_session.py`;
- `tests/unit/test_persistent_worker_command.py`;
- one focused producer test only if existing coverage is insufficient;
- `tasks.md`.

Forbidden: models, migrations, browser/session code, current-worker refactor,
clinical persistence changes, demographics implementation, rollout docs.

## TDD

### RED

Add tests proving R2-R6. At least one test must show that an unsupported or
not-yet-enabled queued run remains untouched while an enabled run is processed.
Add one explicit selected-intent test that asserts zero adapter/source calls.

### GREEN

Implement a small explicit mapping/set for enabled dispatch and use it
consistently in claim and dispatch. Do not duplicate enabled lists across
methods. Do not add a placeholder demographics handler.

### REFACTOR

Remove implicit fallback only. Keep names literal; avoid registries or plugin
abstractions. Do not claim a target intent before its behavior is complete.

## Mandatory Inspection Checks

Run and explain:

```bash
rg -n "admissions_only|demographics_only|full_sync|full_admission_sync" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "else:|_process_full_sync" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "intent=.*queued|intent=\"\"|\"intent\": \"\"" apps tests
```

Expected: explicit supported occurrences; no generic dispatch fallback; no
production queue helper creating an empty intent. Test fixtures must be
identified separately from production producers.

## Binary Success Criteria

- [ ] All R1-R7 tests pass.
- [ ] Empty/unknown normal-poll rows remain untouched.
- [ ] `demographics_only` remains queued for the current worker until PSW-S16.
- [ ] Explicit unsupported/not-yet-enabled selection performs zero source and
  clinical side effects.
- [ ] Enabled claim and dispatch contracts are identical.
- [ ] Current worker regression tests pass.
- [ ] No forbidden file changed.
- [ ] All official gates pass.

## Self-Evaluation Gates

Answer yes/no with evidence:

1. Can any unknown string still reach full-sync?
2. Is the claim filter identical to the dispatch contract?
3. Can an unsupported selected run mutate attempts or status?
4. Did any producer gain a fabricated default intent?
5. Did this slice implement behavior reserved for later slices?

Any answer other than `no, yes, no, no, no` is incomplete.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S14-report.md` with status, matrix, baseline,
RED, GREEN, before/after snippets, inspections, every command plus exit code,
changed files, scope justification, binary criteria, self-evaluation, and a
verifier handoff containing exact rerun commands and risks.

Final prompt: implement only PSW-S14. If any required evidence or gate is
missing, report `Status: INCOMPLETE` and do not update tasks, commit, or push.
