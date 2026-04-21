# containerized-runtime Specification

## MODIFIED Requirements

### Requirement: Containerized worker execution

The worker service SHALL support continuous polling mode for PostgreSQL-backed queued runs without container flapping when idle.

#### Scenario: Worker stays up when queue is empty

- **WHEN** the worker runs in continuous mode and there are no `queued` runs
- **THEN** the worker remains running
- **AND** it sleeps for the configured interval before polling again

#### Scenario: Worker processes queued run in continuous mode

- **WHEN** a new `IngestionRun` is created with status `queued`
- **THEN** the worker picks it up on the next poll
- **AND** transitions the run to a terminal state (`succeeded` or `failed`)
