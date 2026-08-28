# persistent-session-ingestion-worker Delta Specification

## MODIFIED Requirements

### Requirement: Admissions-only parity

The persistent worker SHALL persist a valid admissions snapshot and follow-up
work with the same observable semantics as the current worker, SHALL reject an
empty snapshot for a run linked to a census/recovery batch, and SHALL avoid
creating a second demographics run already owned by that batch.

#### Scenario: Admissions-only persists and schedules batch follow-up

- **WHEN** a batch-bound `admissions_only` run captures a valid non-empty
  snapshot
- **THEN** patient and admissions are upserted through the canonical services
- **AND** seen, created, and updated counters reflect database outcomes
- **AND** the most-recent-admission full-sync is enqueued with the same batch
- **AND** no additional demographics follow-up is enqueued
- **AND** no positive created counter is recorded without persistence

#### Scenario: Standalone admissions-only preserves demographics follow-up

- **WHEN** a standalone `admissions_only` run captures a valid snapshot
- **THEN** patient and admissions are upserted through the canonical services
- **AND** demographics and full-sync follow-ups are enqueued under the existing
  standalone conditions

#### Scenario: Batch-bound empty snapshot fails closed

- **WHEN** an admissions capture linked to a census/recovery batch returns an
  empty normalized snapshot
- **THEN** the run fails or follows the existing retry policy with a sanitized
  normalized reason
- **AND** no Patient or Admission is persisted from that empty result
- **AND** no successful admissions stage or positive counter is recorded
- **AND** no demographics or full-sync follow-up is enqueued

#### Scenario: Standalone empty snapshot remains explicit

- **WHEN** an admissions synchronization without a batch returns a valid empty
  snapshot
- **THEN** the existing explicit no-admissions outcome remains available
- **AND** no evolution extraction candidate is created

### Requirement: Real persistent handle contract supports legacy data extraction

The persistent-session worker SHALL use a real Playwright session handle that
provides admission and evolution data from the legacy UI without relying on
fake-only synthetic containers or reparsing iframe data from the top-level page.

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

#### Scenario: Snapshot read from iframe survives adapter handoff

- **WHEN** action navigation reads the admissions table inside `frame_pol`
- **AND** the concrete wrapped handle has no fake-only `set_html()` method
- **THEN** the bridge retains the normalized snapshot in job-scoped memory
- **AND** `get_page_html()` exposes that exact snapshot to the adapter
- **AND** the bridge does not attempt to recover iframe rows from top-level
  `page.content()`
- **AND** it does not alter the real page DOM

#### Scenario: Snapshot state cannot cross a job boundary

- **WHEN** navigation fails, cleanup runs, a new navigation starts, the browser
  restarts, bootstrap runs, or the bridge shuts down
- **THEN** any cached admissions snapshot is cleared
- **AND** a later patient cannot receive data captured for an earlier patient

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

- **WHEN** the real handle cannot satisfy the legacy data contract
- **THEN** the persistent worker is stopped from forward rollout
- **AND** the blocker is reported without source or patient data

#### Scenario: Persistent full-sync succeeds after blockers are resolved

- **WHEN** the real handle contract and shared ingestion service are available
- **AND** a persistent full-sync run extracts evolutions successfully
- **THEN** the run persists events through the shared service
- **AND** lifecycle fields, stage metrics, counters, and failure semantics match
  the current worker's externally visible behavior
