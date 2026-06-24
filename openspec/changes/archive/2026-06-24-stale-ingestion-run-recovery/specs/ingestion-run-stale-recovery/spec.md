# ingestion-run-stale-recovery Specification

## ADDED Requirements

### Requirement: Stale recovery identifies abandoned running runs

The system SHALL identify abandoned `IngestionRun` records using per-run age,
run intent and worker heartbeat, not total batch duration.

#### Scenario: Running run with fresh heartbeat is not abandoned

- **WHEN** stale recovery evaluates an `IngestionRun` with status `running`
- **AND** its `worker_heartbeat_at` is within the configured heartbeat grace
- **THEN** the run is not classified as abandoned
- **AND** the recovery does not mark it as failed

#### Scenario: Running run older than intent limit and stale heartbeat

- **WHEN** stale recovery evaluates an `IngestionRun` with status `running`
- **AND** its age exceeds the configured limit for its `intent`
- **AND** its `worker_heartbeat_at` is null or older than the heartbeat grace
- **THEN** the run is classified as abandoned

#### Scenario: Running run younger than intent limit is not abandoned

- **WHEN** stale recovery evaluates an `IngestionRun` with status `running`
- **AND** its age does not exceed the configured limit for its `intent`
- **THEN** the run is not classified as abandoned
- **AND** the heartbeat state alone does not make it eligible for recovery

#### Scenario: Unknown intent uses default limit

- **WHEN** stale recovery evaluates a running run with empty or unknown `intent`
- **THEN** it uses the configured default stale limit for unknown intents

### Requirement: Stale recovery supports dry-run inspection

The system SHALL provide a non-mutating way to inspect abandoned run candidates.

#### Scenario: Dry-run lists candidates without mutation

- **WHEN** the operator runs stale recovery in dry-run mode
- **THEN** the system reports candidate run ids, intents, age and worker labels
- **AND** it does not change `IngestionRun` status
- **AND** it does not change `CensusExecutionBatch` status

#### Scenario: Dry-run output is safe

- **WHEN** stale recovery reports candidates
- **THEN** output contains only operational identifiers, timestamps, intents,
  statuses and counts
- **AND** output does not contain patient names, clinical text or credentials

### Requirement: Stale recovery marks abandoned runs as terminal failures

The system SHALL mark confirmed abandoned runs as terminal `failed` records
without automatic requeue.

#### Scenario: Apply marks abandoned run failed

- **WHEN** stale recovery runs in apply mode
- **AND** a running run satisfies abandoned criteria
- **THEN** the run status is changed to `failed`
- **AND** `finished_at` is set
- **AND** `timed_out` is set to true
- **AND** `failure_reason` is set to `timeout`
- **AND** `next_retry_at` is cleared
- **AND** the error message identifies stale recovery without patient data

#### Scenario: Apply does not requeue abandoned run

- **WHEN** stale recovery marks an abandoned run as failed
- **THEN** it does not set the run status back to `queued`
- **AND** it does not schedule `next_retry_at`
- **AND** it does not consume or increment retry attempts

#### Scenario: Apply is race-safe for already terminal run

- **WHEN** stale recovery attempts to mark a candidate as failed
- **AND** the run is no longer in status `running`
- **THEN** the recovery does not overwrite the terminal status
- **AND** it reports the run as skipped due to state change

### Requirement: Stale recovery closes drained batches

The system SHALL attempt to close a batch after abandoned runs are marked
terminally failed.

#### Scenario: Batch drains after abandoned run fails

- **WHEN** stale recovery marks the last active run in a batch as failed
- **AND** no runs in that batch remain `queued` or `running`
- **THEN** the batch `finished_at` is set
- **AND** the batch status is set to `failed`

#### Scenario: Batch with remaining active runs stays open

- **WHEN** stale recovery marks a run as failed
- **AND** the run batch still has other runs in status `queued` or `running`
- **THEN** the batch remains open

### Requirement: Stale recovery protects against mass mutation

The system SHALL include a circuit breaker that prevents unexpected mass failure
of running jobs.

#### Scenario: Candidate count exceeds sweep limit

- **WHEN** stale recovery in apply mode finds more candidates than the configured
  maximum runs per sweep
- **THEN** it aborts without mutating any run
- **AND** it reports that the circuit breaker prevented automatic recovery

#### Scenario: Candidate count is within sweep limit

- **WHEN** stale recovery in apply mode finds candidate count within the
  configured maximum runs per sweep
- **THEN** it may mark those candidates as failed according to recovery rules
