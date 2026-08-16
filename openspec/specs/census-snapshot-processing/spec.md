# census-snapshot-processing Specification

## Purpose

Define how a captured census snapshot is processed into patients and
enqueued ingestion runs, and how `PatientMovement` records are upserted from
the snapshot. Supports both the legacy most-recent-snapshot path and explicit
run-scoped processing used by the adaptive census orchestrator.

## Requirements

### Requirement: process_census_snapshot triggers PatientMovement upsert

The system SHALL upsert `PatientMovement` records as part of the census
snapshot processing cycle, after patients are created/updated and ingestion
runs are enqueued. When a specific census extraction run is provided, the system
SHALL process snapshots from that run rather than the most recent global
snapshot.

#### Scenario: Occupied bed in snapshot creates movement

- **WHEN** `process_census_snapshot` processes a snapshot with an occupied bed
- **AND** no `PatientMovement` exists for that `(patient, movement_date, sector)`
- **THEN** a new `PatientMovement` is created with the snapshot data

#### Scenario: Repeated same state updates last_seen_at

- **WHEN** `process_census_snapshot` processes a snapshot where the patient is
  in the same sector with the same `movement_date` as the previous cycle
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

#### Scenario: Orchestrated processing uses explicit census run

- **WHEN** an adaptive census cycle completes `extract_census`
- **AND** the resulting census extraction run id is passed to
  `process_census_snapshot`
- **THEN** only `CensusSnapshot` rows linked to that run are processed
- **AND** snapshots from newer or older census extraction runs are ignored

### Requirement: Snapshot processing rejects incomplete census extraction

The system SHALL refuse to create a `CensusExecutionBatch` from census snapshot
rows that do not meet the minimum sector coverage requirement.

#### Scenario: Explicit run with enough sectors is processed

- **WHEN** `process_census_snapshot` is called with a census extraction `run_id`
- **AND** the linked `CensusSnapshot` rows contain at least 40 distinct sectors
- **THEN** the snapshot can be processed normally
- **AND** a `CensusExecutionBatch` can be created when occupied patients exist

#### Scenario: Explicit run with too few sectors is rejected

- **WHEN** `process_census_snapshot` is called with a census extraction `run_id`
- **AND** the linked `CensusSnapshot` rows contain fewer than 40 distinct
  sectors
- **THEN** the system MUST NOT create a `CensusExecutionBatch`
- **AND** the system MUST NOT enqueue admissions or demographics runs from that
  incomplete snapshot
- **AND** the command reports the insufficient sector coverage

#### Scenario: Most recent snapshot path applies the same guard

- **WHEN** `process_census_snapshot` is called without `run_id`
- **AND** the selected latest snapshot contains fewer than 40 distinct sectors
- **THEN** the system MUST NOT create a `CensusExecutionBatch`
- **AND** the system MUST NOT enqueue admissions or demographics runs from that
  incomplete snapshot
- **AND** the command reports the insufficient sector coverage
