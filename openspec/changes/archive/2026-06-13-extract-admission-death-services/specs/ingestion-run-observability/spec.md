# Ingestion Run Observability Delta Specification

## ADDED Requirements

### Requirement: Historical extraction services preserve ingestion run observability

Admission and death historical extraction service executions SHALL persist
`IngestionRun` lifecycle status and per-stage metrics equivalent to the existing
management command behavior.

#### Scenario: Successful admission service execution records lifecycle and stages

- **WHEN** admission extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying admission
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Successful death service execution records lifecycle and stages

- **WHEN** death extraction is executed through the service layer and succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying death
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Failed service execution records normalized failure metadata

- **WHEN** admission or death extraction fails through the service layer
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run persists a safe error message
- **AND** the run persists the normalized failure reason when it can be
  classified
- **AND** the failed stage metric includes safe diagnostic context without
  credentials

#### Scenario: Timeout service execution records timeout metadata

- **WHEN** admission or death extraction times out during source-system
  automation
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run failure reason is `timeout`
- **AND** the run timeout flag is set
