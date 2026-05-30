# ingestion-run-observability Specification

## MODIFIED Requirements

### Requirement: Worker identity is recorded when processing runs

Ingestion run tracking MUST record an operational worker label for runs
processed by the asynchronous ingestion worker.

#### Scenario: Worker claims a queued run

- **WHEN** `process_ingestion_runs` claims a queued `IngestionRun`
- **THEN** the run status is changed to `running`
- **AND** `worker_label` is populated with a non-empty operational identifier
- **AND** the identifier contains no patient data or sensitive credential

#### Scenario: Worker label environment override is available

- **WHEN** the environment variable `SIRHOSP_WORKER_LABEL` is configured
- **AND** `process_ingestion_runs` claims a queued run
- **THEN** the persisted `worker_label` is derived from that configured value
- **AND** a safe process-level suffix may be appended to avoid ambiguity

#### Scenario: Worker label fallback is available

- **WHEN** no explicit worker label environment variable is configured
- **AND** `process_ingestion_runs` claims a queued run
- **THEN** the system uses a safe fallback based on host/process information
- **AND** the run remains processable even if hostname resolution is limited
