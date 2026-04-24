# ingestion-run-observability Specification

## ADDED Requirements

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
