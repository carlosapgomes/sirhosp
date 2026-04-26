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
- **THEN** the run persists lifecycle timestamps for queue, processing start, and finish
- **AND** the run persists admissions counters (`admissions_seen`, `admissions_created`, `admissions_updated`)
- **AND** the run persists event counters (`events_processed`, `events_created`, `events_skipped`, `events_revised`)

#### Scenario: Show lifecycle and counters on run status page

- **WHEN** user opens run status page
- **THEN** run status displays lifecycle timing fields (queue wait, execution duration, total duration)
- **AND** status displays admissions and event counters for operational traceability

### Requirement: Run intent and admission context are observable

Ingestion run tracking MUST expose operational intent metadata for admission-first workflows.

#### Scenario: Persist run intent metadata

- **WHEN** a run is created for admission sync, full-admission sync, or custom-period sync
- **THEN** run metadata persists the intent type and relevant context (registro, admission identifier, effective date range)
- **AND** status view renders this metadata for operator traceability

### Requirement: Status guidance reflects admission-first next step

Run status UI SHALL provide explicit guidance according to admissions synchronization outcome.

#### Scenario: Admissions sync finished with admissions available

- **WHEN** admissions sync run succeeds with one or more admissions
- **THEN** status page shows action to proceed to admission selection

#### Scenario: Admissions sync finished with zero admissions

- **WHEN** admissions sync run finishes with zero admissions found
- **THEN** status page shows explicit message that extraction is unavailable without admission
- **AND** no action to start evolution extraction is shown

### Requirement: Run failure outcomes are categorized for operational analysis

Ingestion run tracking MUST classify terminal failures into normalized operational categories.

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

Ingestion run tracking SHALL persist per-stage execution metrics for operational diagnostics.

#### Scenario: Persist successful stage execution

- **WHEN** a run executes a critical stage (admissions capture, gap planning, extraction, persistence) successfully
- **THEN** the system persists stage start/end timestamps
- **AND** the system persists stage status as `succeeded`

#### Scenario: Persist failed stage execution

- **WHEN** a run fails during a critical stage
- **THEN** the system persists stage status as `failed`
- **AND** the system persists stage-level error context linked to the parent run
