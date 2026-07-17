# SLICE PSW-S18: Internal Legacy-Tab Cleanup and Recovery

## Handoff for a Context-Zero Implementer

Implement only PSW-S18 after PSW-S17 is committed. Read project instructions,
all change artifacts, the PSW-S17 report, session policy/controller/handle,
real bridge, adapter cleanup, known legacy tab selectors, and their tests.
Start from a clean tree.

Key distinction: a PrimeFaces legacy tab is a DOM element inside one Playwright
Page. It is not a `BrowserContext.pages` entry.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, branch, clean status, and report matrix.
2. Run official unit baseline before editing; record exit and summary.
3. Write tests first and capture a behavioral RED reproducing two DOM tabs in
   one Playwright Page.
4. Implement minimum GREEN.
5. Run inspections and explain DOM-tab versus Page operations.
6. Run every official gate.
7. Mark tasks/report/commit/push only when complete; otherwise report incomplete.

## Objective

Close only the last non-root legacy DOM tab, verify cleanup, and preserve a
failure signal that forces recovery before another claim when cleanup is unsafe.

## Requirements

- **R1:** Characterize root-only, multiple DOM-tab, missing-close-control,
  click-failure, no-count-decrease, and ambiguous states.
- **R2:** Implement concrete close through
  `li.tabs-last:not(.tabs-first) a.tabs-close` or the centralized equivalent on
  the active page.
- **R3:** Never close a Playwright Page as a substitute for closing a legacy DOM
  tab.
- **R4:** After click, wait for tab count to decrease or root-only state to be
  restored within a bounded timeout.
- **R5:** Preserve root and never classify close as session renewal.
- **R6:** Unsafe cleanup increments/preserves controller failure state and makes
  recovery/restart required before the next claim.
- **R7:** `mark_job_processed` must not erase an unsafe-cleanup failure.
- **R8:** Apply cleanup after success and recoverable extraction failures for all
  supported intents.
- **R9:** Keep cleanup errors sanitized and free of DOM/clinical payloads.

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

The report must identify every `.close()` as browser, context, or DOM-related
and justify it.

## Binary Success Criteria

- [ ] One-Page/multiple-DOM-tab reproduction passes.
- [ ] Root is never closed.
- [ ] Count/root restoration is verified after a click.
- [ ] Failed verification survives job accounting.
- [ ] No next claim occurs before recovery.
- [ ] Close never changes renewal evidence.
- [ ] Success and recoverable failures for supported intents clean up.
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
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S18-report.md` with protocol evidence, state
transition table, RED/GREEN, snippets, inspections, commands/exit codes, files,
risks, and verifier handoff.

Final prompt: implement only PSW-S18. A DOM/Page semantic mismatch, unverified
close, erased failure, or missing gate means incomplete; do not update tasks or
commit.
