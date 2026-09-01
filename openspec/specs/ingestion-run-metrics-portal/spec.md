# ingestion-run-metrics-portal Specification

## Purpose

Defines the authenticated services-portal ingestion metrics surfaces: dashboard cards, drill-down, batch history and operational filtering.

## Requirements

### Requirement: Dashboard shows ingestion operational metric cards

The portal SHALL display ingestion operational metrics in dashboard cards for a configurable recent window.

#### Scenario: Show aggregated metrics on dashboard

- **WHEN** an authenticated user opens the dashboard
- **THEN** the dashboard shows cards with aggregated ingestion metrics for the default time window
- **AND** cards include at least total runs, success rate, timeout rate, and average execution time

#### Scenario: Empty window still renders cards

- **WHEN** an authenticated user opens the dashboard and no runs exist in the selected window
- **THEN** the dashboard renders the same metric cards with zero/default values
- **AND** the page shows no application error

### Requirement: Dashboard provides drill-down to ingestion metrics page

The dashboard MUST provide a direct navigation action from ingestion metric cards to a dedicated metrics page.

#### Scenario: Navigate from dashboard card to metrics page

- **WHEN** an authenticated user clicks the ingestion metrics card (or CTA) on dashboard
- **THEN** the system navigates to the ingestion metrics page
- **AND** the default filter window is pre-applied

### Requirement: Ingestion metrics page supports operational filtering

The portal SHALL provide filtering and tabular visualization of ingestion runs for operational analysis.

#### Scenario: Filter runs by status and intent

- **WHEN** user applies filters by period, status, and intent on the metrics page
- **THEN** the run list updates to include only matching runs
- **AND** aggregated summary values reflect the filtered dataset

#### Scenario: Filter runs by failure category

- **WHEN** user filters by failure category
- **THEN** only failed runs with the selected category are listed
- **AND** timeout-related metrics reflect the filtered set

### Requirement: Ingestion metrics page is authentication-protected

Operational metrics pages MUST require authenticated access.

#### Scenario: Anonymous access to metrics page

- **WHEN** an anonymous user accesses the ingestion metrics page route
- **THEN** the user is redirected to login

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

### Requirement: Batch metrics separate findings from technical failures

The authenticated ingestion metrics portal SHALL aggregate allowlisted patient
flow outcomes separately from terminal technical failures without changing the
persisted batch status.

#### Scenario: Succeeded batch contains recognized findings

- **WHEN** the selected/latest batch is persisted as succeeded and contains one
  or more recognized patient-flow outcomes
- **THEN** the portal displays `Concluído com achados`
- **AND** shows aggregate finding counts by allowlisted label
- **AND** does not call those outcomes technical failures

#### Scenario: Failed batch contains findings and failures

- **WHEN** a failed batch contains recognized outcomes and terminal failed runs
- **THEN** the portal displays `Falha parcial`
- **AND** shows separate totals for operational findings and technical failures

#### Scenario: Batch has no findings

- **WHEN** a batch contains no recognized patient-flow outcome
- **THEN** existing success/failure presentation remains
- **AND** no empty finding card or misleading derived status is required

#### Scenario: Metrics remain aggregate and authorized

- **WHEN** metrics render findings in summary/history/detail
- **THEN** they expose only counts, codes/labels and batch-level status
- **AND** do not add patient record, name, encounter date, professional,
  clinical text or source row values
- **AND** anonymous access remains redirected to login

### Requirement: Technical full-sync failures remain visible beside findings

The portal MUST preserve normalized technical failure reasons even when the
same patient currently qualifies for an operational finding.

#### Scenario: Suspected residual also has timeout

- **WHEN** a patient qualifies as suspected residual and its full-sync failed
  with timeout
- **THEN** aggregate technical metrics continue counting that timeout
- **AND** the finding does not rewrite the run or batch history

### Requirement: Patients failure tab shows current flow findings

The ingestion metrics patients tab SHALL display, for each patient in the
"final failure" list, the patient's current patient-flow finding label when
one exists, using the shared bulk classifier without new patient data.

#### Scenario: Failure row displays current finding label

- **WHEN** the latest finished census batch has a final failure for a patient
  who currently has a patient-flow finding
- **THEN** the patients tab row displays that finding's label with the same
  accessible badge treatment used by the census surfaces
- **AND** review-required findings keep the manual-review warning treatment

#### Scenario: No finding renders no placeholder

- **WHEN** a listed failure patient has no current finding — including when the
  patient is no longer in the current census
- **THEN** the row renders an empty situation cell without error or placeholder
  text

#### Scenario: Classification is bulk and bounded

- **WHEN** the patients tab renders with many failure patients
- **THEN** current findings are resolved with the shared bulk classifier in a
  bounded number of queries independent of the row count
- **AND** no query is performed from the template loop

#### Scenario: Authorization and data minimization are preserved

- **WHEN** an anonymous user requests the ingestion metrics page
- **THEN** the existing login redirection is preserved
- **AND** the tab exposes only the closed finding label — no new identifier,
  date, clinical text or stage detail beyond what the table already shows
