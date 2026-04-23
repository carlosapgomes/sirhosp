# patient-admission-mirror Specification

## MODIFIED Requirements

### Requirement: Admission mirror linked to patient

The system SHALL maintain admissions linked to patients using a stable external admission identifier.

#### Scenario: Create admission with external key

- **WHEN** an ingestion run receives an admission that does not exist by `(source_system, source_admission_key)`
- **THEN** the system creates a new admission linked to the resolved patient

#### Scenario: Reconcile admission for repeated ingestion

- **WHEN** an ingestion run receives an admission that already exists by `(source_system, source_admission_key)`
- **THEN** the system reuses the existing admission and updates known mutable metadata without duplication

#### Scenario: Persist known admissions independently from extracted evolutions

- **WHEN** the source connector provides the patient admissions snapshot for a run
- **THEN** the system upserts known admissions even if no evolutions were extracted in the requested window
- **AND** admissions without extracted events remain visible in patient admission listings

#### Scenario: Do not overwrite ward and bed with empty values

- **WHEN** an admission snapshot omits `ward`/`bed` for past admissions
- **THEN** existing non-empty `ward`/`bed` values are preserved
- **AND** empty snapshot values do not overwrite persisted data
