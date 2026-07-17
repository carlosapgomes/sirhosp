# SLICE PSW-S16: Persistent Demographics-Only End-to-End

## Handoff for a Context-Zero Implementer

Implement only PSW-S16 after PSW-S15 is committed and pushed. Read:

- `AGENTS.md`, `PROJECT_CONTEXT.md`, and all change artifacts;
- PSW-S14 and PSW-S15 reports;
- current `_process_demographics_only` and its tests;
- `automation/source_system/patient_demographics/extract_patient_demographics.py`;
- persistent navigation, bridge, adapter, handle, command, and session tests;
- `upsert_patient_demographics`.

The current script is a behavioral reference, not code to invoke from the
persistent path. Use only synthetic anonymous values.

## Mandatory DeepSeek4-Flash Protocol

The slice is incomplete if any required baseline, RED, inspection, gate, or
report evidence is missing.

1. Record `BASE_REF`, branch, and clean status.
2. Build `Requirement -> files -> tests/inspection` in the report.
3. Run official unit baseline before editing and record exit code and summary.
4. Write tests first; capture a behavioral RED.
5. Implement minimum GREEN through the existing authenticated page/context.
6. Run forbidden-call inspections and interpret results.
7. Run all validation commands.
8. Mark tasks, report, commit, push, and stop only when complete.

## Objective

Process `demographics_only` entirely through the persistent authenticated
session, normalize data in memory, and persist it with the canonical service.

## Required End-to-End Flow

```text
claimed demographics_only run
-> session readiness/renewal checkpoint
-> search patient in existing page
-> open Dados do Paciente
-> read Cadastro fields from frame_pol
-> normalize an in-memory dict
-> upsert_patient_demographics
-> record stages/metrics/status
-> close only the non-root legacy tab
-> reuse the same session for the next job
```

## Requirements

- **R1:** Add action navigation to `Dados do Paciente` modeled on the working
  script, using the already-open Playwright Page.
- **R2:** Read every demographic field currently consumed by
  `upsert_patient_demographics`, including missing/empty values safely.
- **R3:** Expose one focused persistent adapter/bridge method accepting
  `patient_record` and timeout and returning normalized data in memory.
- **R4:** In the same change that implements the persistent behavior, add
  `demographics_only` to the enabled claim/dispatch contract and persist via
  `upsert_patient_demographics`.
- **R5:** Preserve `demographics_extraction` and `demographics_persistence`
  stages, attempts, retry/timeout taxonomy, heartbeat, field-count metric,
  cleanup, and batch closure.
- **R6:** Missing patient record fails validation before source actions.
- **R7:** Perform no subprocess, temporary directory/JSON, filesystem debug
  artifact, `sync_playwright`, browser/context launch, or second login.
- **R8:** Characterize the current worker and keep it unchanged for rollback.
- **R9:** Prove admissions -> demographics can run on one handle with one login.

## Expected Scope

Target maximum: 8 versioned files including `tasks.md`.

Expected:

- one focused persistent-demographics/navigation module or a cohesive extension
  of the existing navigation module;
- bridge/adapter boundary;
- persistent command dispatch;
- focused unit tests and one command/integration-style test;
- `tasks.md`.

Forbidden: modifying the current demographics script, current worker behavior,
models/migrations, evolution/PDF code, templates, real credentials/data.

## TDD

### RED

Add tests for navigation, field extraction, missing fields, timeout, persistence,
stages, field count, cleanup, and same-handle reuse. Spy on subprocess,
`sync_playwright`, browser launch, context creation, login/bootstrap, temporary
files, and debug writes. At least one initial failure must be missing persistent
demographics behavior.

### GREEN

Port only the minimal action/field-reading behavior needed by the persistent
boundary. Return an in-memory dictionary and reuse the existing persistence
service.

### REFACTOR

Centralize selectors and field mapping. Do not copy CLI, environment loading,
debug artifact, or browser startup code from the script.

## Mandatory Inspection Checks

```bash
rg -n \
  -e "subprocess|run_subprocess|TemporaryDirectory|json_output" \
  -e "sync_playwright|launch" \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py \
  apps/ingestion/extractors
rg -n "Dados do Paciente|frame_pol|DEMOGRAPHIC|demographics" \
  apps/ingestion/extractors apps/ingestion/management/commands
rg -n "debug.html|write_text|screenshots?|cookies?" apps/ingestion/extractors
```

Explain legitimate existing occurrences. New demographics execution must contain
none of the forbidden lifecycle/filesystem calls.

## Binary Success Criteria

- [ ] R1-R9 tests pass.
- [ ] Canonical demographic fields persist correctly.
- [ ] Stages and field-count metric match current behavior.
- [ ] Same handle/login is reused across admissions and demographics jobs.
- [ ] Claim enablement and complete demographics dispatch land atomically.
- [ ] All forbidden-call spies remain zero.
- [ ] Current worker/script remain unchanged.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Did the persistent demographics path launch or invoke another process?
2. Can missing date/optional fields fail the whole extraction unexpectedly?
3. Does every persisted field come from the in-memory normalized contract?
4. Are source and persistence failures distinguished?
5. Is any real patient value present in tests/reports?

Required answers: no, no, yes, yes, no.

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

Create `/tmp/sirhosp-slice-PSW-S16-report.md` with matrix, baseline, RED/GREEN,
field-contract table, forbidden-call evidence, snippets, commands and exit codes,
changed files, risks, and verifier handoff.

Final prompt: implement only PSW-S16. If persistent demographics performs any
new process/browser/login/file exchange, or any gate is missing, report
`Status: INCOMPLETE` and stop without tasks/commit/push.
