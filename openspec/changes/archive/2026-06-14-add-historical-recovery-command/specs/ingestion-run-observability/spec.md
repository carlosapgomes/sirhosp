# Ingestion Run Observability Delta Specification

## ADDED Requirements

### Requirement: Historical recovery relies on extractor run observability

The historical recovery command SHALL rely on the per-extractor `IngestionRun`
records created by extractor services and SHALL NOT introduce persistent recovery
job state in this change.

#### Scenario: Successful recovery step exposes extractor ingestion run id

- **WHEN** a recovery step calls an extractor service and the service returns an
  `ExtractionResult` with an `ingestion_run_id`
- **THEN** the command-level step result retains that ingestion run id through
  the service result
- **AND** operators can inspect the corresponding extractor `IngestionRun` for
  detailed lifecycle and stage metrics

#### Scenario: Failed recovery step exposes extractor failure metadata

- **WHEN** a recovery step calls an extractor service and the service returns a
  failed `ExtractionResult`
- **THEN** the command-level step result retains the service failure reason,
  safe error message, and ingestion run id when present
- **AND** the command summary reports the step as failed

#### Scenario: Dry-run does not create ingestion runs

- **WHEN** recovery is executed with `--dry-run`
- **THEN** no extractor service is called
- **AND** no extractor `IngestionRun` is created by recovery planning

#### Scenario: No recovery job model is created

- **WHEN** this change is implemented
- **THEN** the system does not add a recovery job table, recovery attempt table,
  or migration for persistent recovery orchestration
- **AND** any future persistent recovery job state remains a separate OpenSpec
  change
