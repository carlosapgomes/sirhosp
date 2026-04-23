# ingestion-run-observability Specification

## Purpose

Define visibility requirements for ingestion run lifecycle and operational metrics.

## Requirements

### Requirement: Run metrics include admissions-stage visibility

Ingestion run tracking MUST expose admissions-stage metrics in addition to event counters.

#### Scenario: Persist admissions metrics on completed run

- **WHEN** a run processes admissions snapshot and evolution extraction stages
- **THEN** the run persists admissions metrics (`admissions_seen`, `admissions_created`, `admissions_updated`)

#### Scenario: Show admissions metrics on status page

- **WHEN** user opens run status page
- **THEN** admissions metrics are displayed with event metrics for operational traceability
