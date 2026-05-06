# admission-progressive-summary Specification (delta)

## MODIFIED Requirements

### Requirement: Phase 1 supports reuse and incremental update

The workflow MUST avoid recomputation of phase 1 when previously computed
base is still valid for the requested horizon. When phase 1 runs (not
reused), cost and token usage SHALL be captured per chunk and accumulated
into the pipeline run.

#### Scenario: Full phase-1 reuse yields zero phase-1 cost

- **WHEN** canonical base already covers the same period/cutoff
- **THEN** phase 1 is marked as reused/skipped
- **AND** phase 1 cost is persisted as zero

#### Scenario: Open admission with new events updates canonical phase incrementally

- **WHEN** admission remains open and new events exist after prior coverage
- **THEN** phase 1 runs in incremental update mode
- **AND** each chunk's token usage and cost are captured in
  `AdmissionSummaryVersion`
- **AND** phase 2 renders the final output from the updated base

#### Scenario: Phase-1 cost accumulates across chunks

- **WHEN** phase 1 runs with 3 chunks, each returning provider cost
- **THEN** the `SummaryPipelineRun.phase1_cost_total` equals the sum of
  costs from all 3 chunks
- **AND** the `SummaryPipelineStepRun` for phase 1 records total
  `input_tokens` and `output_tokens` aggregated across all chunks
