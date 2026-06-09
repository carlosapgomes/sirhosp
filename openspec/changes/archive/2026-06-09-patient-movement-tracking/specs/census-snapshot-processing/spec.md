# census-snapshot-processing Specification

## MODIFIED Requirements

### Requirement: process_census_snapshot triggers PatientMovement upsert

The system SHALL upsert `PatientMovement` records as part of the census
snapshot processing cycle, after patients are created/updated and ingestion
runs are enqueued.

#### Scenario: Occupied bed in snapshot creates movement

- **WHEN** `process_census_snapshot` processes a snapshot with an occupied bed
- **AND** no `PatientMovement` exists for that `(patient, movement_date, sector)`
- **THEN** a new `PatientMovement` is created with the snapshot data

#### Scenario: Repeated same state updates last_seen_at

- **WHEN** `process_census_snapshot` processes a snapshot where the patient
  is in the same sector with the same `movement_date` as the previous cycle
- **THEN** the existing `PatientMovement.last_seen_at` is updated
- **AND** no new record is created

#### Scenario: New sector creates new movement

- **WHEN** `process_census_snapshot` processes a snapshot where the patient
  moved to a different sector
- **THEN** a new `PatientMovement` is created for the new sector

#### Scenario: Sequence is recalculated after upsert

- **WHEN** `PatientMovement` records are created or updated for a patient
- **THEN** all movements for that patient have their `sequence` field
  recalculated in chronological order

#### Scenario: No occupied beds means no movements processed

- **WHEN** `process_census_snapshot` is called but there are no
  `bed_status=OCCUPIED` rows in the latest snapshot
- **THEN** no `PatientMovement` records are created or modified
- **AND** the method returns without error
