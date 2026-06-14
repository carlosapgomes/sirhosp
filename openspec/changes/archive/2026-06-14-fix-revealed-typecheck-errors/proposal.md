# Fix Revealed Typecheck Errors

## Why

After the duplicate-module mypy issue was fixed, the typecheck gate now reaches
project code and reveals four pre-existing type errors. Fixing them restores the
value of the official typecheck gate before archiving the historical extraction
refactor sequence.

## What Changes

- Fix the two tuple type errors in discharge extraction/persistence unit tests.
- Fix the two services portal view type errors around incompatible assignment
  and unary negation on an imprecisely typed value.
- Add narrow typing helpers or annotations only where needed.
- Preserve runtime behavior and existing assertions unless a type error exposes
  an actual bug.
- Do not change historical extraction, recovery orchestration, or scheduling
  behavior.

## Capabilities

### New Capabilities

- `typecheck-health`: The official typecheck gate completes without the newly
  revealed mypy errors.

### Modified Capabilities

- None.

## Impact

- Expected files:
  - `tests/unit/test_discharge_persistence_hardening.py`
  - `tests/unit/test_discharge_extraction_service.py`
  - `apps/services_portal/views.py`
- No database migrations, Playwright changes, Celery/Redis, or extraction
  orchestration changes are expected.
- Validation impact: official typecheck gate, focused ruff/tests for changed
  files, OpenSpec validation, and markdown lint for changed Markdown files.
