# census-extraction-completeness Specification

## ADDED Requirements

### Requirement: Census extraction enforces minimum sector coverage

The system SHALL reject a census extraction as incomplete when the extracted
snapshot contains fewer than 40 distinct sectors.

#### Scenario: Complete extraction is accepted

- **WHEN** `extract_census` parses a census CSV
- **AND** the parsed rows contain at least 40 distinct non-empty sectors
- **THEN** the extraction is accepted for snapshot persistence
- **AND** the associated `IngestionRun` can be marked as `succeeded`

#### Scenario: Partial extraction is rejected

- **WHEN** `extract_census` parses a census CSV
- **AND** the parsed rows contain fewer than 40 distinct non-empty sectors
- **THEN** the extraction MUST be marked as `failed`
- **AND** no `CensusSnapshot` rows from that incomplete CSV are persisted
- **AND** `process_census_snapshot` MUST NOT be called by the orchestrator for
  that extraction

#### Scenario: Rejection explains the coverage threshold

- **WHEN** an extraction is rejected for insufficient sector coverage
- **THEN** the operator output includes the observed sector count
- **AND** the operator output includes the minimum required sector count
- **AND** the output does not include patient names, patient record numbers,
  credentials or clinical text

### Requirement: Census extraction records safe coverage metrics

The system SHALL record aggregate coverage metrics for accepted and rejected
census extractions.

#### Scenario: Metrics are recorded for accepted extraction

- **WHEN** `extract_census` accepts a parsed CSV
- **THEN** its stage metrics include aggregate `sector_count`
- **AND** they include aggregate `row_count`
- **AND** they include `minimum_required_sectors`
- **AND** they include a status indicating the completeness check passed

#### Scenario: Metrics are recorded for rejected extraction

- **WHEN** `extract_census` rejects a parsed CSV for insufficient sectors
- **THEN** its stage metrics include aggregate `sector_count`
- **AND** they include aggregate `row_count`
- **AND** they include `minimum_required_sectors`
- **AND** they include a status indicating the completeness check failed
- **AND** no patient-identifying fields are persisted in metric details

### Requirement: Playwright sector discovery reports aggregate coverage

The census Playwright script SHALL expose aggregate sector discovery counters in
its terminal summary so operators can distinguish a source-system failure from a
valid empty census.

#### Scenario: Script summary includes sector counters

- **WHEN** the Playwright census script finishes
- **THEN** its stdout summary includes the number of sectors discovered
- **AND** it includes the number of sectors processed
- **AND** it includes the number of sectors with extraction errors
- **AND** it includes the number of sectors that returned no patients

#### Scenario: Sector counter output is safe

- **WHEN** the Playwright script prints sector coverage counters
- **THEN** the counters are aggregate operational values
- **AND** the output does not include patient names, patient record numbers,
  credentials or clinical text
