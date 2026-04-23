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
