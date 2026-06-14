# Typecheck Health Spec

## ADDED Requirements

### Requirement: Typecheck Gate Passes Revealed Errors

The repository SHALL resolve the mypy errors revealed after duplicate-module
checking was fixed.

#### Scenario: Official typecheck succeeds

- **WHEN** `./scripts/test-in-container.sh typecheck` runs after this change
- **THEN** it exits successfully without the four known revealed errors

### Requirement: Type Fixes Preserve Runtime Behavior

The type fixes SHALL preserve existing runtime behavior and test assertions for
discharge tests and services portal views.

#### Scenario: Discharge tests keep their assertions

- **WHEN** discharge unit tests affected by type fixes run
- **THEN** they continue to assert the same extraction and persistence behavior

#### Scenario: Services portal views keep data shape

- **WHEN** focused tests covering the touched services portal view behavior run
- **THEN** they continue to pass without template or route behavior changes

### Requirement: No Broad Type Suppression

The implementation SHALL avoid broad typecheck suppression as the mechanism for
passing the gate.

#### Scenario: No blanket suppression is added

- **WHEN** the implementation diff is reviewed
- **THEN** it does not add broad mypy excludes, blanket ignores, or unrelated
  `# type: ignore` comments
