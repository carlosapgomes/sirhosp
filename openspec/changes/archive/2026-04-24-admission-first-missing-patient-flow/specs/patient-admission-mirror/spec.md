# patient-admission-mirror Specification

## ADDED Requirements

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
