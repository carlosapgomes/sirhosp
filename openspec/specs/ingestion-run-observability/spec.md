# ingestion-run-observability Specification

## Purpose

Define visibility requirements for ingestion run lifecycle, operational metrics,
failure taxonomy, and per-stage execution diagnostics.

## Requirements

### Requirement: Run metrics include lifecycle timing and counters

Ingestion run tracking MUST expose lifecycle timing, admissions-stage metrics,
and event counters.

#### Scenario: Persist lifecycle timestamps and counters on completed run

- **WHEN** a run reaches a terminal state (`succeeded` or `failed`)
- **THEN** the run persists lifecycle timestamps for queue, processing start,
  and finish
- **AND** the run persists admissions counters (`admissions_seen`,
  `admissions_created`, `admissions_updated`)
- **AND** the run persists event counters (`events_processed`,
  `events_created`, `events_skipped`, `events_revised`)

#### Scenario: Show lifecycle and counters on run status page

- **WHEN** user opens run status page
- **THEN** run status displays lifecycle timing fields (queue wait, execution
  duration, total duration)
- **AND** status displays admissions and event counters for operational traceability

### Requirement: Run intent and admission context are observable

Ingestion run tracking MUST expose operational intent metadata for
admission-first workflows.

#### Scenario: Persist run intent metadata

- **WHEN** a run is created for admission sync, full-admission sync, or
  custom-period sync
- **THEN** run metadata persists the intent type and relevant context (registro,
  admission identifier, effective date range)
- **AND** status view renders this metadata for operator traceability

### Requirement: Status guidance reflects admission-first next step

Run status UI SHALL provide explicit guidance according to admissions
synchronization outcome.

#### Scenario: Admissions sync finished with admissions available

- **WHEN** admissions sync run succeeds with one or more admissions
- **THEN** status page shows action to proceed to admission selection

#### Scenario: Admissions sync finished with zero admissions

- **WHEN** admissions sync run finishes with zero admissions found
- **THEN** status page shows explicit message that extraction is unavailable
  without admission
- **AND** no action to start evolution extraction is shown

### Requirement: Run failure outcomes are categorized for operational analysis

Ingestion run tracking MUST classify terminal failures into normalized
operational categories.

#### Scenario: Persist timeout as normalized failure category

- **WHEN** a run fails due to extractor timeout
- **THEN** run status is persisted as `failed`
- **AND** run failure category is persisted as `timeout`
- **AND** timeout flag is persisted for query/aggregation

#### Scenario: Persist non-timeout failures with category and message

- **WHEN** a run fails for non-timeout reason
- **THEN** run failure category is persisted in a normalized enum
- **AND** run error message remains available for detailed diagnostics

### Requirement: Run stage metrics are persisted for critical execution stages

Ingestion run tracking SHALL persist per-stage execution metrics for operational
diagnostics.

#### Scenario: Persist successful stage execution

- **WHEN** a run executes a critical stage (admissions capture, gap planning,
  extraction, persistence) successfully
- **THEN** the system persists stage start/end timestamps
- **AND** the system persists stage status as `succeeded`

#### Scenario: Persist failed stage execution

- **WHEN** a run fails during a critical stage
- **THEN** the system persists stage status as `failed`
- **AND** the system persists stage-level error context linked to the parent run

<!-- Added by run-status-progress-feedback. -->

### Requirement: Run status page exposes stage-level progress to users

Ingestion run tracking SHALL expose per-stage execution progress on the run
status page.

#### Scenario: Stage metrics displayed on run status

- **WHEN** an authenticated user opens the run status page
- **THEN** the page displays a progress section with per-stage execution status
- **AND** each stage shows its name, completion status, and duration
- **AND** the progress section updates automatically while the run is active

#### Scenario: Fragment endpoint returns stage progress HTML

- **WHEN** an authenticated client polls the progress fragment endpoint
- **THEN** the response contains an HTML fragment with stage names and statuses
- **AND** the fragment is suitable for HTMX partial swap

<!-- Added by ingestion-worker-batch-observability. -->

### Requirement: Worker identity is recorded when processing runs

Ingestion run tracking MUST record an operational worker label and heartbeat for
runs processed by the asynchronous ingestion worker.

#### Scenario: Worker claims a queued run

- **WHEN** `process_ingestion_runs` claims a queued `IngestionRun`
- **THEN** the run status is changed to `running`
- **AND** `worker_label` is populated with a non-empty operational identifier
- **AND** `worker_heartbeat_at` is populated with the claim time
- **AND** the identifier contains no patient data or sensitive credential

#### Scenario: Worker label environment override is available

- **WHEN** the environment variable `SIRHOSP_WORKER_LABEL` is configured
- **AND** `process_ingestion_runs` claims a queued run
- **THEN** the persisted `worker_label` is derived from that configured value
- **AND** a safe process-level suffix may be appended to avoid ambiguity

#### Scenario: Worker label fallback is available

- **WHEN** no explicit worker label environment variable is configured
- **AND** `process_ingestion_runs` claims a queued run
- **THEN** the system uses a safe fallback based on host/process information
- **AND** the run remains processable even if hostname resolution is limited

#### Scenario: Worker heartbeat is refreshed while processing

- **WHEN** `process_ingestion_runs` is processing a run
- **THEN** the worker refreshes `worker_heartbeat_at` periodically until the run
  reaches a terminal state or processing exits
- **AND** heartbeat updates do not include patient data, clinical text or
  credentials

#### Scenario: Worker stops heartbeat at terminal state

- **WHEN** a run reaches status `succeeded` or `failed`
- **THEN** the worker stops refreshing `worker_heartbeat_at`
- **AND** the terminal lifecycle fields remain available for duration metrics

### Requirement: Historical extraction services preserve ingestion run observability

Admission and death historical extraction service executions SHALL persist
`IngestionRun` lifecycle status and per-stage metrics equivalent to the existing
management command behavior.

#### Scenario: Successful admission service execution records lifecycle and stages

- **WHEN** admission extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying admission
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Successful death service execution records lifecycle and stages

- **WHEN** death extraction is executed through the service layer and succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying death
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Failed service execution records normalized failure metadata

- **WHEN** admission or death extraction fails through the service layer
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run persists a safe error message
- **AND** the run persists the normalized failure reason when it can be
  classified
- **AND** the failed stage metric includes safe diagnostic context without
  credentials

#### Scenario: Timeout service execution records timeout metadata

- **WHEN** admission or death extraction times out during source-system
  automation
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run failure reason is `timeout`
- **AND** the run timeout flag is set

### Requirement: Census and discharge extraction services preserve observability

Official census and discharge historical extraction service executions SHALL
persist `IngestionRun` lifecycle status and per-stage metrics equivalent to the
existing management command behavior.

#### Scenario: Successful official census service execution records lifecycle

- **WHEN** official census extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying official
  census extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Successful discharge service execution records lifecycle

- **WHEN** discharge extraction is executed through the service layer and
  succeeds
- **THEN** an `IngestionRun` is persisted with intent identifying discharge
  extraction
- **AND** the run reaches status `succeeded` with a finish timestamp
- **AND** successful extraction and persistence stage metrics are linked to the
  run

#### Scenario: Failed census or discharge service records failure metadata

- **WHEN** official census or discharge extraction fails through the service
  layer after an `IngestionRun` has been created
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run persists a safe error message
- **AND** the run persists the normalized failure reason when it can be
  classified
- **AND** the failed stage metric includes safe diagnostic context without
  credentials

#### Scenario: Census or discharge timeout records timeout metadata

- **WHEN** official census or discharge extraction times out during
  source-system automation
- **THEN** the linked `IngestionRun` is marked `failed`
- **AND** the run failure reason is `timeout`
- **AND** the run timeout flag is set
- **AND** the failed stage metric does not expose credential values or
  command-line credential flags

#### Scenario: Unexpected outer failure does not leave a running ingestion run

- **WHEN** official census or discharge extraction encounters an unexpected
  exception after creating an `IngestionRun`
- **THEN** the service marks the linked run as `failed`
- **AND** the service returns a structured failed extraction result with the
  linked ingestion run id

### Requirement: Historical recovery relies on extractor run observability

The historical recovery command SHALL rely on the per-extractor `IngestionRun`
records created by extractor services and SHALL NOT introduce persistent recovery
job state in this change.

#### Scenario: Successful recovery step exposes extractor ingestion run id

- **WHEN** a recovery step calls an extractor service and the service returns an
  `ExtractionResult` with an `ingestion_run_id`
- **THEN** the command-level step result retains that ingestion run id through
  the service result
- **AND** operators can inspect the corresponding extractor `IngestionRun` for
  detailed lifecycle and stage metrics

#### Scenario: Failed recovery step exposes extractor failure metadata

- **WHEN** a recovery step calls an extractor service and the service returns a
  failed `ExtractionResult`
- **THEN** the command-level step result retains the service failure reason,
  safe error message, and ingestion run id when present
- **AND** the command summary reports the step as failed

#### Scenario: Dry-run does not create ingestion runs

- **WHEN** recovery is executed with `--dry-run`
- **THEN** no extractor service is called
- **AND** no extractor `IngestionRun` is created by recovery planning

#### Scenario: No recovery job model is created

- **WHEN** this change is implemented
- **THEN** the system does not add a recovery job table, recovery attempt table,
  or migration for persistent recovery orchestration
- **AND** any future persistent recovery job state remains a separate OpenSpec
  change

### Requirement: Orchestrator logs safe operational state

Ingestion run observability SHALL support safe operator understanding of the
adaptive census orchestrator state without exposing patient data or credentials.

#### Scenario: Orchestrator waits for active queue

- **WHEN** the adaptive census orchestrator checks the queue
- **AND** active `IngestionRun` records prevent a new cycle
- **THEN** operator output includes a safe waiting reason
- **AND** it includes aggregate counts by active status when available
- **AND** it does not include patient names, clinical text, or credentials

#### Scenario: Orchestrator starts a cycle

- **WHEN** the adaptive census orchestrator starts a new census cycle
- **THEN** operator output identifies the lifecycle transition as a cycle start
- **AND** it includes non-sensitive identifiers such as run id or batch id when
  those identifiers become available

#### Scenario: Orchestrator detects stale active runs

- **WHEN** the adaptive census orchestrator detects active runs older than the
  configured stale threshold
- **THEN** operator output includes a stale-run warning
- **AND** it includes only safe operational identifiers and timestamps
- **AND** it does not mutate the stale runs
