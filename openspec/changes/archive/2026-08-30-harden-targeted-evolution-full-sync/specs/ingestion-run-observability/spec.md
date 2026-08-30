## ADDED Requirements

### Requirement: Targeted evolution extraction exposes sanitized substeps

Ingestion run observability SHALL persist real-handle evolution progress using a
closed set of substep names and statuses and MUST NOT persist or emit dynamic
source or patient context with those transitions.

#### Scenario: Successful source substep is recorded

- **WHEN** targeted evolution extraction completes a defined source substep
- **THEN** the run records the substep name, start/end timestamps and
  `succeeded` status
- **AND** the name belongs to the closed evolution substep enum

#### Scenario: Failed source substep is localized

- **WHEN** a defined evolution source substep fails
- **THEN** the run records that substep as `failed`
- **AND** the existing run failure taxonomy remains the source of the normalized
  reason
- **AND** no raw exception text is added to substep details

#### Scenario: Substep telemetry is sanitized

- **WHEN** evolution progress is persisted or logged
- **THEN** it contains no patient or admission identifier, date interval,
  clinical text, URL, selector, HTML, PDF content, credential, cookie or raw
  exception

#### Scenario: Optional telemetry does not change extraction outcome

- **WHEN** no progress callback is supplied by a stub/test adapter caller
- **THEN** existing extraction behavior remains available
- **AND** no alternative navigation or persistence path is selected

### Requirement: Chunk progress is observable through aggregate counters

Ingestion run observability SHALL expose aggregate targeted chunk progress even
when a later chunk causes the run to be retried or fail terminally.

#### Scenario: Partial run retains committed progress

- **WHEN** one or more chunks commit and a later chunk fails
- **THEN** run metrics retain cumulative committed event counters
- **AND** stage details expose `chunks_planned`, `chunks_committed` and
  `chunks_failed`
- **AND** the failed chunk is localized without storing its date bounds or
  patient context

#### Scenario: Completed run reports aggregate chunk totals

- **WHEN** all planned targeted chunks finish
- **THEN** the extraction and persistence metrics report committed chunk and
  processed-event totals
- **AND** totals agree with the run's cumulative event counters

### Requirement: Deferred automatic full-sync remains observable

Ingestion run observability SHALL expose automatic deferment through existing
queued status and `next_retry_at` fields without introducing sensitive guard
state.

#### Scenario: Operator distinguishes deferred from immediately due work

- **WHEN** an automatic `full_sync` is queued under the bounded guard
- **THEN** its future `next_retry_at` is available to operational inspection
- **AND** no patient identifier or raw failure is required to explain why the
  worker has not claimed it
