# SLICE PSW-S24: Guarded Live Validation and Cutover Readiness

## Handoff for a Context-Zero Implementer

Implement only PSW-S24 after PSW-S23 is committed, pushed, and independently
verified. Read project instructions, all change artifacts, every PSW-S14-S23
report, rollout/deploy guidance, architecture/ADR concurrency limits, and the
real-handle command guardrails. Start from a clean tree.

This slice requires authorized lab/staging access to the real legacy UI and a
non-production or explicitly approved database. If access, authorization, safe
synthetic/approved records, or operator supervision is unavailable, report
`Status: INCOMPLETE/BLOCKED`; do not mark tasks, change rollout status, commit,
or push.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, branch, clean status, environment classification, and
   requirement/evidence matrix without recording secrets.
2. Run official unit and integration baselines before any live action.
3. Obtain explicit operator-provided run IDs and approved observation plan.
   Never discover or print patient identifiers in the report.
4. Execute only guarded commands; stop at the first safety/contract failure.
5. Capture sanitized counters/timestamps/outcomes, never raw HTML, screenshots,
   PDFs, cookies, credentials, clinical text, or identifiers.
6. Run final official gates and documentation inspections.
7. Update readiness docs/tasks, commit, and push only if every criterion passes.
   Otherwise create the blocked report and leave versioned files unchanged.

## Objective

Validate the complete persistent worker against the real legacy UI under the
approved concurrency limit, then make an evidence-based cutover decision while
preserving the current worker as rollback.

## Preconditions

All are mandatory:

- PSW-S23 status is COMPLETE and verifier-approved;
- authorized lab/staging legacy access;
- approved non-sensitive test records/run IDs supplied by an operator;
- persistent-worker scale starts at zero;
- current-worker rollback command is known;
- resource and log observation commands are available;
- concurrency never exceeds the project-approved limit;
- no real artifact may be stored in Git or `/tmp` reports.

## Requirements

- **R1:** Validate one guarded real `admissions_only` run: persistence,
  counters, follow-ups, cleanup, and sanitized failure behavior.
- **R2:** Validate one guarded real `demographics_only` run through the same
  authenticated session with no second login/process/browser.
- **R3:** Validate real full-sync with at least one bounded chunk; if an approved
  case spans multiple chunks/admissions, verify ordering and association without
  recording identifiers/content.
- **R4:** Validate direct or `#printLinks` PDF path actually observed, timeout
  propagation, in-memory handling, normalization, and persistence counts.
- **R5:** Validate repeated heterogeneous jobs reuse one login/session and leave
  root-only safe tab state after each job.
- **R6:** Trigger or safely simulate one lifecycle restart and prove rebootstrap
  before the next claim.
- **R7:** Observe renewal/popup behavior at a safe checkpoint or retain rollout
  blocker if it cannot be exercised.
- **R8:** Compare sanitized success/failure rates, durations, attempts, queue
  latency, temp/profile size, RAM, shared memory, swap, and log growth with the
  current worker.
- **R9:** Reconcile thresholds, headless mode, resource bounds, selectors,
  proposal, design, specs, tasks, deploy/rollout docs, and unresolved risks.
- **R10:** Declare replacement-ready only if all automated/live evidence passes,
  rollback is rehearsed, and no blocker remains. Otherwise keep the current
  worker and document the blocker.

## Expected Scope

Target maximum after successful validation: 6 versioned documentation/config
files including `tasks.md`. Production code changes are forbidden in this slice.
If live validation finds a code defect, stop and propose a new focused slice.

Allowed after success: proposal/design/spec/task reconciliation, rollout/deploy
guidance, conservative config examples/default documentation. Do not enable or
scale a production service automatically.

## Validation Procedure

Before live execution, write sanitized commands with placeholders in the report.
Use only explicit `--run-id` and bounded run count. Do not paste credentials or
real IDs into the report or shell history captured there.

Required sequence:

```text
preflight and zero persistent scale
-> guarded admissions
-> same-session demographics
-> bounded full-sync
-> another job on same session
-> controlled restart/rebootstrap
-> resource/observability comparison
-> rollback rehearsal
```

A missing or failed step means incomplete; do not reinterpret it as optional.

## Mandatory Inspection Checks

```bash
rg -n "NOT production|not rollout|blocked|replacement|cutover|rollback" \
  openspec/changes/add-persistent-session-ingestion-worker \
  docs/operations/persistent-worker-rollout.md deploy/README.md
rg -n "scale worker=|scale persistent|concurr|simult" \
  docs/architecture.md docs/adr deploy docs/operations
rg -n "SOURCE_SYSTEM_(USERNAME|PASSWORD)|patient_record.*[0-9]" \
  openspec/changes/add-persistent-session-ingestion-worker \
  docs/operations deploy
```

Interpret placeholders separately. Any real credential or identifier is an
immediate incomplete/security failure.

## Binary Success Criteria

- [ ] Preconditions are documented without secrets.
- [ ] Admissions, demographics, full-sync, reuse, cleanup, and rebootstrap pass.
- [ ] Renewal/popup behavior is validated or rollout remains blocked.
- [ ] No subprocess/new login/browser occurs per job.
- [ ] Resource limits and thresholds are evidence-based.
- [ ] Rollback is rehearsed successfully.
- [ ] Docs contain one consistent readiness status.
- [ ] No sensitive artifact exists in Git/report.
- [ ] Every official gate passes after documentation reconciliation.

## Self-Evaluation Gates

1. Was any criterion inferred rather than observed?
2. Was any real identifier, clinical text, artifact, or secret captured?
3. Did live validation require a production-code fix in this slice?
4. Was approved concurrency exceeded?
5. Can replacement be rolled back using the documented command?
6. Do all artifacts agree on readiness status?

Required answers for COMPLETE: no, no, no, no, yes, yes.

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

Create `/tmp/sirhosp-slice-PSW-S24-report.md` with `Status: COMPLETE` or
`INCOMPLETE/BLOCKED`, preconditions, sanitized evidence matrix, command exit
codes without secrets/IDs, observed lifecycle/resource results, rollback proof,
remaining blockers, changed files, and verifier handoff.

Final prompt: implement only PSW-S24. Without authorized live access and every
observed criterion, produce only a blocked temporary report; do not modify
versioned files, tasks, rollout status, commit, or push.
