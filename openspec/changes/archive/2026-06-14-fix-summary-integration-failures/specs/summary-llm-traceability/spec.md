# Summary LLM Traceability Delta

## ADDED Requirements

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
