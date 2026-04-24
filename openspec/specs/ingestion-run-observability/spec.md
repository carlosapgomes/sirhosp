# ingestion-run-observability Specification

## Purpose

Define visibility requirements for ingestion run lifecycle and operational metrics.

## Requirements

### Requirement: Run metrics include admissions-stage visibility

Ingestion run tracking MUST expose admissions-stage metrics in addition to event counters.

#### Scenario: Persist admissions metrics on completed run

- **WHEN** a run processes admissions snapshot and evolution extraction stages
- **THEN** the run persists admissions metrics (`admissions_seen`, `admissions_created`, `admissions_updated`)

#### Scenario: Show admissions metrics on status page

- **WHEN** user opens run status page
- **THEN** admissions metrics are displayed with event metrics for operational traceability

### Requirement: Run intent and admission context are observable

Ingestion run tracking MUST expose operational intent metadata for admission-first workflows.

#### Scenario: Persist run intent metadata

- **WHEN** a run is created for admission sync, full-admission sync, or custom-period sync
- **THEN** run metadata persists the intent type and relevant context (registro, admission identifier, effective date range)
- **AND** status view renders this metadata for operator traceability

### Requirement: Status guidance reflects admission-first next step

Run status UI SHALL provide explicit guidance according to admissions synchronization outcome.

#### Scenario: Admissions sync finished with admissions available

- **WHEN** admissions sync run succeeds with one or more admissions
- **THEN** status page shows action to proceed to admission selection

#### Scenario: Admissions sync finished with zero admissions

- **WHEN** admissions sync run finishes with zero admissions found
- **THEN** status page shows explicit message that extraction is unavailable without admission
- **AND** no action to start evolution extraction is shown
