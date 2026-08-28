# patient-demographics-ingestion Delta Specification

## MODIFIED Requirements

### Requirement: Census pipeline enqueues demographics runs

The system SHALL automatically enqueue exactly one batch-owned
`demographics_only` ingestion run for each unique patient processed by the
census snapshot processor, while preserving standalone admissions-driven
refresh behavior.

#### Scenario: New patient from census gets demographics run

- **WHEN** `process_census_snapshot()` discovers a new patient
- **THEN** one `IngestionRun` with `intent="demographics_only"`, status
  `queued`, and the census batch is created for that patient
- **AND** an `IngestionRun` with `intent="admissions_only"` is also created

#### Scenario: Existing patient from census also gets demographics run

- **WHEN** `process_census_snapshot()` encounters a patient that already exists
- **THEN** exactly one batch-owned `demographics_only` run is still enqueued to
  refresh demographic data

#### Scenario: Admissions success does not duplicate batch demographics

- **WHEN** either worker completes an `admissions_only` run linked to a census
  or recovery batch
- **THEN** it does not enqueue a detached `demographics_only` follow-up
- **AND** the batch-owned demographics run remains the sole producer for that
  cycle

#### Scenario: Standalone admissions can request demographics refresh

- **WHEN** either worker completes a valid standalone `admissions_only` run
- **THEN** the existing detached demographics follow-up is preserved

#### Scenario: Demographics runs counted in metrics

- **WHEN** `process_census_snapshot()` completes
- **THEN** the returned metrics dict includes a
  `demographics_runs_enqueued` key equal to the number of unique occupied
  patients processed
