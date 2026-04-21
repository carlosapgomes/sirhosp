# evolution-ingestion-on-demand Specification

## Purpose
TBD - created by archiving change fundacao-modelo-eventos-e-ingestao-evolucoes. Update Purpose after archive.
## Requirements
### Requirement: On-demand ingestion by patient and period

The system SHALL provide an ingestion flow that can be triggered on demand for a selected patient and requested time interval.

#### Scenario: Trigger ingestion for missing patient data

- **WHEN** an authenticated user requests import for a patient not yet mirrored in SIRHOSP
- **THEN** the system executes ingestion for that patient and requested period and persists resulting data in the canonical model

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

