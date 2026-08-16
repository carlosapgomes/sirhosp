# ingestion-run-observability Specification

## ADDED Requirements

### Requirement: Census extraction coverage is observable

The system SHALL expose safe aggregate coverage metrics for census extraction
runs so operators can diagnose partial extractions without accessing patient
identifiers or clinical content.

#### Scenario: Accepted extraction stores coverage metrics

- **WHEN** a `census_extraction` run succeeds
- **THEN** its stage metrics include the number of persisted rows
- **AND** they include the number of distinct sectors observed
- **AND** they include the minimum sector threshold used for acceptance
- **AND** metric details do not include patient names, patient record numbers,
  credentials or clinical text

#### Scenario: Rejected extraction stores coverage metrics

- **WHEN** a `census_extraction` run is rejected for insufficient sector
  coverage
- **THEN** its failure metadata identifies the failure as a payload or coverage
  validation problem
- **AND** its stage metrics include the observed sector count
- **AND** they include the minimum sector threshold used for rejection
- **AND** metric details do not include patient names, patient record numbers,
  credentials or clinical text

#### Scenario: Operator can distinguish partial extraction

- **WHEN** an operator inspects the recent `census_extraction` runs or command
  output
- **THEN** the partial extraction failure is distinguishable from timeout,
  source unavailability and unexpected exceptions
- **AND** the diagnostic information is limited to aggregate operational values
