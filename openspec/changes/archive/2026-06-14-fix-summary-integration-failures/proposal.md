# Fix Summary Integration Failures

## Why

The official unit, lint, and typecheck gates are now clean, but the integration
gate still has ten pre-existing failures in summary HTTP coverage. Fixing these
restores confidence that the summary status/read pages preserve cost visibility
and admission context after the recent pipeline and UI changes.

## What Changes

- Diagnose the ten failing integration tests in:
  - `tests/integration/test_summary_cost_visibility_http.py`
  - `tests/integration/test_summary_http.py`
- Fix production code when the tests expose a regression in operator-visible
  summary pages.
- Update test fixtures only when they are stale relative to the current spec,
  especially where pipeline runs are now linked to `SummaryRun` explicitly.
- Preserve cost display in USD and BRL, phase-1 reuse indicators, and admission
  reference visibility on summary pages.
- Do not change historical extraction, recovery orchestration, or quality-gate
  cleanup behavior.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `summary-llm-traceability`: Clarify integration expectations for linked
  pipeline cost visibility and admission context on summary status/read pages.

## Impact

- Expected files include summary views/templates and the two failing integration
  test files.
- No database migrations, Playwright changes, Celery/Redis, extraction services,
  or historical recovery command changes are expected.
- Validation impact: focused integration tests, official integration gate,
  quality-gate checks as needed, OpenSpec validation, and markdown lint for
  changed Markdown files.
