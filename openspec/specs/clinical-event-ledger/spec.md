# clinical-event-ledger Specification

## Purpose

TBD - created by archiving change fundacao-modelo-eventos-e-ingestao-evolucoes. Update Purpose after archive.

## Requirements

### Requirement: Canonical clinical event record

The system SHALL persist clinical evolutions in a canonical event model containing standardized queryable columns and raw source payload for audit.

#### Scenario: Persist canonical and raw data together

- **WHEN** a clinical evolution is ingested
- **THEN** the system stores canonical fields (`happened_at`, `signed_at`, `author_name`, `profession_type`, `content_text`, `signature_line`) and the full `raw_payload_json`

### Requirement: Event identity and deduplication

The system MUST compute and persist a deterministic `event_identity_key` per clinical event for idempotent ingestion.

#### Scenario: Ignore duplicate event in repeated run

- **WHEN** a new ingestion receives an event with an `event_identity_key` that already exists and the same `content_hash`
- **THEN** the system does not create a duplicate clinical event

### Requirement: Event revision detection

The system MUST detect content drift for the same event identity using `content_hash`.

#### Scenario: Register revision when content changes

- **WHEN** an event is received with the same `event_identity_key` and a different `content_hash`
- **THEN** the system records a new revision state while preserving event identity traceability

### Requirement: Ingestion run traceability

The system SHALL link each ingested event to its ingestion execution context.

#### Scenario: Link event to run

- **WHEN** an event is persisted during an ingestion execution
- **THEN** the event references the corresponding `IngestionRun` identifier for operational traceability
