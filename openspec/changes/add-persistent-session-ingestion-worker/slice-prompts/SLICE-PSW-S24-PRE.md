# SLICE PSW-S24-PRE: Guarded Real Multi-Run Execution

## Handoff for a Context-Zero Implementer

Implement only PSW-S24-PRE after PSW-S23 and its corrective audit are committed,
pushed, and independently approved. Read `AGENTS.md`, the complete active
OpenSpec change, this prompt, the PSW-S23 reports, the persistent worker command,
its focused command tests, and the rollout guide. Start from a clean tree.

The blocking fact is specific: the command creates one persistent adapter for a
process, but the current `--real-handle` guard requires one `--run-id` and
`--max-runs 1`. Therefore, the real CLI cannot yet execute two jobs under one
login, exercise restart before a later claim, or start the documented continuous
real queue worker. Fake parity is not operational proof.

This slice adds only the guarded command surface needed before PSW-S24 live
validation. It does not access the legacy system and cannot declare rollout
readiness.

## Mandatory Protocol for the Implementing LLM

If any item fails, report `Status: INCOMPLETE/BLOCKED`; do not mark `tasks.md`,
commit, or push.

1. Record `BASE_REF`, branch, clean status, and a
   `Requirement -> file(s) -> test(s)` matrix before editing.
2. Run official `check`, `unit`, and `integration` baselines. Record exit codes
   and exact summaries. Stop if the baseline has failures or errors.
3. Add focused command tests first. Run the official unit command and capture at
   least one new failure proving that the current single-run real guard rejects
   the required bounded multi-run mode.
4. Implement the smallest command orchestration change that satisfies the
   closed mode matrix below. Do not edit extractors, navigation, PDF,
   persistence, models, or queue producers.
5. Re-run the focused command behavior and official unit suite for GREEN, then
   refactor only duplicated validation/selection code.
6. Run every mandatory inspection and official gate. Record command, exit code,
   and summary, not only a claim that it passed.
7. Update `tasks.md` only after every binary criterion passes. Create the
   required report with literal Before/After fragments for every changed file.
8. Commit and push only a COMPLETE slice, then stop. Never begin PSW-S24 live
   validation in this slice.

## Inherited Contracts — Frozen and Not Reopened

PSW-S17 through PSW-S23 are frozen. Preserve their timeout taxonomy,
sanitation, attempt/lifecycle behavior, cleanup, restart thresholds, canonical
chunking, PDF acquisition, clinical persistence, and parity assertions.

The following behaviors are especially frozen:

- the current `process_ingestion_runs` command is unchanged;
- the existing single-run smoke remains exactly
  `--real-handle --run-id ID --max-runs 1`;
- unsupported, empty, conflicting, not-due, missing, or non-queued selected runs
  receive no source action and no mutation;
- one adapter owns one session lifecycle for the command invocation;
- queue claims remain transactional with `select_for_update(skip_locked=True)`;
- no subprocess, temporary clinical artifact, second Playwright runtime, or
  browser/context launch may occur per job;
- rollout remains blocked until PSW-S24 succeeds with authorized live evidence.

If a test exposes a defect outside command orchestration, stop and propose a
separate focused remediation. Do not fix it here.

## Objective

Make the real persistent worker operationally capable of:

1. processing a small, explicit, ordered allow-list of operator-selected runs
   under one real authenticated session for PSW-S24; and
2. entering the existing continuous real queue loop only behind an explicit,
   default-off rollout opt-in.

Neither capability is enabled in deployment by this slice.

## Closed CLI Mode Matrix

Implement exactly these modes. Do not add aliases, implicit fallbacks, or a
second configuration mechanism.

| Mode | Required CLI contract | Queue ownership |
| --- | --- | --- |
| safe stub | no `--real-handle` | existing behavior unchanged |
| single real smoke | `--real-handle --run-id ID --max-runs 1` | exactly `ID` |
| bounded validation | selected IDs + exact cap | listed order |
| continuous queue | loop + explicit opt-in | enabled intents |

Bounded live validation has these fixed rules:

- `--validation-run-id` is repeatable;
- the list contains 2 through 4 distinct positive IDs;
- `--max-runs` is mandatory and equals the list length;
- `--loop`, `--run-id`, and `--enable-real-queue` are forbidden;
- every listed row passes all preflight checks before browser/adapter creation;
- processing never falls through to an unlisted queue row;
- selected runs are claimed in operator-supplied order, not primary-key order;
- if a selected row becomes unclaimable after preflight, stop without claiming
  another row;
- if a processed run does not finish as `succeeded`, stop and leave all later
  selected rows untouched;
- output for this mode uses only ordinal/count information and sanitized
  lifecycle messages, never run IDs, patient identifiers, clinical content,
  URLs, credentials, cookies, HTML, or PDF data.

Continuous real queue mode has these fixed rules:

- `--enable-real-queue` defaults to false and is valid only with both
  `--real-handle` and `--loop`;
- `--run-id`, `--validation-run-id`, and `--max-runs` are forbidden;
- `--real-handle --loop` without the opt-in still fails before adapter/browser
  creation and before a claim;
- adding the opt-in makes the existing loop reachable; it does not create a new
  queue, claim algorithm, worker service, or deployment default;
- documentation must keep this path disabled and NOT rollout-ready until
  PSW-S24 completes.

Every CLI combination outside this matrix fails before `_create_adapter()` and
before any run mutation.

## Requirements

- **R1 — Closed mode parser:** Add only the repeatable
  `--validation-run-id` option and boolean `--enable-real-queue` option, then
  validate the complete mode matrix before adapter creation.
- **R2 — Single-smoke regression:** Preserve the existing one-ID real smoke and
  its fail-fast guard behavior byte-for-byte at the observable CLI/DB boundary.
- **R3 — All-or-nothing preflight:** Validate every bounded selected row for
  existence, positive/distinct ID, queued state, retry due time, enabled intent,
  and model/JSON intent agreement before any login or mutation.
- **R4 — Exact ordered claims:** In bounded mode, claim only the next listed ID
  under the existing row-lock discipline. Never call the generic next-run claim
  as a fallback.
- **R5 — Real session reuse:** Create/bootstrap one adapter before the first
  selected claim, reuse it across consecutive selected jobs, run safe cleanup
  through existing behavior after each job, and shut it down once.
- **R6 — Restart before later claim:** With four selected jobs and
  `--max-jobs 3`, prove jobs 1 through 3 use the initial bootstrap, then
  `restart_and_rebootstrap()` succeeds before job 4 is claimed. A restart
  failure leaves job 4 queued and untouched.
- **R7 — Stop on failed validation job:** If any selected run ends queued for
  retry, failed, cancelled, or otherwise not succeeded, do not claim a later
  selected run.
- **R8 — Default-off continuous path:** Make the existing real loop reachable
  only through `--enable-real-queue`; preserve the existing enabled-intent
  filter, locking, readiness-before-claim, and graceful shutdown.
- **R9 — Sanitized bounded operation:** Do not emit selected IDs or source data
  in the new bounded-mode output, report, tests, or docs. Synthetic test IDs and
  anonymous payloads remain allowed in test fixtures.
- **R10 — Honest artifacts:** Update design/spec/tasks/rollout text to describe
  the three real modes, keep deployment disabled, and state that authorized
  PSW-S24 live validation is still mandatory.

## Expected Scope and File Freeze

Maximum: exactly these 6 versioned files may change:

1. `apps/ingestion/management/commands/` plus
   `process_ingestion_runs_persistent_session.py`;
2. `tests/unit/test_persistent_worker_command.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/design.md`;
4. `openspec/changes/add-persistent-session-ingestion-worker/specs/` plus
   `persistent-session-ingestion-worker/spec.md`;
5. `docs/operations/persistent-worker-rollout.md`;
6. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`.

The line-wrapped path fragments above each denote one file, not a directory
allowance. Do not edit this prompt during implementation.

Forbidden: models, migrations, settings, environment defaults, compose/systemd,
queue producers, current worker, adapter/controller/bridge, Playwright handle,
navigation/selectors, PDF flow, persistence services, other tests, proposal,
ADRs, dependency files, and live artifacts. If a seventh versioned file is
needed, stop as blocked and explain why.

## TDD

### RED

Add tests for the closed matrices below before production edits. The current
code must fail at least the bounded multi-run entry test because it permits only
one real selected run.

- **Single smoke regression:** one explicit run still passes; a missing or wrong
  cap still fails before adapter creation.
- **Bounded happy path:** four heterogeneous listed runs execute in listed order
  with one adapter.
- **Bounded guard matrix:** list size, duplicate/nonpositive ID, cap mismatch,
  and conflicting flags fail before adapter creation.
- **All-row preflight:** one bad row among valid rows leaves every row unchanged
  and creates no adapter.
- **No fallthrough:** unlisted eligible rows remain queued before, during, and
  after the selected sequence.
- **Claim race:** a selected row no longer queued causes a stop; no generic row
  is claimed.
- **Failed job:** later selected rows remain queued after a non-success result.
- **Restart success:** restart/rebootstrap occurs after job 3 and before claim 4.
- **Restart failure:** job 4 remains queued and receives no source action.
- **Continuous opt-in:** the real loop is rejected by default and reached only
  with the exact opt-in combination.
- **Sanitation:** new bounded output contains no selected IDs or synthetic
  patient tokens.

Use fakes/mocks only at the real browser boundary. Tests must exercise command
parsing, preflight, transaction/claim selection, and database state; assertions
only on mock calls are insufficient.

### GREEN

Prefer one normalized mode validator and one ordered selected-ID cursor in the
existing command. Reuse current preflight, intent validation, claim locking,
processing, controller, and shutdown behavior. Do not duplicate the worker
loop or per-intent dispatch.

### REFACTOR

Remove obsolete single-mode comments after GREEN and document the closed mode
in the command help/docstring. Keep helpers narrow and typed. Do not generalize
into a workflow framework or configuration abstraction.

## Mandatory Inspection Checks

Run and interpret all results in the report:

```bash
rg -n "validation-run-id|enable-real-queue|real-handle|max-runs" \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py \
  tests/unit/test_persistent_worker_command.py \
  docs/operations/persistent-worker-rollout.md
rg -n "_claim_eligible_run|select_for_update|skip_locked|_create_adapter" \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py
rg -n "subprocess|TemporaryDirectory|sync_playwright|launch" \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py
rg -n "production rollout-ready|NOT production|blocked|PSW-S24" \
  openspec/changes/add-persistent-session-ingestion-worker \
  docs/operations/persistent-worker-rollout.md
```

Also inspect the final diff by file. Any change outside the six-file allow-list,
generic queue fallback in bounded mode, or readiness claim is automatic
incompletion.

## Binary Success Criteria

- [ ] The existing single real smoke contract is unchanged and regression-tested.
- [ ] Bounded mode accepts 2 through 4 distinct listed IDs only.
- [ ] All listed rows preflight before one adapter/bootstrap is created.
- [ ] Four heterogeneous jobs execute in supplied order without an unlisted claim.
- [ ] Jobs before the threshold share the initial login/session.
- [ ] Restart plus rebootstrap completes before the post-threshold claim.
- [ ] Restart or job failure leaves every later selected row untouched.
- [ ] Real continuous loop remains unreachable without explicit opt-in.
- [ ] Opted-in loop reuses existing readiness, claim, lock, and shutdown paths.
- [ ] New output/artifacts contain no selected IDs or source data.
- [ ] Deployment remains disabled and readiness remains blocked pending PSW-S24.
- [ ] Only the six allowed files changed.
- [ ] All official gates, strict OpenSpec validation, and Markdown lint pass.

## Automatic INCOMPLETE Conditions

Mark the slice incomplete if any planned test is absent; RED is not captured;
a mode outside the closed matrix is accepted; validation mode can claim an
unlisted row; any preflight failure starts the adapter; a later run is claimed
after job/restart failure; continuous real queue operation is enabled by
default; the single smoke regresses; a frozen subsystem changes; any gate fails;
`tasks.md` is checked early; the report is missing; or rollout readiness is
claimed without PSW-S24 evidence.

## Self-Evaluation Gates

1. Can `--real-handle` process multiple arbitrary queue rows without an explicit
   opt-in?
2. Can bounded mode process any row not present in the operator allow-list?
3. Can login/browser creation occur before every selected row passes preflight?
4. Do the first three jobs in the restart test share the initial bootstrap?
5. Is rebootstrap complete before the fourth claim?
6. Does the continuous path use the existing queue/locking implementation?
7. Was any bridge, selector, PDF, persistence, model, deployment, or current
   worker file changed?
8. Do docs still block rollout pending PSW-S24?

Required answers: no, no, no, yes, yes, yes, no, yes.

## Validation

Run all commands exactly and record exit codes/summaries:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate add-persistent-session-ingestion-worker --strict
./scripts/markdown-lint.sh
```

The final unit and integration totals must be greater than or equal to their
baselines, with exit code 0 and zero failures/errors. A narrower diagnostic run
does not replace the official commands.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S24-PRE-report.md` containing:

- `Status: COMPLETE` or `Status: INCOMPLETE/BLOCKED`;
- `BASE_REF`, branch, and initial/final clean-status evidence;
- requirement/file/test matrix;
- official baseline summaries;
- real RED command, failing tests, and expected reasons;
- GREEN/refactor evidence;
- complete CLI mode and negative-guard matrix;
- ordered four-job trace using only ordinal labels;
- adapter/bootstrap/restart/rebootstrap/shutdown cardinalities;
- preflight, no-fallthrough, failure-stop, and sanitation evidence;
- literal Before/After fragments for every changed file, with no ellipses;
- inspection commands and interpretations;
- official final gate exit codes and summaries;
- changed-file allow-list comparison;
- risks, limitations, exact verifier reruns, and R1-R10 checklist.

Do not include real IDs, patient identifiers, clinical content, URLs, HTML, PDF
bytes, screenshots, cookies, credentials, or secrets.

Final prompt: implement only PSW-S24-PRE. Preserve the single real smoke, add the
bounded ordered allow-list and explicit default-off real queue opt-in, prove
session reuse and restart-before-next-claim through command/DB tests, keep
rollout blocked, run every official gate, create the report, commit, push, and
stop. Any missing proof or scope breach means INCOMPLETE.
