# adaptive-census-orchestration Specification

## ADDED Requirements

### Requirement: Orchestrator starts cycles only when ingestion is drained

The system SHALL provide an adaptive census orchestrator that starts a new
census cycle only when ingestion work is drained.

#### Scenario: Queue is idle

- **WHEN** the orchestrator evaluates whether a new cycle can start
- **AND** no `IngestionRun` exists with status `queued` or `running`
- **AND** no open `CensusExecutionBatch` exists
- **THEN** the orchestrator reports the system as eligible for a new cycle

#### Scenario: Queue has pending work

- **WHEN** the orchestrator evaluates whether a new cycle can start
- **AND** at least one `IngestionRun` exists with status `queued` or `running`
- **THEN** the orchestrator MUST NOT start a new census cycle
- **AND** it reports how many active runs are blocking the cycle

#### Scenario: Open batch blocks new cycle

- **WHEN** the orchestrator evaluates whether a new cycle can start
- **AND** a `CensusExecutionBatch` has no `finished_at`
- **THEN** the orchestrator MUST NOT start a new census cycle
- **AND** it reports that an open batch is blocking the cycle

### Requirement: Orchestrator executes one safe census cycle

The orchestrator SHALL execute a safe census cycle by running census extraction
and then processing the snapshot produced by that extraction.

#### Scenario: Successful single cycle

- **WHEN** the orchestrator is asked to run one cycle
- **AND** the queue is drained
- **AND** the cooldown interval has elapsed
- **THEN** it runs `extract_census`
- **AND** it identifies exactly one new successful `census_extraction` run
- **AND** it runs `process_census_snapshot` with that run id
- **AND** it reports the created batch id and enqueued counts when available

#### Scenario: Extraction fails

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` fails
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** it exits or reports failure without enqueuing a new census batch

#### Scenario: Extraction run is ambiguous

- **WHEN** `extract_census` returns successfully
- **AND** the orchestrator cannot identify exactly one new successful
  `census_extraction` run from the cycle
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** it reports the ambiguity as an operational failure

### Requirement: Orchestrator prevents concurrent execution

The orchestrator MUST prevent more than one orchestrator instance from starting
a census cycle at the same time.

#### Scenario: Lock is acquired

- **WHEN** an orchestrator instance starts a cycle
- **AND** the PostgreSQL coordination lock is available
- **THEN** it acquires the lock before checking and starting the cycle
- **AND** releases the lock after the cycle succeeds, fails, or is skipped

#### Scenario: Lock is already held

- **WHEN** an orchestrator instance starts a cycle
- **AND** another orchestrator instance already holds the coordination lock
- **THEN** the new instance MUST NOT start extraction
- **AND** it reports that another orchestrator is active

### Requirement: Orchestrator respects cooldown and failure backoff

The orchestrator SHALL avoid aggressive repeated access to the source system by
respecting cooldown and failure backoff settings.

#### Scenario: Cooldown has not elapsed

- **WHEN** the queue is drained
- **AND** the latest successful census extraction is newer than the configured
  minimum interval
- **THEN** the orchestrator MUST NOT start a new cycle
- **AND** it reports the remaining cooldown or the reason for waiting

#### Scenario: Failure backoff in loop mode

- **WHEN** a cycle fails in continuous loop mode
- **THEN** the orchestrator waits for the configured failure backoff before
  attempting another cycle

### Requirement: Orchestrator supports dry-run and loop modes

The orchestrator SHALL support a non-mutating status check and a continuous
mode suitable for service execution.

#### Scenario: Dry-run reports decision without mutating data

- **WHEN** the operator runs the orchestrator in dry-run mode
- **THEN** it reports whether a cycle would start
- **AND** it does not execute `extract_census`
- **AND** it does not execute `process_census_snapshot`
- **AND** it does not create `IngestionRun` or `CensusExecutionBatch` records

#### Scenario: Loop waits while blocked

- **WHEN** the orchestrator runs in loop mode
- **AND** the queue is not drained
- **THEN** it logs the waiting reason
- **AND** sleeps for the configured interval before checking again

#### Scenario: Loop handles shutdown signal

- **WHEN** the orchestrator runs in loop mode
- **AND** it receives SIGTERM or SIGINT
- **THEN** it exits gracefully after the current sleep or cycle boundary

### Requirement: Orchestrator reports stale active runs without mutating them

The orchestrator SHALL detect active runs that exceed the configured stale
threshold and report them for manual operator review.

#### Scenario: Stale running run exists

- **WHEN** at least one `IngestionRun` has status `running`
- **AND** its processing start or queue time is older than the configured stale
  threshold
- **THEN** the orchestrator reports a stale active run warning
- **AND** it does not mark the run as failed
- **AND** it does not start a new census cycle

#### Scenario: Active run is slow but not stale

- **WHEN** a run is still active but newer than the stale threshold
- **THEN** the orchestrator reports normal waiting state
- **AND** it does not classify the run as stale
