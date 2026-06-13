# Ingestion Run Observability Delta Specification

## ADDED Requirements

### Requirement: Census and discharge extraction services preserve observability

Official census and discharge historical extraction service executions SHALL
persist `IngestionRun` lifecycle status and per-stage metrics equivalent to the
existing management command behavior.

#### Scenario: Successful official census service execution records lifecycle

- **WHEN** official census extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying official
  census extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Successful discharge service execution records lifecycle

- **WHEN** discharge extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying discharge
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Failed census or discharge service records failure metadata

- **WHEN** official census or discharge extraction fails through the service
  layer after an `IngestionRun` has been created
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run persists a safe error message
- **AND** the run persists the normalized failure reason when it can be
  classified
- **AND** the failed stage metric includes safe diagnostic context without
  credentials

#### Scenario: Timeout service execution records timeout metadata

- **WHEN** official census or discharge extraction times out during
  source-system automation
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run failure reason is `timeout`
- **AND** the run timeout flag is set
- **AND** the failed stage metric does not expose credential values or
  command-line credential flags

#### Scenario: Unexpected outer failure does not leave a running ingestion run

- **WHEN** official census or discharge extraction encounters an unexpected
  exception after creating an `IngestionRun`
- **THEN** the service marks the linked run as `failed`
- **AND** the service returns a structured failed extraction result with the
  linked ingestion run id
