# ingestion-run-observability Specification Delta

## ADDED Requirements

### Requirement: Orchestrator logs safe operational state

Ingestion run observability SHALL support safe operator understanding of the
adaptive census orchestrator state without exposing patient data or credentials.

#### Scenario: Orchestrator waits for active queue

- **WHEN** the adaptive census orchestrator checks the queue
- **AND** active `IngestionRun` records prevent a new cycle
- **THEN** operator output includes a safe waiting reason
- **AND** it includes aggregate counts by active status when available
- **AND** it does not include patient names, clinical text, or credentials

#### Scenario: Orchestrator starts a cycle

- **WHEN** the adaptive census orchestrator starts a new census cycle
- **THEN** operator output identifies the lifecycle transition as a cycle start
- **AND** it includes non-sensitive identifiers such as run id or batch id when
  those identifiers become available

#### Scenario: Orchestrator detects stale active runs

- **WHEN** the adaptive census orchestrator detects active runs older than the
  configured stale threshold
- **THEN** operator output includes a stale-run warning
- **AND** it includes only safe operational identifiers and timestamps
- **AND** it does not mutate the stale runs
