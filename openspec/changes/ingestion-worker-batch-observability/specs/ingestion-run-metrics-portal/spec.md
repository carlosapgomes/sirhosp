# ingestion-run-metrics-portal Specification

## MODIFIED Requirements

### Requirement: Ingestion metrics page exposes latest batch worker efficiency

The portal SHALL expose observed worker and throughput metrics for the latest
finished census execution batch.

#### Scenario: Latest finished batch has runs and attempts

- **WHEN** an authenticated user opens the ingestion metrics page
- **AND** there is a latest finished `CensusExecutionBatch`
- **THEN** the page exposes the batch total jobs by terminal status
- **AND** it exposes the number of distinct observed worker labels
- **AND** it exposes observed peak concurrency based on attempt overlap
- **AND** it exposes observed average concurrency for the batch drain window
- **AND** it exposes throughput in jobs per minute
- **AND** it exposes average processing duration per job
- **AND** it exposes average active attempt duration

#### Scenario: Latest finished batch has no worker labels

- **WHEN** the latest finished batch contains runs with empty `worker_label`
- **THEN** the page still renders without error
- **AND** the observed worker count is shown as zero or an explicit empty state
- **AND** other derivable metrics remain visible when timestamps are available

#### Scenario: No finished batch exists

- **WHEN** an authenticated user opens the ingestion metrics page
- **AND** no finished `CensusExecutionBatch` exists
- **THEN** the page renders the existing empty batch state
- **AND** all worker efficiency metrics use zero or empty-list defaults

### Requirement: Ingestion metrics page prioritizes batch history

The portal SHALL show a paginated historical table of census execution batches
as the default content of the ingestion metrics page.

#### Scenario: User opens ingestion metrics page with finished batches

- **WHEN** an authenticated user opens `/metrica-ingestao/`
- **AND** finished `CensusExecutionBatch` records exist
- **THEN** the page shows a table of batches ordered in reverse chronology
- **AND** the most recently finished batch appears first
- **AND** each row includes batch ID, status, timestamps, duration, job counts,
  observed worker metrics, concurrency metrics, throughput, and average
  durations when derivable

#### Scenario: Batch history has more rows than one page

- **WHEN** the number of finished batches exceeds the configured page size
- **THEN** the page renders pagination controls
- **AND** each page only shows its corresponding slice of batches
- **AND** ordering remains reverse chronological across pages

#### Scenario: User selects a batch from history

- **WHEN** the user clicks a batch row or batch ID in the history table
- **THEN** the system opens the ingestion metrics page with that batch selected
- **AND** the selected batch ID is available in the request, for example via
  `?batch_id=<id>`

### Requirement: Execution list is shown only for a selected batch

The portal SHALL NOT render a global list of all ingestion executions by
default; execution rows SHALL be displayed only when a specific batch is
selected.

#### Scenario: Default page does not list global executions

- **WHEN** an authenticated user opens `/metrica-ingestao/` without `batch_id`
- **THEN** the page shows the batch history table
- **AND** it does not render the global `Execuções` table of all jobs
- **AND** it provides guidance to select a batch for execution details

#### Scenario: Selected batch shows only its executions

- **WHEN** an authenticated user opens `/metrica-ingestao/?batch_id=<id>`
- **AND** the batch exists
- **THEN** the page shows execution rows for that batch only
- **AND** status, intent, and failure category filters apply within the selected
  batch only
- **AND** no executions from other batches are rendered

#### Scenario: Invalid selected batch does not leak global executions

- **WHEN** an authenticated user opens `/metrica-ingestao/?batch_id=<invalid>`
- **THEN** the page renders an empty or not-found state for the selected batch
- **AND** it does not fall back to rendering all executions globally
