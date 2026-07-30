# SLICE PSW-S23: Current-Versus-Persistent Parity Suite

## Handoff for a Context-Zero Implementer

Implement only PSW-S23 after PSW-S22 is committed. Read project instructions,
all change artifacts and PSW-S14-S22 reports, both commands, all supported-intent
services/models, and existing worker integration tests. Start clean.

This slice is a parity proof and may make narrowly required fixes only when a
failing parity case exposes a small defect within the file budget. Do not weaken
assertions to preserve known differences.

## Mandatory Protocol for the Implementing LLM

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

## Inherited Contracts — Frozen and Not Reopened

PSW-S17 through PSW-S22 are frozen prerequisites. This slice composes their
observable outcomes; it does not re-prove every timeout category, cleanup
state, restart threshold, chunk boundary, or PDF validation for every intent.

Observable-surface sanitization and cooperative deadline semantics remain as
defined by PSW-S17. Suppressed internal exception context is not re-audited.

An inherited non-critical defect becomes a separate focused remediation. If a
parity failure requires broad production work or exceeds the file cap, stop
blocked instead of expanding PSW-S23.

## Acceptance Freeze and Artifact Policy

Use the pairwise scenario matrix below. It is the complete parity proof; do not
form the Cartesian product of four intents, every historical failure category,
and every lifecycle mode.

Update active requirements in place; do not append D-numbered corrective
sections. Report Before/After fragments only for files changed in this pass.

## Objective

Prove that the persistent worker can replace the current worker for every
supported intent while reusing one authenticated session across heterogeneous
jobs.

## Requirements

- **R1:** Use one pairwise scenario table for `admissions_only`,
  `demographics_only`, `full_sync`, and `full_admission_sync` with equivalent
  synthetic source data.
- **R2:** For each row, compare only the listed observable run/lifecycle,
  persistence, and counter effects. Do not compare private call order.
- **R3:** Cover the shared failure boundary once for timeout, invalid payload,
  retryable failure, and attempts exhausted; do not multiply those cases by
  every intent because PSW-S17 already owns failure taxonomy parity.
- **R4:** Normalize only enumerated non-semantic differences such as worker
  label/PID and clock values. List each normalization in the report.
- **R5:** Run `admissions_only -> demographics_only -> full_sync ->
  admissions_only` with one handle and assert one login, no browser/context
  relaunch, and safe cleanup after each job.
- **R6:** Assert no persistent-job subprocess, temporary JSON, synthetic direct
  real URL, or secret/clinical artifact.
- **R7:** Empty/unknown intents remain outside replacement scope and receive no
  source action.
- **R8:** Keep rollout blocked; fake parity is not live readiness.

## Closed Pairwise Parity Matrix

| Scenario | Required comparison |
| --- | --- |
| `admissions_only` success + dedup | counters, patient/admission, follow-ups |
| `demographics_only` success + update | fields, metrics, follow-ups |
| `full_sync` success + no evolutions | gaps, events, batch/stages |
| `full_admission_sync` success | admission association and revisions |
| shared timeout boundary | timeout category and retry scheduling |
| shared invalid payload boundary | normalized failure and no bad persistence |
| shared retryable failure | queued retry and no final failure |
| shared attempts exhausted | terminal state, final failure, batch closure |
| heterogeneous sequence | one login/handle; cleanup between jobs |
| empty/unknown intent | no source action |

Each supported intent needs its assigned row, not both a success and every
failure row.

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

- [ ] All four supported intents pass their assigned pairwise scenario.
- [ ] Shared timeout/invalid/retry/terminal rows compare equal effects.
- [ ] Clinical and operational persistence matches in the assigned rows.
- [ ] Multi-job sequence uses one login/handle before configured restart.
- [ ] Forbidden lifecycle/artifact calls remain zero.
- [ ] Empty/unknown intents cause no source action.
- [ ] No assertion was weakened without a documented intentional difference.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Does any supported intent lack its assigned pairwise comparison?
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
Include real Before/After fragments only for files changed in this pass.

Final prompt: implement only PSW-S23. Missing intent/scenario coverage, mock-only
proof, hidden difference, failing gate, or readiness overclaim means incomplete.
