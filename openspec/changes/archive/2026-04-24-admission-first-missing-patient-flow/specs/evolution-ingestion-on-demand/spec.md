# evolution-ingestion-on-demand Specification

## ADDED Requirements

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
