# adaptive-census-orchestration Specification

## Purpose

Define the adaptive census orchestrator that starts a new census cycle
(extraction + snapshot processing) only when ingestion work is drained, using
PostgreSQL as the coordination mechanism. Covers safe-cycle execution,
concurrency prevention via advisory lock, cooldown and failure backoff,
dry-run and continuous-loop modes, and stale active-run reporting.

## Requirements

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
and then processing the snapshot produced by that extraction only when the
extraction is complete enough for operational use. The one-shot management
command SHALL return a nonzero process status when the cycle fails, is
incomplete, is ambiguous, or produces an unknown outcome.

#### Scenario: Successful single cycle

- **WHEN** the orchestrator is asked to run one cycle
- **AND** the queue is drained
- **AND** the cooldown interval has elapsed
- **AND** `extract_census` completes with at least 40 distinct sectors
- **THEN** it runs `extract_census`
- **AND** it identifies exactly one new successful `census_extraction` run
- **AND** it runs `process_census_snapshot` with that run id
- **AND** it reports the created batch id and enqueued counts when available
- **AND** the one-shot command returns process status zero

#### Scenario: Extraction fails

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` fails
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** the one-shot command reports the failure and returns a nonzero process
  status without enqueuing a new census batch

#### Scenario: Extraction is incomplete

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` detects fewer than 40 distinct sectors
- **THEN** it MUST treat the cycle as an extraction failure
- **AND** it MUST NOT run `process_census_snapshot`
- **AND** the one-shot command reports incomplete coverage and returns a nonzero
  process status

#### Scenario: Extraction run is ambiguous

- **WHEN** `extract_census` returns successfully
- **AND** the orchestrator cannot identify exactly one new successful
  `census_extraction` run from the cycle
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** the one-shot command reports the ambiguity and returns a nonzero
  process status

#### Scenario: One-shot cycle is safely blocked

- **WHEN** the one-shot command is blocked by active work or observes that
  another orchestrator holds the coordination lock
- **THEN** it does not start extraction
- **AND** it reports the safe no-work condition
- **AND** it returns process status zero

#### Scenario: One-shot cycle returns an unknown outcome

- **WHEN** the one-shot command receives an outcome outside its known taxonomy
- **THEN** it reports the unexpected outcome
- **AND** it returns a nonzero process status

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

The orchestrator SHALL report stale active runs in dry-run and disabled-recovery
modes, and SHALL delegate automatic stale-run mutation to the configured stale
recovery service before deciding whether the queue is drained in loop mode.

#### Scenario: Stale running run exists and recovery is disabled

- **WHEN** at least one `IngestionRun` has status `running`
- **AND** its processing start or queue time is older than the configured stale
  threshold
- **AND** stale recovery is disabled for the orchestrator execution
- **THEN** the orchestrator reports a stale active run warning
- **AND** it does not mark the run as failed
- **AND** it does not start a new census cycle

#### Scenario: Active run is slow but not stale

- **WHEN** a run is still active but newer than the stale threshold
- **THEN** the orchestrator reports normal waiting state
- **AND** it does not classify the run as stale

#### Scenario: Loop invokes stale recovery before eligibility check

- **WHEN** the orchestrator runs in continuous loop mode
- **AND** stale recovery is enabled
- **THEN** it invokes stale-run recovery before computing whether a new census
  cycle can start
- **AND** it uses the updated run and batch state for the eligibility decision

#### Scenario: Recovery frees the queue for a new cycle

- **WHEN** stale recovery marks abandoned runs as failed
- **AND** affected batches are closed because no queued or running runs remain
- **AND** cooldown and other eligibility criteria are satisfied
- **THEN** the orchestrator may start the next census cycle in the same loop
  execution flow

#### Scenario: Recovery circuit breaker blocks automatic mutation

- **WHEN** stale recovery reports that its circuit breaker prevented mutation
- **THEN** the orchestrator does not start a new census cycle
- **AND** it logs the recovery blocker as the reason for waiting

### Requirement: Production loop runtime is isolated from the web service

The production deployment guidance for the orchestrator loop SHALL prefer a
dedicated runtime service for continuous execution, while preserving manual
`--dry-run` and `--once` execution for diagnostics.

#### Scenario: Continuous loop uses dedicated runtime

- **WHEN** an operator deploys the adaptive census orchestrator in production
  continuous mode
- **THEN** the recommended runtime is the dedicated `census_orchestrator`
  service
- **AND** the loop is not run as a long-lived `docker compose exec -T web`
  process

#### Scenario: Manual diagnostics remain available

- **WHEN** an operator needs to inspect eligibility or run a single controlled
  cycle
- **THEN** the documented commands preserve `run_adaptive_census_cycles
  --dry-run` and `run_adaptive_census_cycles --once`
- **AND** the commands use the dedicated runtime when volatile storage behavior
  is being validated

### Requirement: Census extractors share the proven authentication bootstrap

The official and current census Playwright extractors SHALL use the same
canonical source-system authentication bootstrap used by the persistent worker.

#### Scenario: Census extractor starts an authenticated session

- **WHEN** either census extractor starts a source-system session
- **THEN** it fills the configured username and password
- **AND** it submits the login by pressing Enter in the password field
- **AND** it waits for `#tempoSessao` to contain at least three numeric parts
  before continuing to census navigation
- **AND** it does not infer authentication failure from the completion status
  of the login button click

#### Scenario: Hospital host has a direct route to the source system

- **WHEN** the hospital host can reach the configured source-system URL directly
- **THEN** census authentication does not require a proxy
- **AND** optional existing proxy behavior remains available when explicitly
  configured

### Requirement: Current census consumes only fresh search results

The current-census extractor SHALL distinguish each newly rendered JSF search
result from the prior sector's result before classifying or exporting it.

#### Scenario: Previous sector displayed an explicit empty result

- **WHEN** the operator selects another sector and triggers `Pesquisar`
- **AND** the prior explicit empty row remains visible while the AJAX response
  is pending
- **THEN** the extractor ignores that stale row
- **AND** it waits for a structurally fresh, settled result table
- **AND** it exports the XLSX when the refreshed table contains patient rows

#### Scenario: Search result does not refresh

- **WHEN** the result table does not become fresh and stable before the timeout
- **THEN** the sector attempt fails
- **AND** the extractor does not classify the stale table as the new result
- **AND** the existing retry and completeness policies remain in force

#### Scenario: Result freshness is observed safely

- **WHEN** the extractor observes the result-table transition
- **THEN** it uses only structural counts, loading state and a non-reversible
  in-browser signature
- **AND** it does not return, log or persist table text, HTML, patient values,
  credentials or cookies as freshness evidence
