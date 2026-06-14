# Fix Quality Gate Debt

## Why

The historical extraction refactor is ready for archive, but a few pre-existing
quality-gate failures still obscure whether new changes are clean. Fixing these
now restores reliable validation before archiving the completed extraction
sequence.

## What Changes

- Fix the stale inpatient report regression test or the command behavior it
  exposes.
- Fix the remaining lint failures in the services portal URL/tests area.
- Fix the mypy duplicate-module issue around services portal sector tests so
  type checking can validate the suite again.
- Add focused regression coverage only where needed to preserve the intended
  behavior.
- Do not change historical extraction behavior, recovery orchestration, or
  production scheduling.

## Capabilities

### New Capabilities

- `quality-gate-health`: Repository quality gates remain actionable and free of
  known unrelated failures.

### Modified Capabilities

- None.

## Impact

- Affected code is expected to be limited to tests, lint-only formatting, and
  possibly the stale inpatient report command if the failing test exposes a real
  behavior mismatch.
- No database migrations, Celery/Redis, Playwright automation changes, or
  extraction-service changes are expected.
- Validation impact: `check`, `unit`, `lint`, `typecheck`, OpenSpec validation,
  and markdown lint for changed Markdown files.
