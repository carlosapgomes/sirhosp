<!-- markdownlint-disable MD013 -->
# patient-admission-mirror Specification

## MODIFIED Requirements

### Requirement: Admission mirror linked to patient

The system SHALL maintain admissions linked to patients using reconciliation that tolerates source admission key instability.

#### Scenario: Reconcile admission for repeated ingestion with stable source key

- **WHEN** an ingestion run receives an admission that already exists by `(source_system, source_admission_key)`
- **THEN** the system reuses the existing admission and updates mutable metadata without duplication

#### Scenario: Reconcile admission for repeated ingestion with unstable source key

- **WHEN** an ingestion run receives an admission whose `source_admission_key` changed between runs
- **AND** patient + admission period (`admission_start`, `admission_end`) matches an existing admission
- **THEN** the system reuses the existing admission for that patient/period
- **AND** does not create a duplicate admission record

#### Scenario: Consolidate duplicated admissions for same patient and period

- **WHEN** more than one admission exists for the same patient and period
- **THEN** the system consolidates to a single canonical admission deterministically
- **AND** reassigns linked clinical events to the canonical admission before removing duplicates

### Requirement: Persist known admissions independently from extracted evolutions

The system SHALL keep known admissions visible even when no evolutions were extracted, while preserving period-level uniqueness.

#### Scenario: Failed run still preserves canonical admission identity

- **WHEN** admissions snapshot capture succeeded but evolution extraction failed
- **THEN** the admission for that patient/period remains persisted
- **AND** subsequent reruns for the same period reuse that same admission record instead of creating new rows
