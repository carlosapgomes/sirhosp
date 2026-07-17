# SLICE PSW-S23: Current-Versus-Persistent Parity Suite

## Handoff for a Context-Zero Implementer

Implement only PSW-S23 after PSW-S22 is committed. Read project instructions,
all change artifacts and PSW-S14-S22 reports, both commands, all supported-intent
services/models, and existing worker integration tests. Start clean.

This slice is a parity proof and may make narrowly required fixes only when a
failing parity case exposes a small defect within the file budget. Do not weaken
assertions to preserve known differences.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, clean status, requirement matrix, and supported-intent
   table before edits.
2. Run official unit and integration baselines; record both exits/summaries.
3. Add parameterized parity and multi-job tests first; capture real RED if a
   difference remains. If all tests pass immediately, explain why each new test
   still proves a previously untested contract.
4. Fix only small parity defects; stop blocked if broader implementation is
   needed.
5. Run parity/forbidden-call inspections.
6. Run every official gate.
7. Mark tasks/report/commit/push only with complete evidence, then stop.

## Objective

Prove that the persistent worker can replace the current worker for every
supported intent while reusing one authenticated session across heterogeneous
jobs.

## Requirements

- **R1:** Use one scenario table for `admissions_only`, `demographics_only`,
  `full_sync`, and `full_admission_sync` with equivalent synthetic source data.
- **R2:** Compare terminal/intermediate status, attempts, timestamps, stages,
  failure fields, retry scheduling, and `FinalRunFailure`.
- **R3:** Compare run counters, gaps, parameters/metrics, follow-up runs, and
  batch closure.
- **R4:** Compare persisted Patient, Admission, ClinicalEvent, revisions,
  demographics, ward/bed backfill, and admission association.
- **R5:** Cover success, zero-data/no-evolutions, update/dedup, source timeout,
  invalid payload, retryable error, and attempts-exhausted cases.
- **R6:** Normalize only intentional non-semantic differences such as worker
  label/PID and clock values. List every normalization in the report.
- **R7:** Run the sequence `admissions_only -> demographics_only -> full_sync ->
  admissions_only` with one handle and assert one login, no browser/context
  relaunch between jobs, and safe cleanup after each job.
- **R8:** Assert no persistent-job subprocess, temporary JSON, synthetic direct
  real URL, or secret/clinical artifact.
- **R9:** Empty/unknown intents remain outside replacement scope and receive no
  source action.
- **R10:** Keep rollout blocked; fake parity alone is not live readiness.

## Expected Scope

Target maximum: 6 versioned files including `tasks.md`.

Expected: one focused parity test module, existing helper/factory extensions,
small production fixes only if local and justified, and `tasks.md`.

Forbidden: broad refactor, models/migrations, new features, selector redesign,
rollout docs/readiness claim, real access/data.

## TDD

### RED

Build observable snapshots of database/run effects for each worker and compare
by scenario. Do not compare private call order where state is the contract.
Add the heterogeneous multi-job sequence with spies on login/browser/subprocess.

### GREEN

If parity fails, make only the smallest production correction. If correction
exceeds the file budget or belongs to an earlier contract, mark blocked and
name the required remediation slice.

### REFACTOR

Keep test builders readable and deterministic. Avoid one giant fixture or
snapshot blobs that obscure which invariant failed.

## Mandatory Inspection Checks

```bash
rg -n \
  -e "parametrize|admissions_only|demographics_only" \
  -e "full_sync|full_admission_sync" \
  tests/unit tests/integration
rg -n \
  "subprocess|TemporaryDirectory|sync_playwright|launch_persistent_context" \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py \
  apps/ingestion/extractors
rg -n "assert.*worker_label|sleep\(|datetime\.now" tests/unit tests/integration
```

Explain determinism and every intentionally ignored field.

## Binary Success Criteria

- [ ] All four supported intents have parity scenarios.
- [ ] Success/empty/update/timeout/retry/terminal cases compare equal effects.
- [ ] Clinical and operational persistence matches.
- [ ] Multi-job sequence uses one login/handle before configured restart.
- [ ] Forbidden lifecycle/artifact calls remain zero.
- [ ] Empty/unknown intents cause no source action.
- [ ] No assertion was weakened without documented intentional difference.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Does any supported intent lack a success and failure comparison?
2. Are tests comparing only mock calls instead of observable effects?
3. Is any difference hidden by broad snapshot filtering?
4. Did multi-job proof actually execute heterogeneous intents?
5. Does the report claim live or production readiness?

Required answers: no, no, no, yes, no.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S23-report.md` with protocol evidence, full parity
matrix, intentional-difference list, multi-job trace, forbidden-call evidence,
RED/GREEN, commands/exit codes, files, risks, and exact verifier reruns.

Final prompt: implement only PSW-S23. Missing intent/scenario coverage, mock-only
proof, hidden difference, failing gate, or readiness overclaim means incomplete.
