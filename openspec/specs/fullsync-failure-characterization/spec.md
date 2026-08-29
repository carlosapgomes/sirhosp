# fullsync-failure-characterization Specification

## Purpose
TBD - created by archiving change characterize-fullsync-chronic-failures. Update Purpose after archive.
## Requirements
### Requirement: Chronic full-sync failure cohort is characterizable through read-only aggregates

The system SHALL expose a Django management command that characterizes the
chronic `full_sync`/`full_admission_sync` failure cohort over a configurable
window using only aggregate queries.

#### Scenario: Fail-only cohort is detected without identifying patients

- **WHEN** the window contains patients with at least the configured minimum
  number of terminal attempts and zero successful full-sync runs
- **THEN** the command reports the cohort size, total failed runs, per-patient
  attempt median and maximum, and the age of the first and last failure
- **AND** no patient record, identifier, parameter payload or clinical text
  appears in stdout, stderr or any raised error

#### Scenario: Reasons, stage timing and hourly pattern are aggregated

- **WHEN** the cohort characterization runs
- **THEN** the output includes the failure reason distribution for the
  fail-only cohort and a contrast distribution for recovered runs
- **AND** includes per-stage duration profiles (median and p90 seconds) and
  the terminal failing stage distribution
- **AND** includes an aggregated hourly histogram of failed attempts
- **AND** every value is a count, duration, percentile or allowlisted reason

#### Scenario: Characterization never mutates state

- **WHEN** the characterization command runs against any database state
- **THEN** no row of any model is created, updated or deleted
- **AND** no network call, subprocess execution or Playwright session is
  performed by the command

### Requirement: Synthetic lab reproduction validates failure hypotheses against real extraction code

The system SHALL provide a laboratory harness, clearly separated from
operational code, that reproduces the observed failure hypotheses against
the real evolution extraction flow using exclusively synthetic fixtures.

#### Scenario: Timeout hypothesis is reproducible and measured

- **WHEN** the harness runs the synthetic large-evolution-list fixture with a
  constrained deadline against the real extraction flow
- **THEN** the resulting sanitized failure reason is `timeout`
- **AND** the experiment records the measured duration, fixture parameters
  and a confirmation verdict in a synthetic artifact

#### Scenario: Invalid payload hypothesis maps to the real classifier

- **WHEN** the harness runs synthetic content fixtures that violate known
  payload validations against the real classifier
- **THEN** each fixture maps to the `invalid_payload` family through the real
  classification path
- **AND** the experiment records which validation triggered each mapping

#### Scenario: Laboratory never touches production data

- **WHEN** any laboratory experiment runs
- **THEN** fixtures are exclusively synthetic and versioned in the repository
- **AND** no production row, credential, patient identifier or real
  HTML/PDF content is read or persisted

### Requirement: Evidence decision artifact recommends the fix with proven cause

The system SHALL consolidate characterization aggregates and laboratory
verdicts into a decision artifact that recommends the corrective change.

#### Scenario: Characterization report is generated from command output

- **WHEN** the characterization command output is processed by the report
  generator
- **THEN** the generated report contains only aggregate values organized by
  cohort, reasons, stage timing, hourly pattern and contrast baseline

#### Scenario: Decision artifact records proven cause or refuted hypotheses

- **WHEN** the characterization report and laboratory verdicts are
  consolidated
- **THEN** the decision artifact (ADR) records each hypothesis with a
  confirmed, refuted or inconclusive verdict and the supporting evidence
- **AND** recommends the corrective change to open, or the next experiment
  when no hypothesis is confirmed
- **AND** contains no patient identifiers or clinical content

