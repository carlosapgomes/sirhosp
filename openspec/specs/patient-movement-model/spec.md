# patient-movement-model Specification

## Purpose

Defines the PatientMovement ledger: sector transit history, temporal snapshots, optional Admission links and discharge typing.

## Requirements

### Requirement: PatientMovement stores sector transit history

The system SHALL provide a `PatientMovement` model that records each
significant change of sector for a patient during an admission, carrying —
when the source census snapshot provides it — the real movement timestamp
from the portal.

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
- **AND** another `PatientMovement` is created for patient A on date D with
  sector "Enf"
- **THEN** both records are persisted

#### Scenario: Default ordering is by patient and sequence

- **WHEN** multiple `PatientMovement` records exist for the same patient
  with different `sequence` values
- **THEN** the default queryset ordering is `patient` ascending,
  `sequence` ascending

#### Scenario: Optional source movement time is stored when available

- **WHEN** a movement is created from a census snapshot that carries a
  non-null source movement timestamp
- **THEN** the movement persists that timestamp verbatim (aware, in the
  configured timezone) in an optional `source_movement_at` field
- **AND** movements whose snapshot has no source timestamp persist `NULL`
  (date-only remains valid)

#### Scenario: Source movement time is never inferred

- **WHEN** a snapshot has no source movement timestamp
- **THEN** the corresponding movement keeps `source_movement_at` as `NULL`
- **AND** no capture time, processing time or midnight value is written

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

### Requirement: Census upsert propagates source movement time

The census movement upsert SHALL propagate the source movement timestamp
from the census snapshot being processed to the matching movement, keeping
the most recent source observation as the authoritative value.

#### Scenario: New movement inherits snapshot time

- **WHEN** the upsert creates a movement for a patient whose snapshot has a
  non-null source movement timestamp
- **THEN** the created movement stores that timestamp in
  `source_movement_at`

#### Scenario: Repeated observation refreshes the time from the latest source

- **WHEN** the same `(patient, movement_date, sector)` movement is observed
  again in a later census snapshot for the same movement date
- **AND** that snapshot carries a source movement timestamp
- **THEN** the movement's `source_movement_at` is refreshed to the latest
  snapshot's value

#### Scenario: Movement without time gains time later

- **WHEN** a movement was persisted with `source_movement_at` NULL
- **AND** a later census snapshot for the same movement date carries a
  source movement timestamp
- **THEN** the upsert fills the previously NULL `source_movement_at`

#### Scenario: Later snapshot without time does not erase a known time

- **WHEN** a movement already has a non-null `source_movement_at`
- **AND** a later census snapshot for the same movement date has no source
  movement timestamp
- **THEN** the movement keeps its existing `source_movement_at`

#### Scenario: Historical movements are not backfilled

- **WHEN** movements were created before this capability existed
- **THEN** they remain `source_movement_at` NULL until a new census
  observation for their movement date provides a time
- **AND** no migration or batch job writes times to historical movements
