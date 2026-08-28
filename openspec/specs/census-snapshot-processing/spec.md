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
rows that do not meet the minimum sector coverage requirement, and its
management command SHALL signal rejection with Django `CommandError` rather
than process-level `SystemExit`.

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
- **AND** the command raises a sanitized `CommandError`
- **AND** no `SystemExit` escapes through `call_command`

#### Scenario: Most recent snapshot path applies the same guard

- **WHEN** `process_census_snapshot` is called without `run_id`
- **AND** the selected latest snapshot contains fewer than 40 distinct sectors
- **THEN** the system MUST NOT create a `CensusExecutionBatch`
- **AND** the system MUST NOT enqueue admissions or demographics runs from that
  incomplete snapshot
- **AND** the command raises a sanitized `CommandError`

### Requirement: Complete snapshot processing materializes occupancy history

The system SHALL attempt occupancy materialization for the selected complete
census run after the completeness guard and before creating a
`CensusExecutionBatch` or enqueuing patient ingestion runs.

#### Scenario: Complete post-activation run is processed

- **WHEN** `process_census_snapshot` selects a complete run with an applicable
  capacity catalog
- **THEN** it materializes or reuses that run's occupancy measurement
- **AND** only then continues the existing patient-processing flow

#### Scenario: Incomplete run is rejected before measurement

- **WHEN** the GCEC-S2 completeness guard rejects the selected snapshot
- **THEN** no occupancy measurement or daily summary is created
- **AND** no clinical batch or patient ingestion run is created

#### Scenario: Complete run has zero occupied patients

- **WHEN** a complete accepted run has no occupied patient record to enqueue
- **THEN** its occupancy measurement is still materialized
- **AND** the existing behavior of creating no clinical batch is preserved

#### Scenario: Pre-activation run preserves clinical processing

- **WHEN** the selected complete run predates the first applicable catalog
- **THEN** occupancy materialization returns `pre_activation` without creating
  history
- **AND** the existing clinical processing continues

### Requirement: Capacity-data gaps do not block clinical processing

The system SHALL represent unknown sectors, source-name mismatches, pending
linked slots and missing official capacities as non-calculable measurement
states without failing an otherwise complete census.

#### Scenario: Complete run contains an unknown sector

- **WHEN** a complete accepted run contains a code absent from the catalog
- **THEN** the measurement records it as `unmapped`
- **AND** clinical batch creation and patient enqueuing continue

#### Scenario: Complete run contains unrated sectors

- **WHEN** a complete accepted run contains a configured `unrated` sector
- **THEN** the measurement records null capacity and percentage
- **AND** clinical processing continues

#### Scenario: Structural persistence failure occurs

- **WHEN** occupancy materialization fails because the catalog is invalid or
  database persistence fails
- **THEN** the processing command fails before creating a clinical batch
- **AND** the error contains no patient identifier or clinical text

### Requirement: Legacy latest-snapshot processing requires provenance for history

The path without an explicit run id SHALL materialize occupancy only when the
latest snapshot set resolves to exactly one census `IngestionRun`.

#### Scenario: Latest snapshot has one run

- **WHEN** the legacy path selects the latest `captured_at`
- **AND** all selected rows resolve to one census run
- **THEN** occupancy materialization uses that run as its idempotency key

#### Scenario: Latest snapshot lacks unique run provenance

- **WHEN** the latest snapshot rows have no run or more than one distinct run
- **THEN** occupancy history is not materialized
- **AND** the existing clinical processing path remains available
- **AND** the result reports `missing_provenance` using aggregate-safe metadata

### Requirement: Census snapshots preserve a normalized occupancy age band

For every newly extracted census row, the system SHALL derive and persist only
the normalized age band required by occupancy classification, using the row's
own legacy `Idade` value and bed status.

#### Scenario: Integer below twelve is classified as child

- **WHEN** an occupied census row has an integer age from 0 through 11
- **THEN** its persisted occupancy age band is `under_12`

#### Scenario: Integer twelve or greater is classified as adult

- **WHEN** an occupied census row has integer age 12 or greater
- **THEN** its persisted occupancy age band is `age_12_or_over`

#### Scenario: Legacy month and day formats are normalized

- **WHEN** an occupied census row has a valid legacy age such as `1m` or
  `1m3d`
- **THEN** the system interprets its month/day units deterministically
- **AND** persists the corresponding age band without persisting that raw age
  in occupancy history

#### Scenario: Unknown occupied age remains explicit

- **WHEN** an occupied census row has a blank, negative, unsupported or
  structurally invalid age
- **THEN** its persisted occupancy age band is `unknown`
- **AND** the system does not infer age from name, record number, specialty or
  another row

#### Scenario: Non-occupied row has no applicable age band

- **WHEN** a census row is empty, reserved, in maintenance or in isolation
- **THEN** its persisted occupancy age band is `not_applicable`

#### Scenario: Historical snapshots are not backfilled

- **WHEN** the additive age-band migration is applied
- **THEN** existing snapshots receive a safe non-classifying default
- **AND** no historical age is reconstructed from patient data

### Requirement: Age classification does not change clinical census processing

The system SHALL restrict the normalized age band to capacity and occupancy
calculation and SHALL preserve the source sector and all existing clinical
processing behavior.

#### Scenario: Virtual 3A sectors do not replace the clinical source sector

- **WHEN** a code `654` row is classified for occupancy
- **THEN** its stored source code and source sector remain unchanged
- **AND** patient movement, ingestion and clinical views continue using the
  original 3A sector

#### Scenario: Unknown age does not block clinical processing

- **WHEN** an otherwise complete accepted census contains an occupied code
  `654` row with age band `unknown`
- **THEN** the clinical batch and patient ingestion flow continue normally
- **AND** only the occupancy result records the aggregate age-classification
  gap

### Requirement: Physical-position quality gaps do not block clinical processing

The system SHALL restrict v3 deduplication and conflict handling to occupancy
measurement and presentation, while clinical census processing continues from
the preserved raw snapshots.

#### Scenario: Exact duplicate is suppressed only from occupancy

- **WHEN** an otherwise complete accepted census contains an exact duplicate
  physical position
- **THEN** v3 occupancy counts the position once
- **AND** existing patient, movement and ingestion processing retain their
  prior raw-snapshot behavior

#### Scenario: Conflicting position produces a partial measurement

- **WHEN** an otherwise complete accepted census contains one conflicting
  physical position
- **THEN** a physically partial v3 measurement is persisted
- **AND** clinical batch creation and patient enqueuing continue normally
- **AND** only official daily occupancy eligibility is affected

#### Scenario: Unidentified occupied row produces a partial measurement

- **WHEN** an otherwise complete accepted census contains an occupied row
  without usable bed identity
- **THEN** v3 occupancy preserves an aggregate unidentified count and partial
  flag
- **AND** clinical processing continues without inferring a bed or patient
