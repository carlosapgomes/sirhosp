# quality-gate-health Specification

## Purpose

Define repository quality-gate health requirements for unit, lint, typecheck,
and cleanup scope.

## Requirements

### Requirement: Unit Gate Has No Known Debt Failures

The repository SHALL not retain known pre-existing unit-test failures that mask
new regressions.

#### Scenario: Stale inpatient report test is actionable

- **WHEN** the unit test gate runs after this change
- **THEN** the stale inpatient report test passes or fails only for a new,
  unrelated regression

### Requirement: Lint Gate Has No Known Debt Failures

The repository SHALL not retain known lint failures in the services portal URL
or ingestion metrics test files.

#### Scenario: Services portal lint debt is resolved

- **WHEN** the lint gate runs after this change
- **THEN** it does not report the known long line in
  `apps/services_portal/urls.py`
- **AND** it does not report the known unused variables in ingestion metrics or
  stale inpatient tests

### Requirement: Typecheck Gate Reaches Project Code

The repository SHALL not stop type checking because of the known duplicate
module issue around services portal sector tests.

#### Scenario: Duplicate module issue is resolved

- **WHEN** the typecheck gate runs after this change
- **THEN** it does not stop with a duplicate-module error for
  `test_services_portal_sectors.py`

### Requirement: Cleanup Scope Remains Narrow

The cleanup SHALL avoid behavioral, infrastructure, or schema changes unrelated
to restoring the quality gates.

#### Scenario: No unrelated architecture changes

- **WHEN** the implementation diff is reviewed
- **THEN** it contains no migrations, Celery or Redis setup, Playwright script
  changes, or historical recovery behavior changes
