# census-snapshot-processing Delta Specification

## MODIFIED Requirements

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
