# Capability: clinical-event-full-text-search

## ADDED Requirements

### Requirement: Full text search over clinical event content

The system SHALL provide full text search over canonical clinical event content text.

#### Scenario: Search by free-text query

- **WHEN** a user submits a free-text query for clinical content
- **THEN** the system returns matching clinical events ranked by text relevance

### Requirement: Operational filters for search

The system SHALL support search filtering by patient, admission, period, and profession type.

#### Scenario: Apply combined filters

- **WHEN** a user provides a text query with patient, period, and profession filters
- **THEN** the system returns only events that satisfy all provided filters

### Requirement: Search response traceability

The system MUST return identifiers necessary to open original event context.

#### Scenario: Trace search result to patient timeline

- **WHEN** a search result is displayed
- **THEN** the result includes event identifier, patient identifier, admission identifier, and event datetime for timeline navigation
