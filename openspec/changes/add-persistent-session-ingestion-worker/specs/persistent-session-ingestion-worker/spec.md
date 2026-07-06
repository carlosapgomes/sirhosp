# Persistent Session Ingestion Worker Spec

## ADDED Requirements

### Requirement: Side-by-side worker

The system SHALL provide an alternative ingestion worker that consumes queued
`IngestionRun` records from the same PostgreSQL queue without changing or
disabling the current `process_ingestion_runs` worker.

#### Scenario: Persistent worker claims safely

- **WHEN** current and persistent workers are running concurrently
- **AND** a queued `IngestionRun` is eligible for processing
- **THEN** at most one worker claims that run
- **AND** the claimed run transitions to `running`
- **AND** other workers skip the locked or already claimed run

#### Scenario: Current worker remains available

- **WHEN** the persistent-session worker command is added
- **THEN** the existing `process_ingestion_runs` command remains executable
- **AND** operators can run either worker type independently

### Requirement: Browser and session reuse

The persistent-session worker SHALL keep a Playwright/Chromium browser context
and authenticated legacy session available across multiple jobs in one process.

#### Scenario: Browser is reused for jobs

- **WHEN** the worker processes consecutive jobs without a restart trigger
- **THEN** it reuses the same browser/session lifecycle for those jobs
- **AND** it does not perform full browser startup and login for each job

#### Scenario: Real handle owns browser profile

- **WHEN** the persistent worker starts a production browser/session path
- **THEN** a real session handle owns the Playwright browser/context lifecycle
- **AND** it uses an exclusive browser profile path for that worker process
- **AND** it exposes open-tab, wait, cleanup, recovery, and shutdown operations
  used by the shared adapter lifecycle

#### Scenario: Relog before claim

- **WHEN** the worker detects before claim that the legacy session is unusable
- **THEN** it renews or relogs before claiming an `IngestionRun`
- **AND** no run is marked `running` only while session recovery is happening

### Requirement: Safe session renewal

The persistent-session worker SHALL renew the legacy session only at safe
checkpoints. Proactive renewal MUST depend on opening and rendering a new safe
legacy tab, with counter verification. Tab close events MUST NOT be treated as
session-renewal evidence.

#### Scenario: Parse session countdown

- **WHEN** the page contains `#tempoSessao` with three time spans
- **THEN** the worker parses remaining time as hours, minutes and seconds
- **AND** the value is available for preventive health decisions
- **AND** no sensitive data is persisted

#### Scenario: Renew by opening safe tab

- **WHEN** proactive session renewal is required at a safe checkpoint
- **AND** a safe renewal tab action is configured
- **THEN** the worker opens a new legacy tab using that action
- **AND** it waits until the tab is fully rendered
- **AND** it verifies that `#tempoSessao` reset before continuing

#### Scenario: Handle visible popup defensively

- **WHEN** `#casca_renovasession` is visible with `aria-hidden="false"`
- **THEN** the worker clicks the semantic `Renovar` button to unblock the page
- **AND** it waits until the popup no longer blocks the page
- **AND** it does not treat popup dismissal alone as proactive counter reset
- **AND** it opens a safe legacy tab if a verified counter reset is required

#### Scenario: Avoid aggressive renewal

- **WHEN** the worker is in a source-system action that is not a safe checkpoint
- **THEN** it does not run an unconstrained background popup clicker
- **AND** renewal waits for a safe checkpoint or recovery path

### Requirement: Root tab preservation

The persistent-session worker SHALL preserve the legacy root tab and close only
non-root operational tabs after each job or recoverable job error.

#### Scenario: Do not close root-only tab

- **WHEN** the tabs list has exactly one `tabs-first tabs-last tabs-selected`
  tab
- **THEN** the worker does not click a close button
- **AND** the root tab remains available for the next job

#### Scenario: Close last non-root tab

- **WHEN** the tabs list contains more than one tab
- **AND** the last tab is not also `tabs-first`
- **AND** the last tab contains `a.tabs-close`
- **THEN** the worker clicks the close button for that last tab
- **AND** it waits for tab count to decrease or root state to return
- **AND** it does not treat that close as a session-renewal signal

#### Scenario: Cleanup runs after recoverable data failure

- **WHEN** an admissions-only job fails due to recoverable source data shape,
  such as missing snapshot container or invalid JSON
- **THEN** the worker records the run failure or retry outcome according to
  existing semantics
- **AND** it attempts to close the non-root job tab before claiming another run
- **AND** it does not treat tab close as session-renewal evidence

#### Scenario: Cleanup failure triggers recovery

- **WHEN** the worker cannot verify safe tab cleanup after a job
- **THEN** it records a safe diagnostic message
- **AND** it relogs or restarts before claiming another run

### Requirement: Browser health restarts

The persistent-session worker SHALL restart its browser/session when configured
health thresholds or unrecoverable browser/session errors are reached.

#### Scenario: Restart after session failures

- **WHEN** renewal or relogin fails beyond the configured threshold
- **THEN** the worker closes the current browser/session
- **AND** it starts a fresh browser/session before claiming more work

#### Scenario: Restart after lifecycle limit

- **WHEN** max jobs per browser session or max lifetime is reached
- **THEN** the worker restarts at the next safe point
- **AND** it does not interrupt a run unless the browser is unusable

#### Scenario: Use exclusive browser profile

- **WHEN** a persistent worker starts a browser context
- **THEN** it uses a profile or temporary directory unique to that process
- **AND** it does not share a mutable Chromium profile with another worker

### Requirement: Run lifecycle preservation

The persistent-session worker SHALL preserve the same externally visible
`IngestionRun` lifecycle semantics as the current worker for supported intents.

#### Scenario: Successful run records metrics

- **WHEN** the persistent worker successfully processes a supported intent
- **THEN** the run reaches `succeeded`
- **AND** lifecycle timestamps, counters, gaps, stages, and attempts are stored
  consistently with current worker behavior

#### Scenario: Failed run records metadata

- **WHEN** the persistent worker fails a supported intent
- **THEN** the run reaches `failed` or is scheduled for retry
- **AND** failure reason, timeout flag, error message, attempts, and stages are
  stored consistently with current worker behavior

#### Scenario: Heartbeat is active

- **WHEN** the persistent worker is processing a claimed run
- **THEN** it refreshes `worker_heartbeat_at` periodically until terminal state
- **AND** heartbeat data contains no patient data, clinical text or credentials

#### Scenario: Source wait timeout is honored

- **WHEN** the persistent worker invokes a source-system wait or extraction
  action with a timeout parameter
- **THEN** the timeout is propagated to the session handle or wait path
- **AND** timeout failures use the existing timeout failure taxonomy

### Requirement: Shared evolution ingestion service

The system SHALL provide a shared evolution ingestion service used by both the
current ingestion worker and the persistent-session worker.

#### Scenario: Current worker delegates to shared service

- **WHEN** the current `process_ingestion_runs` worker persists extracted
  evolutions
- **THEN** it uses the shared evolution ingestion service
- **AND** created, skipped, and revised counters remain equivalent to the
  previous command-local behavior

#### Scenario: Persistent worker uses same service for full-sync

- **WHEN** the persistent-session worker completes evolution extraction for a
  full-sync run
- **THEN** it persists events through the same shared evolution ingestion
  service as the current worker
- **AND** admission resolution, fallback behavior, transactions, and event
  counters remain consistent across worker types

### Requirement: Real persistent handle contract supports legacy data extraction

The persistent-session worker SHALL use a real Playwright session handle that
can provide admission and evolution data from the legacy UI without relying on
fake-only synthetic containers.

#### Scenario: Handle satisfies adapter data contract

- **WHEN** the persistent worker uses the real handle for source-system actions
- **THEN** the handle or adapter boundary returns admission and evolution data
  in the normalized contract expected by the persistent adapter
- **AND** automated tests use mocks or fakes rather than real legacy access

#### Scenario: Bridge translates real legacy output

- **WHEN** the real legacy UI or download flow does not expose synthetic
  `#admission-snapshot-data` or `#evolution-data` containers
- **THEN** the real handle or adapter boundary translates the real output into
  the persistent extraction contract
- **AND** the bridge does not launch a fresh browser or subprocess for each job

#### Scenario: Persistent full-sync is not rollout-ready while contract blocked

- **WHEN** the real handle cannot yet satisfy the legacy data contract
- **THEN** the persistent worker remains guarded from production rollout
- **AND** documentation states the blocker explicitly

#### Scenario: Persistent full-sync succeeds after blockers are resolved

- **WHEN** the real handle contract and shared ingestion service are available
- **AND** a persistent full-sync run extracts evolutions successfully
- **THEN** the run persists events through the shared service
- **AND** lifecycle fields, stage metrics, counters, and failure semantics match
  the current worker's externally visible behavior
