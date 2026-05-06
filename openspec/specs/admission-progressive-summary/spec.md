# admission-progressive-summary Specification

## Purpose

TBD - created by archiving change 2026-05-03-summary-two-phase-pipeline-traceability. Update Purpose after archive.

## Requirements

### Requirement: Summary execution uses two internal phases

The system SHALL execute summary generation as a two-phase pipeline while
keeping a simple user flow.

#### Scenario: Execute canonical phase and render phase

- **WHEN** user requests summary generation/update/regeneration
- **THEN** the system executes phase 1 (canonical base)
- **AND** executes phase 2 (final render) using phase 1 output

### Requirement: Canonical phase is fixed by system configuration

Phase 1 MUST use system-defined provider/model/prompt and is not user-editable.

#### Scenario: User config affects only phase 2

- **WHEN** user opens summary configuration page
- **THEN** user can choose model/prompt only for phase 2
- **AND** phase 1 remains fixed by environment configuration

### Requirement: Standard prompts are loaded from versioned files

The system SHALL store phase-1 and phase-2 default prompts in versioned files
within the repository (not in database).

#### Scenario: Phase-1 standard prompt is loaded from file

- **WHEN** phase 1 executes
- **THEN** system loads prompt from configured versioned file path
- **AND** uses this content as canonical phase prompt

#### Scenario: Phase-2 standard prompt is loaded from file

- **WHEN** user selects standard prompt mode for phase 2
- **THEN** system loads default phase-2 prompt from versioned file
- **AND** uses this content as render-phase prompt

### Requirement: Phase 1 supports reuse and incremental update

The workflow MUST avoid recomputation of phase 1 when previously computed base
is still valid for the requested horizon. When phase 1 runs (not reused), cost
and token usage SHALL be captured per chunk and accumulated into the pipeline
run.

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

### Requirement: Phase-2 prompt can be standard or custom for all users

All authenticated users SHALL be able to run phase 2 with default prompt or
custom prompt text.

#### Scenario: Run phase 2 with standard prompt

- **WHEN** user selects standard prompt mode
- **THEN** phase 2 uses system default prompt template

#### Scenario: Run phase 2 with custom prompt

- **WHEN** user selects custom prompt mode and submits prompt text
- **THEN** phase 2 uses submitted prompt text
- **AND** prompt snapshot is persisted for traceability

#### Scenario: Run phase 2 with previously saved custom prompt

- **WHEN** user selects a saved custom prompt from prompt library
- **THEN** phase 2 uses the selected prompt content
- **AND** the execution persists prompt snapshot text (not FK reference)

### Requirement: Phase-2 custom prompt can be persisted with metadata

The system SHALL allow users to persist custom prompts with title and
visibility for reuse in future sessions.

#### Scenario: Persist a new private custom prompt

- **WHEN** user submits custom prompt with `salvar prompt` enabled,
  valid title, and `público` disabled
- **THEN** prompt is stored as private for the owner
- **AND** becomes available in prompt selection for future sessions

#### Scenario: Persist a new public custom prompt

- **WHEN** user submits custom prompt with `salvar prompt` enabled,
  valid title, and `público` enabled
- **THEN** prompt is stored as public
- **AND** becomes visible to other authenticated users for selection

### Requirement: Phase-2 model selection uses configured options only

The system SHALL expose only phase-2 model options configured in environment.

#### Scenario: UI lists enabled options only

- **WHEN** summary configuration page is rendered
- **THEN** only enabled phase-2 options are available for selection
- **AND** user cannot submit arbitrary endpoint/model outside configured options
