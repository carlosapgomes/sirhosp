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

### Requirement: Defensive reconciliation metadata

The system MUST persist reconciliation-support fields for admissions and patients to tolerate future source key instability.

#### Scenario: Persist reconciliation support data

- **WHEN** patient and admission data are ingested
- **THEN** the system stores additional reference metadata (such as admission period and source patient reference) required for controlled reconciliation
