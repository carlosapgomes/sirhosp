# developer-quality-gates Specification

## ADDED Requirements

### Requirement: Official quality gates run in containerized test suite

Project quality gate execution MUST run through a containerized orchestration flow that provisions required dependencies and tears them down automatically.

#### Scenario: Execute unit quality gate without manual DB management

- **WHEN** the executor runs the official test command
- **THEN** the system automatically starts required services (including PostgreSQL), waits for readiness, runs tests, and performs teardown

#### Scenario: Deterministic environment for local and CI

- **WHEN** quality gates are executed locally or in CI
- **THEN** both environments use the same containerized test entrypoint
- **AND** behavior does not depend on host-specific DB hostname resolution

### Requirement: Documentation defines a single official testing path

Project documentation MUST declare one official path for quality gate execution and classify host-only alternatives as non-official diagnostics.

#### Scenario: Developer follows AGENTS/README commands

- **WHEN** a developer or LLM follows documented quality gate commands
- **THEN** commands invoke the containerized entrypoint
- **AND** do not require manual database container lifecycle management
