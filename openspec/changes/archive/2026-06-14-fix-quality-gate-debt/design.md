# Fix Quality Gate Debt Design

## Context

Change 3 finished with the new historical recovery command implemented, but the
project still has known pre-existing validation failures. Those failures make it
harder to prove that future OpenSpec slices are clean because full `unit`,
`lint`, and `typecheck` gates report noise unrelated to the active work.

The known debt is narrow:

- one stale inpatient report unit test fails;
- lint reports one long URL route line and two unused variables;
- mypy stops early because of duplicate module resolution around services portal
  sector tests.

## Goals / Non-Goals

**Goals:**

- Restore actionable unit, lint, and typecheck gates for the current codebase.
- Keep fixes small, deterministic, and scoped to the failing debt.
- Preserve intended clinical/reporting behavior with regression tests.
- Produce a short implementation report suitable for handoff before archiving
  the historical extraction changes.

**Non-Goals:**

- Do not change historical recovery command behavior.
- Do not alter Playwright automation, extraction services, or scheduling.
- Do not introduce persistent jobs, migrations, Celery, Redis, or new infra.
- Do not perform broad formatting or opportunistic refactors.

## Decisions

### Decision: Use one focused cleanup change

The debt spans tests, lint, and typecheck, but all items share the same outcome:
restoring trustworthy quality gates. A single focused change is simpler than
three tiny changes and avoids delaying archive readiness with repeated setup.

Alternative considered: fix each failure under separate OpenSpec changes. That
would be traceable but more overhead than the risk warrants.

### Decision: Treat the stale inpatient failure as behavior-first

The implementer MUST first reproduce the failing test and inspect the
`report_suspected_stale_inpatients` command. If the command is wrong, fix the
command; if the test expectation is stale, update the test with an explicit
reason. Do not blindly weaken assertions.

Alternative considered: mark or skip the failing test. This is rejected because
it would hide a clinical reporting regression.

### Decision: Fix typecheck root cause, not by excluding files

The duplicate-module issue SHOULD be resolved by aligning package/module layout
or mypy discovery inputs. Do not suppress mypy wholesale or exclude the affected
test unless a precise, justified configuration fix is documented.

Alternative considered: add a broad mypy ignore. This is rejected because it
would reduce future validation value.

## Risks / Trade-offs

- Misclassifying the stale inpatient test could change clinical report semantics
  unintentionally. Mitigation: add or preserve focused tests for active versus
  discharged/latest-admission cases.
- Fixing mypy discovery can have repo-wide effects. Mitigation: prefer minimal
  package marker or configuration changes and run the official typecheck gate.
- Full markdown lint may include unrelated legacy/archive noise. Mitigation:
  run focused markdownlint for changed Markdown files and document any full-run
  noise exactly.
