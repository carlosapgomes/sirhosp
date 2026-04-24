# patient-admission-mirror Specification

## Purpose

TBD - created by archiving change fundacao-modelo-eventos-e-ingestao-evolucoes. Update Purpose after archive.
## Requirements
### Requirement: Patient mirror with external identity

The system SHALL maintain a read-only mirror of patient demographic data with an external source identifier and safe upsert behavior.

#### Scenario: Create patient from source data

- **WHEN** an ingestion run receives a patient that does not exist by `(source_system, patient_source_key)`
- **THEN** the system creates a new patient record with basic demographic fields and source identifiers

#### Scenario: Update patient from source data

- **WHEN** an ingestion run receives a patient that already exists by `(source_system, patient_source_key)`
- **THEN** the system updates mutable demographic fields without creating duplicate patient records

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

### Requirement: Defensive reconciliation metadata

The system MUST persist reconciliation-support fields for admissions and patients to tolerate future source key instability.

#### Scenario: Persist reconciliation support data

- **WHEN** patient and admission data are ingested
- **THEN** the system stores additional reference metadata (such as admission period and source patient reference) required for controlled reconciliation

### Requirement: Admissions catalog sync is a first-class operation

The system SHALL support admissions catalog synchronization as a standalone operation before evolution extraction.

#### Scenario: Synchronize admissions for missing local patient

- **WHEN** admissions sync is triggered for a registro absent in local mirror
- **THEN** the system upserts all admissions returned by source snapshot
- **AND** admissions become immediately available in patient admission listing

#### Scenario: Reconcile admissions for existing local patient

- **WHEN** admissions sync is triggered for a registro already present in local mirror
- **THEN** existing admissions are reconciled by `(source_system, source_admission_key)`
- **AND** no duplicate admissions are created

### Requirement: Empty admission snapshot does not create extraction candidates

The mirror layer MUST preserve the invariant that evolutions require at least one known admission.

#### Scenario: Empty snapshot on admissions sync

- **WHEN** source admissions snapshot is empty for the requested registro
- **THEN** the system records an explicit no-admissions outcome
- **AND** no admission extraction candidates are produced for follow-up actions

