# SLICE PSW-S15: Admissions-Only Persistence Parity

## Handoff for a Context-Zero Implementer

Implement only PSW-S15 on branch
`feature/add-persistent-session-ingestion-worker` after PSW-S14 is committed.

Read `AGENTS.md`, `PROJECT_CONTEXT.md`, all change artifacts, the PSW-S14
report, both worker commands, `apps/ingestion/services.py`, admission models,
batch closure, and current admissions worker tests. Start from a clean tree.

## Mandatory DeepSeek4-Flash Protocol

If any item fails, mark the slice incomplete; do not update tasks or commit.

1. Record `BASE_REF`, branch, and clean status.
2. Write the report matrix `Requirement -> files -> tests`.
3. Run the official unit baseline before editing and record exit code plus
   passed/failed/error summary.
4. Write failing parity tests first and capture a real RED.
5. Implement minimum GREEN; no broad command rewrite.
6. Run and interpret mandatory inspections.
7. Run all official gates and OpenSpec/Markdown validation.
8. Only then mark PSW-S15, write the report, commit, push, and stop.

## Objective

Make persistent `admissions_only` produce the same clinical and operational
outcome as the current worker: canonical persistence, accurate counters,
follow-up jobs, attempts, stages, and batch closure.

## Current Problem

The persistent worker counts the adapter result and sets
`admissions_created = admissions_seen` without persisting the snapshot. It also
omits demographics and full-sync follow-ups.

## Requirements

- **R1:** Characterize current admissions-only success, zero-result, update,
  failure, and follow-up behavior before refactoring.
- **R2:** Persist patient/admissions through the canonical existing services,
  including ward/bed backfill behavior.
- **R3:** Populate seen/created/updated from database outcomes, never list length
  assumptions.
- **R4:** Enqueue one `demographics_only` follow-up under the same conditions as
  the current worker.
- **R5:** Enqueue the most-recent-admission full-sync follow-up with equivalent
  parameters and batch relationship.
- **R6:** Preserve stage, attempt, retry, timeout, heartbeat, terminal status,
  and batch semantics.
- **R7:** Zero admissions must not fabricate created rows or full-sync work.
- **R8:** Avoid two divergent copies of admissions business orchestration; share
  only the smallest cohesive service/helper justified by characterization.
- **R9:** Keep current worker externally unchanged.

## Expected Scope

Target maximum: 7 versioned files including `tasks.md`.

Expected:

- one small shared admissions orchestration service, only if required;
- both worker commands for delegation;
- `apps/ingestion/services.py` only when existing canonical helpers need a thin
  public boundary;
- focused current and persistent worker tests;
- `tasks.md`.

Forbidden: models/migrations, demographics extraction, browser navigation,
evolution/PDF changes, UI/templates, rollout docs.

## TDD

### RED

Use identical synthetic snapshots against both workers and assert Patient,
Admission, counters, follow-up runs, attempt status, stages, and batch outcome.
Include create, update, empty, and persistence-failure cases. The initial RED
must expose the persistent worker's missing persistence or fabricated counter.

### GREEN

Extract/reuse the minimum orchestration and delegate from both commands. Keep
source extraction outside the shared persistence boundary.

### REFACTOR

Remove duplicated business rules introduced during GREEN. Do not generalize to
demographics or evolution ingestion.

## Mandatory Inspection Checks

```bash
rg -n "admissions_created.*admissions_seen|simplified" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "upsert_admission_snapshot|backfill_admission_ward_from_census" \
  apps/ingestion
rg -n "queue_demographics_only_run|_enqueue_most_recent_full_sync" \
  apps/ingestion/management/commands apps/ingestion/services.py
```

Expected: no fabricated-counter assignment; one canonical persistence path; no
accidental duplicate follow-up creation.

## Binary Success Criteria

- [ ] Create/update/empty/failure parity tests pass.
- [ ] Persistent success writes Patient and Admission rows.
- [ ] Counters equal database outcomes.
- [ ] Follow-up intents and parameters match the current worker.
- [ ] No follow-up duplication occurs on retry/reprocessing.
- [ ] Existing current-worker tests remain green.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Can a positive created counter exist without an Admission row?
2. Are extraction and persistence still separated?
3. Did both workers use the same business rule rather than copied logic?
4. Are follow-up batch semantics characterized?
5. Did this slice touch demographics navigation or evolution extraction?

Required answers: no, yes, yes, yes, no.

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

Create `/tmp/sirhosp-slice-PSW-S15-report.md`. Include the protocol evidence,
parity result table for every scenario, before/after snippets, inspections,
commands with exit codes, changed files, scope exceptions, risks, and verifier
handoff.

Final prompt: implement only PSW-S15 with real RED/GREEN evidence. Any false
counter, missing follow-up, failing gate, or uncharacterized current-worker
change makes the slice incomplete.
