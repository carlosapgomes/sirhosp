# summary-llm-traceability Specification

## Purpose

Define traceability requirements for summary LLM calls, costs, exchange-rate
conversion, public/admin visibility, and summary page cost display.

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

The system SHALL persist costs by phase and aggregate run total, prioritizing
real provider-reported cost in USD over token-based estimation.

#### Scenario: Store real cost by phase

- **WHEN** phase 1 and phase 2 complete and the provider returns cost in the
  API response
- **THEN** `cost_usd_reported` is persisted with the provider-returned value
- **AND** `cost_usd_estimated` is persisted with the token-based calculation
  for auditability
- **AND** `phase1_cost_total` and `phase2_cost_total` on the pipeline run
  reflect the reported cost (or estimated when reported is unavailable)

#### Scenario: Store estimated cost when provider omits cost

- **WHEN** phase 1 or phase 2 complete but the provider does NOT return
  cost in the API response
- **THEN** `cost_usd_reported` is persisted as `0.00`
- **AND** `cost_usd_estimated` is used as the effective cost for the phase
- **AND** the pipeline run total reflects the estimated cost

#### Scenario: Full phase-1 reuse stores zero phase-1 cost

- **WHEN** phase 1 is reused/skipped due to valid prior base
- **THEN** phase 1 cost is stored as zero
- **AND** total run cost equals phase 2 cost

### Requirement: Pipeline run is linked to the originating SummaryRun

The system SHALL maintain a direct reference from `SummaryPipelineRun` to the
`SummaryRun` that triggered it.

#### Scenario: Pipeline run references its SummaryRun

- **WHEN** a two-phase pipeline is executed for a `SummaryRun`
- **THEN** the resulting `SummaryPipelineRun` stores a FK to that
  `SummaryRun`
- **AND** views query the pipeline run by `summary_run` instead of
  `admission + latest`

#### Scenario: Legacy runs without pipeline

- **WHEN** a `SummaryRun` was executed without two-phase pipeline
  (legacy mode, no `--pipeline`)
- **THEN** no `SummaryPipelineRun` is linked to it
- **AND** the status page renders without cost card

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

### Requirement: Exchange-rate provider endpoints are correct at time of implementation

The system SHALL use verified, working endpoints for exchange rate providers.

#### Scenario: Primary endpoint returns valid rate

- **WHEN** daily sync runs against `api.frankfurter.dev/v1/latest`
- **THEN** rate is collected successfully without API key
- **AND** response is parsed from `data["rates"]["BRL"]`

#### Scenario: Fallback parses correct response key

- **WHEN** primary source fails and fallback is configured with valid API key
- **THEN** fallback calls `exchangerate-api.com` and parses
  `data["conversion_rates"]["BRL"]`
- **AND** rate is persisted with `provider="exchangerate_api"`

### Requirement: Public and admin trace views are separated

The system SHALL expose two traceability views with different data sensitivity.

#### Scenario: Public view hides sensitive content

- **WHEN** authenticated user accesses public logs
- **THEN** prompt text and raw payload/response are not displayed

#### Scenario: Admin view shows full details

- **WHEN** admin accesses sensitive logs
- **THEN** prompt text and raw payload/response are displayed

### Requirement: Summary pages expose linked pipeline cost visibility

The summary status and read pages SHALL display cost information from the
`SummaryPipelineRun` linked to the displayed `SummaryRun` when that linked
pipeline run exists.

#### Scenario: Status page shows linked pipeline costs

- **WHEN** an authenticated user opens the status page for a `SummaryRun` with a
  linked successful `SummaryPipelineRun`
- **THEN** the page displays phase 1, phase 2, and total USD costs
- **AND** the page displays BRL conversion when an exchange rate is available
- **AND** the page shows a clear fallback when no exchange rate is available

#### Scenario: Read page shows linked pipeline total cost

- **WHEN** an authenticated user opens the read page for a `SummaryRun` with a
  linked successful `SummaryPipelineRun`
- **THEN** the page displays the total USD cost
- **AND** the page displays BRL conversion when an exchange rate is available
- **AND** the page shows a clear fallback when no exchange rate is available

#### Scenario: Phase 1 reuse remains visible

- **WHEN** the linked pipeline run reused phase 1
- **THEN** the status and read pages expose an operator-visible reuse indicator
- **AND** phase 1 cost is displayed as zero

### Requirement: Summary status page preserves admission context

The summary status page SHALL display enough admission context for an operator
to identify the run being viewed.

#### Scenario: Status page shows admission reference

- **WHEN** an authenticated user opens the status page for a `SummaryRun`
- **THEN** the page displays the patient name
- **AND** the page displays the admission source reference when available
