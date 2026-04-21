# containerized-runtime Specification

## ADDED Requirements

### Requirement: Containerized development stack

The system SHALL provide a compose-based development stack that starts database and Django web services with host browser access.

#### Scenario: Start dev stack and access health endpoint

- **WHEN** an operator runs the documented dev compose command
- **THEN** PostgreSQL and web services start successfully
- **AND** `/health/` is reachable from the host browser

### Requirement: Containerized worker execution

The system SHALL provide a worker service in the dev stack able to process queued ingestion runs.

#### Scenario: Process queued ingestion run in dev stack

- **WHEN** an authenticated user creates an ingestion run in the web UI
- **THEN** the worker service processes the queued run
- **AND** the run transitions to a terminal status (`succeeded` or `failed`)

### Requirement: Local deploy mode separate from dev

The system MUST provide a production-oriented compose mode distinct from development mode.

#### Scenario: Start local deploy mode

- **WHEN** an operator runs the documented prod compose command
- **THEN** the web service starts using a production web server configuration
- **AND** service health remains reachable through the host

### Requirement: Rootless-compatible defaults

The compose setup SHOULD run with rootless container engines without privileged requirements.

#### Scenario: Run compose without privileged flags

- **WHEN** the stack is started in a rootless environment
- **THEN** it does not require privileged mode or host networking
- **AND** persistent data is stored in named volumes
