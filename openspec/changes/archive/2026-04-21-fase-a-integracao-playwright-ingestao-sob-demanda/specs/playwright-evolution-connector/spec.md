<!-- markdownlint-disable MD013 -->
# ADDED Specification: playwright-evolution-connector

## Requirements

### Requirement: Production extraction adapter contract

The system SHALL provide a production extraction adapter for clinical evolutions that returns a normalized collection compatible with canonical ingestion.

#### Scenario: Extract evolutions by patient and period

- **WHEN** the ingestion worker invokes the Playwright connector with patient record and date interval
- **THEN** the connector returns evolution items with required source fields (`createdAt`, `signedAt`, `content`, `createdBy`, `type`, `signatureLine`, `admissionKey`, `chunkStart`, `chunkEnd`)

### Requirement: Transition-safe integration with existing MVP extractor

The system MUST allow transitional execution through the current MVP extractor while preserving the same adapter interface.

#### Scenario: Execute transitional extractor implementation

- **WHEN** the production adapter is configured in transitional mode
- **THEN** it can invoke the existing extractor process and map returned JSON to the internal adapter contract

### Requirement: Connector failure mapping

The system SHALL map technical extraction failures to structured ingestion errors.

#### Scenario: Handle extractor failure

- **WHEN** Playwright execution fails, times out, or returns invalid JSON
- **THEN** the connector raises a typed extraction error and the run is marked failed with actionable diagnostics
