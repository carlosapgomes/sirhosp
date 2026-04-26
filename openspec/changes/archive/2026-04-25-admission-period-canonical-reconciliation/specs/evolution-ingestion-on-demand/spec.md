# evolution-ingestion-on-demand Specification

## MODIFIED Requirements

### Requirement: Execution semantics for admissions and evolutions stages

The ingestion flow SHALL preserve admissions after failures and ensure reruns converge to a single admission identity for the same patient/period.

#### Scenario: Preserve admissions when evolutions extraction fails later

- **WHEN** admissions snapshot was captured and persisted
- **AND** evolutions extraction fails afterwards
- **THEN** persisted admissions remain stored
- **AND** the run transitions to `failed`
- **AND** a later rerun for the same patient/admission period must reuse the same admission mirror record

## ADDED Requirements

### Requirement: Reruns with volatile source admission key converge to one mirrored admission

The ingestion flow MUST avoid multiplying admission rows when source connector emits different admission keys for the same period.

#### Scenario: Same period, different source admission key across reruns

- **WHEN** two or more runs capture the same patient admission period
- **AND** source `admission_key` differs between runs
- **THEN** the system keeps a single mirrored admission for that patient/period
- **AND** any extracted events stay associated to that canonical admission
