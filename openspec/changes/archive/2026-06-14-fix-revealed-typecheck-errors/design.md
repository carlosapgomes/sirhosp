# Fix Revealed Typecheck Errors Design

## Context

The `fix-quality-gate-debt` change fixed mypy duplicate-module discovery. As a
result, mypy now checks the suite and reveals four older type errors:

- tuple type mismatches in discharge-related unit tests;
- an incompatible assignment in `apps/services_portal/views.py`;
- unary `-` applied to a value inferred as `object` in the same view module.

These errors are not part of the historical recovery implementation, but they
keep the official typecheck gate from reaching a clean state.

## Goals / Non-Goals

**Goals:**

- Make `./scripts/test-in-container.sh typecheck` pass without newly revealed
  mypy errors.
- Keep changes narrow and type-focused.
- Preserve existing runtime behavior and test assertions unless a type issue
  identifies a real bug.
- Document any remaining non-typecheck caveats separately.

**Non-Goals:**

- Do not address pre-existing integration-test failures in this change.
- Do not modify historical recovery or extraction orchestration behavior.
- Do not change database schema, scheduling, Playwright automation, or
  infrastructure.
- Do not introduce broad mypy suppressions, blanket casts, or excludes.

## Decisions

### Decision: Prefer precise annotations over suppression

The implementer SHOULD fix inferred `object` or heterogeneous tuple issues by
adding precise type annotations, small typed structures, or local conversions.
Use `cast()` only if the value has already been validated and no cleaner type
narrowing is practical.

Alternative considered: add `# type: ignore`. This is rejected unless the report
justifies a narrow false positive that cannot be resolved cleanly.

### Decision: Keep tests behaviorally identical

The discharge unit-test fixes SHOULD preserve test intent and assertions. If the
problem is a heterogeneous fixture tuple, prefer a named dataclass, typed helper,
or explicit variable annotations over changing what the test verifies.

Alternative considered: loosen assertions to satisfy mypy. This is rejected.

### Decision: Isolate services portal typing fixes

The view fixes SHOULD be local to the affected computations around lines 2072
and 2108 reported by mypy. Avoid broad view rewrites or template behavior
changes.

Alternative considered: refactor the whole view function. This is too risky for
this cleanup.

## Risks / Trade-offs

- A type-only edit in views could still affect runtime output. Mitigation: run
  focused tests around services portal views if available and preserve existing
  data shapes.
- Heterogeneous test fixtures may be easier to silence than type correctly.
  Mitigation: prefer explicit typed structures and keep assertions unchanged.
- Integration tests are known to have unrelated failures. Mitigation: document
  them if encountered, but do not expand this change to fix them.
