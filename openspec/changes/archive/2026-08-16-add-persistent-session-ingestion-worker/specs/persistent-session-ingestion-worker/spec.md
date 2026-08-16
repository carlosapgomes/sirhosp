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

### Requirement: Explicit replacement intent parity

The persistent-session worker SHALL provide functional and operational parity
for every queued intent supported for replacement: `admissions_only`,
`demographics_only`, `full_sync`, and `full_admission_sync` as an explicit
full-sync alias.

#### Scenario: Supported intent is dispatched explicitly

- **WHEN** the persistent worker claims a supported queued run
- **THEN** it dispatches through an explicit intent mapping
- **AND** it produces the same externally visible clinical and operational
  effects as the current worker
- **AND** it never relies on a generic unknown-intent-to-full-sync fallback

#### Scenario: Empty or unknown intent is not source-processed

- **WHEN** a queued run has an empty or unknown intent
- **THEN** the persistent worker does not claim it during normal queue polling
- **AND** an explicitly selected unsupported run fails validation without
  opening source-system tabs or changing clinical data
- **AND** tests prove supported production enqueue paths create explicit intents

### Requirement: Admissions-only parity

The persistent worker SHALL persist the admissions snapshot and follow-up work
with the same observable semantics as the current worker.

#### Scenario: Admissions-only persists and schedules follow-ups

- **WHEN** an `admissions_only` run captures a valid snapshot
- **THEN** patient and admissions are upserted through the canonical services
- **AND** seen, created, and updated counters reflect database outcomes
- **AND** demographics and full-sync follow-ups are enqueued under the same
  conditions as the current worker
- **AND** no positive created counter is recorded without persistence

### Requirement: Persistent demographics extraction

The persistent worker SHALL process `demographics_only` through the existing
authenticated Playwright session and persist results through
`upsert_patient_demographics`.

#### Scenario: Demographics reuse the current login

- **WHEN** a `demographics_only` run is processed between other persistent jobs
- **THEN** the worker navigates to `Dados do Paciente` through the already-open
  page/context and reads the demographic fields from the legacy UI
- **AND** it performs no subprocess, temporary JSON exchange, new Playwright
  entry, browser/context launch, or second login
- **AND** it records extraction and persistence stages plus the extracted-field
  count consistently with the current worker

### Requirement: Replacement readiness requires parity evidence

The current worker SHALL remain available until automated parity and guarded
live validation demonstrate that the persistent worker can replace it safely.

#### Scenario: Multi-intent parity suite passes

- **WHEN** replacement readiness is evaluated
- **THEN** identical synthetic inputs are exercised through both workers for
  every supported intent
- **AND** status, attempts, stages, failures, counters, clinical persistence,
  follow-up runs, and batch closure are compared
- **AND** a persistent sequence of admissions, demographics, full-sync, and a
  later job proves one login/session is reused across jobs

#### Scenario: Cutover remains blocked without live validation

- **WHEN** fake-based tests pass but the real legacy UI has not been validated
- **THEN** the persistent worker remains a guarded candidate
- **AND** production replacement is not declared ready

### Requirement: Guarded real multi-run execution surface

The persistent-session worker SHALL expose exactly four closed real-handle CLI
modes, validated before any adapter/browser creation or run mutation, and SHALL
keep bounded validation and the continuous real queue disabled until authorized
PSW-S24 live validation succeeds.

#### Scenario: Single real smoke is preserved

- **WHEN** an operator runs `--real-handle --run-id ID --max-runs 1`
- **THEN** exactly the selected queued run is processed under one bootstrap
- **AND** the command rejects the smoke without `--run-id` or with `--max-runs`
  other than `1` before adapter creation

#### Scenario: Bounded validation requires the real handle

- **WHEN** an operator passes `--validation-run-id` values and `--max-runs`
  without `--real-handle`
- **THEN** the command raises a sanitized error before adapter/browser
  creation and before any run mutation
- **AND** the safe stub path never acquires a validation-list mode

#### Scenario: Bounded validation processes an ordered allow-list

- **WHEN** an operator passes `--real-handle` plus two through four distinct
  positive `--validation-run-id` values with `--max-runs` equal to the count
- **THEN** every listed row is preflichted (queued, retry-due, supported
  intent, model/JSON agreement) before one real adapter/bootstrap is created
- **AND** the listed rows are claimed in operator-supplied order under
  `select_for_update(skip_locked=True)`
- **AND** the worker never claims an unlisted eligible row
- **AND** the listed jobs reuse the same real persistent adapter/session
- **AND** a claim race, a job that does not finish as `succeeded`, or a
  restart/rebootstrap failure stops the sequence and leaves every later
  selected row queued and untouched

#### Scenario: Bounded guard rejects invalid combinations

- **WHEN** the bounded list has fewer than two or more than four values, a
  duplicate or non-positive ID, a `--max-runs` mismatch, or `--loop`,
  `--run-id`, or `--enable-real-queue` is also passed
- **THEN** the command raises a sanitized error before adapter creation
- **AND** no run is mutated

#### Scenario: Restart and rebootstrap before a later claim

- **WHEN** four selected jobs run with a jobs-per-session threshold of three
- **THEN** jobs one through three reuse the initial bootstrap
- **AND** restart plus rebootstrap completes before the fourth claim
- **AND** a restart failure leaves the fourth selected row queued and untouched

#### Scenario: Continuous real queue is default-off

- **WHEN** `--real-handle --loop` is passed without `--enable-real-queue`
- **THEN** the command fails before adapter/browser creation and before a claim
- **AND** `--enable-real-queue` is valid only with both `--real-handle` and
  `--loop` and forbids `--run-id`, `--validation-run-id`, and `--max-runs`
- **AND** the opt-in reuses the existing queue, locking, readiness, and shutdown
  paths without creating a new worker, queue, or deployment default

#### Scenario: Real multi-run output is sanitized across every surface

- **WHEN** bounded or continuous real mode emits operational messages on any
  success or failure branch (admissions, demographics, full-sync, persistence,
  retry, terminal failure, follow-up, race, or unsupported intent)
- **THEN** complete stdout and stderr use only bounded ordinals or fixed
  continuous labels, counts, stage names, and normalized reasons
- **AND** they contain NO claimed run primary key and NO auto-enqueued follow-up
  primary key (no `Run #<n>` or `run #<n>` label pattern)
- **AND** they contain no patient/source identifiers, clinical content, URLs,
  credentials, cookies, HTML, or PDF data
- **AND** stub and explicitly selected single-smoke messages remain unchanged

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

#### Scenario: Real handle uses action navigation for JSP legacy UI

- **GIVEN** the real legacy system does not expose reloadable patient,
  admission, or evolution URLs
- **WHEN** the persistent worker runs with `--real-handle`
- **THEN** admissions and evolutions are reached through action-based
  Playwright navigation modeled after the known legacy scripts
- **AND** the real path does not require admissions or evolutions URL templates
  to process a guarded single-run smoke
- **AND** it reuses the already-open persistent browser session/context

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
