# ingestion-run-metrics-admin Specification

## ADDED Requirements

### Requirement: Django Admin lists ingestion runs with operational metric columns

The system SHALL expose ingestion runs in Django Admin with lifecycle and outcome metrics.

#### Scenario: Admin list shows key operational fields

- **WHEN** an authenticated admin opens the ingestion run changelist
- **THEN** the list shows status, intent, queue timestamp, processing start, finish, and duration fields
- **AND** the list shows failure category and timeout indicator when available

### Requirement: Django Admin supports filtering for run diagnostics

The system SHALL provide admin filters for common operational investigations.

#### Scenario: Filter runs by status, intent, and timeout

- **WHEN** admin applies filters by status, intent, and timeout indicator
- **THEN** only matching runs are displayed in changelist

#### Scenario: Filter runs by failure category and date window

- **WHEN** admin applies failure category and date filters
- **THEN** changelist returns only matching runs in the selected period

### Requirement: Django Admin run detail shows per-stage metrics

The system SHALL expose stage execution metrics in run detail view for diagnostics.

#### Scenario: Inspect stage metrics in admin detail

- **WHEN** admin opens a specific ingestion run detail page
- **THEN** the page displays persisted stage entries with stage name, status, start, finish, and duration
- **AND** stage-level error context is visible when a stage failed
