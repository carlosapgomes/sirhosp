# current-census-admissions-recovery Specification

## Purpose

TBD - created by archiving change repair-persistent-admissions-pipeline. Update Purpose after archive.

## Requirements

### Requirement: Recovery plans from the latest complete census

The system SHALL provide a deterministic recovery plan for admissions of unique
occupied patients from the latest census snapshot with complete coverage and
unambiguous run provenance.

#### Scenario: Complete latest census is eligible

- **WHEN** the latest snapshot resolves to one census ingestion run
- **AND** it satisfies the existing minimum sector coverage
- **THEN** recovery plans each unique occupied non-empty patient record at most
  once
- **AND** output contains only aggregate candidate and exclusion counts

#### Scenario: Missing, incomplete or ambiguous census blocks recovery

- **WHEN** no snapshot exists, coverage is incomplete, or provenance does not
  resolve to one census run
- **THEN** recovery fails safely before creating a batch or ingestion run
- **AND** the error contains no patient, HTML, URL or credential data

### Requirement: Recovery is dry-run by default and bounded on apply

The recovery command SHALL make no mutation unless apply is explicitly selected
and SHALL bound each applied batch with a positive operator-provided limit.

#### Scenario: Default dry-run is non-mutating

- **WHEN** the operator runs current-census admissions recovery without
  `--apply`
- **THEN** the command prints an aggregate plan
- **AND** creates no `CensusExecutionBatch`, `IngestionRun`, Patient or Admission

#### Scenario: Invalid limit fails before mutation

- **WHEN** apply receives a missing, zero or negative limit
- **THEN** the command raises `CommandError` before creating any record

#### Scenario: Limited apply creates one recovery batch

- **WHEN** the operator supplies `--apply --limit N` for an eligible census
- **THEN** at most N admissions-only runs are created in one recovery batch
- **AND** each run uses the canonical queue helper and explicit intent
- **AND** the batch stores only safe recovery provenance/aggregate metadata

### Requirement: Recovery is idempotent and does not reopen incident history

Recovery SHALL skip duplicate or already-active work and SHALL preserve the
historical runs recorded during the incident.

#### Scenario: Active admissions work is skipped

- **WHEN** an eligible patient already has a queued or running
  `admissions_only` run
- **THEN** recovery does not enqueue another run for that patient

#### Scenario: Prior recovery for the same census is skipped

- **WHEN** an eligible patient already belongs to a recovery batch for the same
  census run
- **THEN** a repeated dry-run or apply does not enqueue that patient again

#### Scenario: Historical false successes remain immutable

- **WHEN** recovery creates new runs
- **THEN** it does not change status, attempts, counters, timestamps or
  parameters of any historical `IngestionRun`

### Requirement: Recovery composes with corrected follow-ups

The recovery batch SHALL reuse normal admissions persistence, retry, batch and
full-sync behavior without duplicating census demography.

#### Scenario: Valid recovered admission schedules full-sync

- **WHEN** a recovery admissions run captures and persists a non-empty snapshot
- **THEN** the most recent admission full-sync is attached to the recovery batch
- **AND** no detached demographics follow-up is created

#### Scenario: Empty recovered admission fails closed

- **WHEN** a recovery admissions capture returns an empty snapshot
- **THEN** the batch-bound empty-snapshot invariant applies
- **AND** no clinical or follow-up effects are created from that result
