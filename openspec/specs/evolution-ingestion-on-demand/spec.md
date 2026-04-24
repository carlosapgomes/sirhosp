# evolution-ingestion-on-demand Specification

## Purpose

TBD - created by archiving change fundacao-modelo-eventos-e-ingestao-evolucoes. Update Purpose after archive.
## Requirements
### Requirement: On-demand ingestion by patient and period

The system SHALL provide an ingestion flow that can be triggered on demand for a selected patient and requested time interval.

#### Scenario: Trigger ingestion for missing patient data

- **WHEN** an authenticated user requests import for a patient not yet mirrored in SIRHOSP
- **THEN** the system executes ingestion for that patient and requested period and persists resulting data in the canonical model

#### Scenario: Extract only requested evolution window while capturing admissions snapshot

- **WHEN** a user requests ingestion for a patient and interval
- **THEN** the system captures the full known admissions snapshot for that patient from the source system
- **AND** extracts evolutions only for the requested interval windows

### Requirement: Deterministic admission association for ingested evolutions

The ingestion flow MUST deterministically associate each evolution to the correct admission.

#### Scenario: Associate by admission key

- **WHEN** an ingested evolution contains a valid `admission_key`
- **THEN** the event is associated to that admission

#### Scenario: Fallback by happened_at when admission key is missing or invalid

- **WHEN** an ingested evolution has missing/invalid `admission_key`
- **THEN** the system resolves admission deterministically by `happened_at` against known admission periods
- **AND** tie-breaks are deterministic (latest matching admission start, then stable key order)

### Requirement: Execution semantics for admissions and evolutions stages

The ingestion flow SHALL enforce explicit failure semantics across admissions and evolutions stages.

#### Scenario: Fail run when admissions snapshot capture fails

- **WHEN** admissions snapshot capture fails
- **THEN** the run transitions to `failed`
- **AND** evolution extraction stage is not executed

#### Scenario: Preserve admissions when evolutions extraction fails later

- **WHEN** admissions snapshot was captured and persisted
- **AND** evolutions extraction fails afterwards
- **THEN** persisted admissions remain stored
- **AND** the run transitions to `failed`

#### Scenario: Succeed with zero evolutions after successful admissions capture

- **WHEN** admissions snapshot capture succeeds
- **AND** no evolutions are available in the requested interval
- **THEN** the run transitions to `succeeded`
- **AND** event counters remain zero

### Requirement: In-memory ingestion execution

The ingestion flow MUST support execution without requiring persisted source JSON files.

#### Scenario: Process extracted data in memory

- **WHEN** the scraper returns extracted evolution objects during a run
- **THEN** the system processes and persists those objects directly from memory buffers

### Requirement: Professional type compatibility

The ingestion flow SHALL preserve source compatibility for profession-type values while normalizing internal classification.

#### Scenario: Handle legacy profession token

- **WHEN** an evolution arrives with `type = "phisiotherapy"`
- **THEN** the system stores a compatible source value and maps to the internal physiotherapy classification without data loss

### Requirement: Timestamp normalization policy

The ingestion flow MUST normalize source timestamps without timezone offset according to institutional timezone configuration.

#### Scenario: Normalize source datetime

- **WHEN** source fields `createdAt` and `signedAt` are provided without timezone offset
- **THEN** the system persists timezone-aware datetimes normalized to the configured institutional timezone

### Requirement: Admission-first orchestration for non-mirrored patient search

The ingestion flow SHALL support an admissions-first operational path for registros not present in local mirror.

#### Scenario: Run admissions-only synchronization from missing-patient search

- **WHEN** the portal triggers admissions synchronization from a missing-patient search result
- **THEN** the worker executes admissions snapshot capture without requiring evolution extraction
- **AND** run status records completion/failure of the admissions stage

### Requirement: Evolution extraction requires known admissions

The system MUST block evolution extraction when no admissions are known for the target registro.

#### Scenario: No admissions found after synchronization

- **WHEN** admissions snapshot capture completes with zero admissions for the target registro
- **THEN** the system marks the run outcome as `no admissions found` in operational feedback
- **AND** no evolution extraction windows are scheduled

### Requirement: Admission-scoped synchronization modes

The ingestion flow SHALL support two synchronization modes after admission selection.

#### Scenario: Synchronize full admission period

- **WHEN** user selects `sincronizar internação completa`
- **THEN** extraction window is set to admission start through discharge date
- **AND** if discharge date is null, extraction window end is current date

#### Scenario: Synchronize custom period inside selected admission

- **WHEN** user selects custom period for a chosen admission
- **THEN** requested range must intersect and remain bounded by selected admission period
- **AND** out-of-bound ranges are rejected with clear validation errors

### Requirement: Long windows are chunked for source-system compatibility

Extraction execution MUST split long windows into operational chunks compatible with source-system limits.

#### Scenario: Chunk a long admission period deterministically

- **WHEN** requested extraction window is longer than 15 days
- **THEN** the connector splits execution into chunks of at most 15 days
- **AND** chunk boundaries are deterministic and include configured overlap to avoid edge losses

