# SLICE PSW-S18: Internal Legacy-Tab Cleanup and Recovery

## Handoff for a Context-Zero Implementer

Implement only PSW-S18 after PSW-S17 is committed. Read project instructions,
all change artifacts, the PSW-S17 report, session policy/controller/handle,
real bridge, adapter cleanup, known legacy tab selectors, and their tests.
Start from a clean tree.

Key distinction: a PrimeFaces legacy tab is a DOM element inside one Playwright
Page. It is not a `BrowserContext.pages` entry.

## Mandatory Protocol for the Implementing LLM

1. Record `BASE_REF`, branch, clean status, and report matrix.
2. Run official unit baseline before editing; record exit and summary.
3. Write tests first and capture a behavioral RED reproducing two DOM tabs in
   one Playwright Page.
4. Implement minimum GREEN.
5. Run inspections and explain DOM-tab versus Page operations.
6. Run every official gate.
7. Mark tasks/report/commit/push only when complete; otherwise report incomplete.

## Inherited Contracts — Frozen and Not Reopened

PSW-S17 is a frozen prerequisite. Preserve its normalized failure taxonomy,
observable-surface sanitization, accepted `raise ... from None` semantics,
cooperative deadline, and current/persistent lifecycle parity. This slice does
not re-audit or re-prove those contracts.

Sanitization is checked only on persisted fields, logs, command output,
`CommandError`, and rendered tracebacks. A suppressed internal `__context__`
is not a failure unless application code re-emits it. Deadline means bounded
timeout-capable calls plus boundary checks, not mid-call interruption.

If implementation exposes a non-critical defect in an inherited contract,
record a separate focused remediation and keep it out of PSW-S18. Only data
loss, observable secret leakage, database corruption, authentication bypass,
or a defect that blocks an explicit PSW-S18 requirement may block this slice.

## Acceptance Freeze and Artifact Policy

The requirements and binary criteria below are frozen before RED. Prove only
the enumerated scenarios and observable outcomes. Do not add private call
order, internal exception references, or unrelated intent behavior as new
acceptance criteria.

Update active requirements in place. Do not append D-numbered corrective
appendices; git history preserves old wording. The report needs real
Before/After fragments only for files changed in this execution pass.

## Objective

Close only the last non-root legacy DOM tab, verify cleanup, and preserve a
failure signal that forces recovery before another claim when cleanup is unsafe.

## Cleanup Outcome Boundary

Cleanup has exactly three observable outcomes; representation may be an enum,
typed result, or equivalent explicit contract:

- `ROOT_ONLY`: no non-root DOM tab exists; no click occurs;
- `CLOSED_AND_VERIFIED`: one non-root tab was closed and the safe state was
  observed;
- `UNSAFE`: close could not be performed or verified; recovery is required
  before the next claim.

Only these outcomes, controller state, next-claim behavior, DOM tab count, and
browser Page liveness are acceptance surfaces.

## Requirements

- **R1:** Characterize root-only, multiple DOM-tab, missing-close-control,
  click-failure, no-count-decrease, and ambiguous states using the three
  cleanup outcomes above.
- **R2:** Implement concrete close through
  `li.tabs-last:not(.tabs-first) a.tabs-close` or the centralized equivalent on
  the active page.
- **R3:** Never close a Playwright Page as a substitute for closing a legacy
  DOM tab.
- **R4:** After click, wait for tab count to decrease or root-only state to be
  restored within a bounded timeout.
- **R5:** Preserve root and never classify close as session renewal.
- **R6:** `UNSAFE` increments/preserves controller failure state and makes
  recovery/restart required before the next claim.
- **R7:** `mark_job_processed` must not erase an unsafe-cleanup failure.
- **R8:** Apply cleanup after success and recoverable extraction failures for
  exactly `admissions_only`, `demographics_only`, `full_sync`, and
  `full_admission_sync`.
- **R9:** Apply inherited PSW-S17 observable-surface sanitization to cleanup
  errors; do not re-audit internal exception objects.

## Expected Scope

Target maximum: 8 versioned files including `tasks.md`.

Expected: session policy, controller, concrete handle/bridge, adapter/command
only where orchestration must react, focused tests, and `tasks.md`.

Forbidden: models/migrations, extraction parsing, persistence rules, restart
bootstrap implementation (PSW-S19), PDF/chunk changes, UI templates.

## TDD

### RED

Mandatory reproduction:

```text
one Playwright Page
+ two legacy li tab elements
-> cleanup clicks the DOM close control
-> browser Page remains open
-> DOM tab count decreases
```

Also add a test where cleanup cannot verify safety and prove the next claim is
blocked by recovery state. Initial RED must expose the existing no-op/Page-close
mismatch or failure-counter reset.

### GREEN

Correct the concrete SessionHandle contract and controller result handling with
small explicit return values or typed errors.

### REFACTOR

Keep selector policy centralized. Delete obsolete Page-closing behavior if it
has no valid caller; do not leave aliases or dual semantics.

## Mandatory Inspection Checks

```bash
rg -n "close_last_non_root_tab|tabs-last|tabs-close|context.pages|\.close\(" \
  apps/ingestion/extractors
rg -n "mark_job_processed|consecutive_failures|restart_required" \
  apps/ingestion/extractors apps/ingestion/management/commands
```

Inspect `.close()` only in changed files and the direct cleanup call graph.
Classify each matched call as browser, context, Page, or DOM-related and
justify it. Do not audit unrelated ingestion subsystems.

## Binary Success Criteria

- [ ] One-Page/multiple-DOM-tab reproduction passes.
- [ ] Root is never closed.
- [ ] Count/root restoration is verified after a click.
- [ ] Failed verification survives job accounting.
- [ ] No next claim occurs before recovery.
- [ ] Close never changes renewal evidence.
- [ ] Success and recoverable failures for the four enumerated intents clean up.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Does cleanup ever use `context.pages[-1].close()` for a legacy tab?
2. Can cleanup report success without observing a changed safe state?
3. Can `mark_job_processed` zero a cleanup failure?
4. Can root-only state trigger a click?
5. Are timeouts bounded and sanitized?

Required answers: no, no, no, no, yes.

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

Create `/tmp/sirhosp-slice-PSW-S18-report.md` with protocol evidence, state
transition table, RED/GREEN, snippets, inspections, commands/exit codes, files,
risks, and verifier handoff.
Include real Before/After fragments only for files changed in this pass. Do not
reconstruct the history of PSW-S17 or inherited contracts.

Final prompt: implement only PSW-S18. A DOM/Page semantic mismatch, unverified
close, erased failure, or missing gate means incomplete; do not update tasks or
commit.
