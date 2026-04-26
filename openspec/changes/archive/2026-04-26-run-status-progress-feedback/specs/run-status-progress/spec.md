# run-status-progress Specification

> **Status**: Implemented ✅ (PF-1, PF-2)

## Purpose

Define progressive feedback requirements for the ingestion run status page,
exposing per-stage execution progress via HTMX polling with partial updates.

## Requirements

### Requirement: Run status page exposes stage-level progress

The run status page SHALL display per-stage execution progress using data from
`IngestionRunStageMetric`, updating automatically without full page reload.

#### Scenario: Stage progress visible during execution

- **WHEN** an authenticated user opens the run status page for a running run
  that has started stage execution
- **THEN** the page displays a progress section listing each execution stage
- **AND** completed stages show their status and duration
- **AND** the currently executing stage is visually distinct from completed
  and pending stages

#### Scenario: Progress section updates without page reload

- **WHEN** the run status page is open and the run is still in progress
- **THEN** the progress section polls the backend every few seconds
- **AND** only the progress section is updated (not the entire page)
- **AND** newly completed stages appear automatically

#### Scenario: Polling stops on terminal state

- **WHEN** the run transitions to a terminal state (`succeeded` or `failed`)
- **THEN** the progress section stops polling
- **AND** all stages show their final status

#### Scenario: Compatibility with all run intents

- **WHEN** a run of any intent (`full_admission_sync`, `admissions_only`,
  `demographics_only`, or generic) is viewed
- **THEN** the progress section shows the stages applicable to that intent
- **AND** stages not executed for that intent are not shown

### Requirement: Stage metrics are accessible via dedicated fragment endpoint

The system SHALL provide an HTTP endpoint that returns stage progress as an
HTML fragment suitable for HTMX polling.

#### Scenario: Fragment returns stage list for existing run

- **WHEN** an authenticated client requests the progress fragment for a
  valid run ID
- **THEN** the response contains an HTML fragment with stage names, statuses
  and durations
- **AND** the response status is 200

#### Scenario: Fragment returns 404 for nonexistent run

- **WHEN** an authenticated client requests the progress fragment for a
  nonexistent run ID
- **THEN** the response status is 404

#### Scenario: Fragment requires authentication

- **WHEN** an anonymous client requests the progress fragment
- **THEN** the response redirects to login

### Requirement: HTMX library is available in base template

The base template SHALL load the HTMX JavaScript library to enable
progressive enhancement of ingestion status pages.

#### Scenario: HTMX script tag present in base template

- **WHEN** any page extending the base template is rendered
- **THEN** the HTMX library script tag is included
- **AND** HTMX attributes (`hx-get`, `hx-trigger`, etc.) are functional
