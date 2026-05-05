# summary-llm-traceability Specification

## Purpose

TBD - created by archiving change 2026-05-03-summary-two-phase-pipeline-traceability. Update Purpose after archive.

## Requirements

### Requirement: Every LLM call is fully traceable

The system SHALL persist a complete execution record for each phase call in a
summary pipeline run.

#### Scenario: Persist full trace for successful call

- **WHEN** a phase call succeeds
- **THEN** the system stores user, admission, phase, provider/model,
  prompt version, prompt snapshot, request payload, response payload,
  tokens, latency, and cost
- **AND** prompt is stored as textual snapshot (not prompt-template FK)
- **AND** for standard prompts, `prompt_version` references the file version
  identifier used in execution

#### Scenario: Persist full trace for failed call

- **WHEN** a phase call fails
- **THEN** the system stores the same trace context
- **AND** stores error details and terminal status

### Requirement: Cost is tracked by phase and total run

The system SHALL compute and persist costs by phase and aggregate run total.

#### Scenario: Store cost by phase

- **WHEN** phase 1 and phase 2 complete
- **THEN** phase 1 and phase 2 costs are persisted independently in USD

#### Scenario: Full phase-1 reuse stores zero phase-1 cost

- **WHEN** phase 1 is reused/skipped due to valid prior base
- **THEN** phase 1 cost is stored as zero
- **AND** total run cost equals phase 2 cost

### Requirement: BRL display uses latest available exchange rate

The system SHALL convert USD costs to BRL using the most recent available
USD/BRL rate at view time.

#### Scenario: Convert with current available rate

- **WHEN** user opens logs or run cost view
- **THEN** UI shows USD stored values
- **AND** shows BRL values converted with latest available rate

#### Scenario: Missing today rate falls back to latest stored rate

- **WHEN** no rate exists for current date
- **THEN** system uses latest previously stored USD/BRL rate
- **AND** conversion remains available without blocking the page

### Requirement: Exchange-rate provider fallback enforces API-key policy

The system SHALL fetch daily USD/BRL from `frankfurter.dev` as primary source
without API key, and use `exchangerate-api.com` as fallback only when its API
key is configured.

#### Scenario: Primary succeeds without API key

- **WHEN** daily sync runs and `frankfurter.dev` is available
- **THEN** rate is collected successfully without API key

#### Scenario: Fallback requires configured API key

- **WHEN** primary source fails and fallback API key is missing
- **THEN** fallback call is not attempted
- **AND** system keeps using latest stored rate until next successful sync

### Requirement: Public and admin trace views are separated

The system SHALL expose two traceability views with different data sensitivity.

#### Scenario: Public view hides sensitive content

- **WHEN** authenticated user accesses public logs
- **THEN** prompt text and raw payload/response are not displayed

#### Scenario: Admin view shows full details

- **WHEN** admin accesses sensitive logs
- **THEN** prompt text and raw payload/response are displayed
