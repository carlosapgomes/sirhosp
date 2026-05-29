# patient-movement-model Specification

## ADDED Requirements

### Requirement: PatientMovement stores sector transit history

The system SHALL provide a `PatientMovement` model that records each
significant change of sector for a patient during an admission.

#### Scenario: Create a movement record

- **WHEN** a `PatientMovement` is created with `patient`, `movement_date`,
  `sector`
- **THEN** the record is persisted with auto-generated `first_seen_at` and
  `last_seen_at`

#### Scenario: Unique constraint prevents duplicates

- **WHEN** a second `PatientMovement` is created with the same
  `(patient, movement_date, sector)` combination
- **THEN** the database raises an integrity error

#### Scenario: Multiple sectors on the same day are allowed

- **WHEN** a `PatientMovement` is created for patient A on date D with
  sector "PS"
- **AND** another `PatientMovement` is created for patient A on date D
  with sector "UTI"
- **THEN** both records are persisted successfully

#### Scenario: Default ordering is by patient and sequence

- **WHEN** multiple `PatientMovement` records exist for the same patient
  with different `sequence` values
- **THEN** the default queryset ordering is `patient` ascending,
  `sequence` ascending

### Requirement: PatientMovement tracks temporal snapshots

The system SHALL record `first_seen_at` and `last_seen_at` to track when a
movement state was first and last observed in census snapshots.

#### Scenario: first_seen_at is set on creation

- **WHEN** a `PatientMovement` is created
- **THEN** `first_seen_at` is populated with the creation timestamp

#### Scenario: last_seen_at is updated on repeated observation

- **WHEN** a `PatientMovement` is updated without changing sector
- **THEN** `last_seen_at` is updated to the current timestamp

### Requirement: PatientMovement links optionally to Admission

The system SHALL allow `PatientMovement` to optionally reference an
`Admission` record.

#### Scenario: Movement without linked admission

- **WHEN** a `PatientMovement` is created without an `admission` FK
- **THEN** the record is persisted with `admission=None`

#### Scenario: Movement with linked admission

- **WHEN** a `PatientMovement` is created referencing a valid `Admission`
- **THEN** the record is persisted with the FK populated

### Requirement: PatientMovement discharge_type indicates exit reason

The system SHALL store the `tipo_alta` value from the census in the
`discharge_type` field, with empty string meaning the patient is still
active.

#### Scenario: Active patient has empty discharge_type

- **WHEN** a `PatientMovement` is created for a patient still in the sector
- **THEN** `discharge_type` is an empty string

#### Scenario: Discharged patient has non-empty discharge_type

- **WHEN** a `PatientMovement` is created from a snapshot where
  `tipo_alta` is not empty
- **THEN** `discharge_type` stores that value as a string
