# census-extraction-completeness Specification

## Purpose

Ensure census extractions are validated for sector coverage completeness
before any snapshot processing or batch creation, with safe aggregate
coverage metrics and conservative failure handling.

## Requirements

### Requirement: Census extraction enforces minimum sector coverage

The system SHALL reject a census extraction as incomplete when the extracted
snapshot contains fewer than 40 distinct sectors, or when the extraction
summary does not establish complete coverage of discovered sectors without
sector or pagination failures. An explicitly limited diagnostic scope MUST
NOT be accepted as a full operational census.

#### Scenario: Complete extraction is accepted

- **WHEN** `extract_census` parses a census CSV
- **AND** the parsed rows contain at least 40 distinct non-empty sectors
- **AND** the matching extraction summary establishes full discovery scope,
  completion of every requested sector and no unresolved failures
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

#### Scenario: One failed sector remains after forty successful sectors

- **WHEN** the CSV contains rows from at least 40 sectors
- **BUT** another discovered sector failed or has incomplete pagination
- **THEN** the extraction is rejected despite meeting the numeric threshold
- **AND** no snapshots, processing batch or patient ingestion runs are
  published from that rejected extraction

#### Scenario: Limited diagnostic scope reaches the numeric threshold

- **WHEN** extraction intentionally selects only part of the discovered scope
- **AND** that subset still contains at least 40 non-empty sectors
- **THEN** it is identified as limited
- **AND** it is not accepted as a full operational census

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

### Requirement: Extraction completion is accompanied by a verifiable summary

A completed extraction SHALL provide a versioned, aggregate-safe summary of
discovered, selected, processed, empty and failed sectors, emitted row count
and scope limitation. The ingestion boundary MUST validate that summary
against the delivered data before persisting snapshots.

#### Scenario: Empty sectors are processed successfully

- **WHEN** a requested sector returns an explicit valid empty-table result
- **THEN** it counts as processed and empty, not failed
- **AND** it does not fabricate rows to satisfy minimum sector coverage

#### Scenario: Summary is absent or inconsistent

- **WHEN** the summary is missing, malformed, incomplete or has a row count
  inconsistent with the delivered CSV
- **THEN** ingestion rejects the extraction before persisting any snapshots
- **AND** the previously accepted census remains available

#### Scenario: Subprocess exits successfully with partial metadata

- **WHEN** the extraction subprocess exits with code zero
- **BUT** its summary indicates missing sectors or unresolved failures
- **THEN** the ingestion boundary rejects that result
- **AND** exit code zero alone is not sufficient evidence of completeness

#### Scenario: Summary and stage metrics preserve privacy

- **WHEN** completion metadata is written or copied into stage metrics
- **THEN** it contains only structural counters, scope flags and categorized
  failure reasons
- **AND** no raw patient data, source timestamps or credentials are included
