# summary-llm-traceability Specification

## Purpose

TBD - created by archiving change 2026-05-03-summary-two-phase-pipeline-traceability. Updated by change real-provider-cost-and-exchange-fixes-2026-05-05.

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
