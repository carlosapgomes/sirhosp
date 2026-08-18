# census-snapshot-processing Delta Specification

## ADDED Requirements

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
