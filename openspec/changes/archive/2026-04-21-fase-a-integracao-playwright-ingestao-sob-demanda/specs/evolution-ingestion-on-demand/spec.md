
# MODIFIED Specification: evolution-ingestion-on-demand

## Requirements

### Requirement: Asynchronous on-demand ingestion run

The system SHALL execute on-demand ingestion requests through an asynchronous run lifecycle tracked in `IngestionRun`.

#### Scenario: Queue and process on-demand request

- **WHEN** an authenticated user requests ingestion for a patient and period
- **THEN** the system creates an `IngestionRun` in `queued` state and processes it asynchronously to a terminal state (`succeeded` or `failed`)

### Requirement: Cache-first on-demand policy

The system MUST prioritize already ingested data and trigger extraction only for missing temporal coverage.

#### Scenario: Reuse existing coverage

- **WHEN** requested patient/period is fully covered by existing canonical events
- **THEN** the run completes without external extraction and returns coverage metadata

#### Scenario: Extract only missing windows

- **WHEN** requested patient/period is partially covered
- **THEN** the run extracts only missing windows and ingests new events idempotently

### Requirement: Operational status visibility

The system SHALL provide minimal operational status for an on-demand run.

#### Scenario: Check run status after request

- **WHEN** a client queries a previously created run
- **THEN** the system returns run status, timestamps, and summary counters for processed/new/duplicate events
