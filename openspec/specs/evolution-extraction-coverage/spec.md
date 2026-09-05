# evolution-extraction-coverage Specification

## Purpose

Drive targeted medical-evolution extraction by explicit interval coverage so every target window is extracted exactly once, with observable completeness.

## Requirements

### Requirement: Targeted evolution extraction uses explicit interval coverage

The system SHALL represent completed evolution extraction coverage explicitly
for a local admission and source-system date interval and MUST NOT infer that
coverage from the mere presence of a clinical event.

#### Scenario: Successful non-empty chunk records coverage

- **WHEN** a targeted evolution chunk is extracted and its events are persisted
- **THEN** the system records completed coverage for the local admission,
  source system and inclusive chunk bounds
- **AND** the coverage records the aggregate event count and confirming run

#### Scenario: Successful empty chunk records coverage

- **WHEN** the source explicitly reports no evolutions for a targeted chunk
- **THEN** the system records completed coverage with event count zero
- **AND** the chunk is distinguishable from an interval that was never
  successfully consulted

#### Scenario: Existing event does not prove coverage

- **WHEN** a requested date contains a `ClinicalEvent` but no explicit coverage
  for the target admission and interval
- **THEN** the targeted planner treats that date as not proven covered

#### Scenario: Coverage write is idempotent

- **WHEN** the same admission, source and chunk bounds are confirmed again
- **THEN** the system maintains one logical coverage record for those bounds
- **AND** no duplicate coverage fact is created

### Requirement: Clinical persistence and coverage commit atomically per chunk

The system SHALL persist each targeted chunk independently and SHALL make its
clinical event changes, cumulative run counters and coverage fact atomic.

#### Scenario: Earlier chunk survives later extraction failure

- **WHEN** the first targeted chunk is extracted and committed
- **AND** a later chunk fails during extraction
- **THEN** events, counters and coverage from the first chunk remain committed
- **AND** the run follows its existing retry or terminal failure policy
- **AND** no coverage is recorded for the failed chunk

#### Scenario: Persistence failure rolls back chunk coverage

- **WHEN** event persistence fails within a targeted chunk transaction
- **THEN** no coverage for that chunk is committed
- **AND** partial event or counter changes from that chunk are rolled back

#### Scenario: Coverage failure rolls back clinical chunk

- **WHEN** the coverage fact cannot be committed after event persistence in the
  same chunk transaction
- **THEN** clinical and counter changes from that chunk are rolled back

### Requirement: Targeted retries plan only uncovered chunks

The system SHALL plan targeted evolution extraction from the union of explicit
coverage intervals and SHALL split uncovered windows with the existing
canonical deterministic chunking policy.

#### Scenario: Retry skips a previously committed chunk

- **WHEN** a prior attempt committed coverage for an earlier chunk and failed on
  a later chunk
- **AND** the run is retried for the same admission and requested interval
- **THEN** the planner excludes the previously completed chunk as a whole
- **AND** extraction resumes with the remaining gap, allowing only the
  configured overlap at its boundary

#### Scenario: Coverage union satisfies the requested interval

- **WHEN** explicit coverage intervals jointly cover the complete requested
  interval for the target admission
- **THEN** evolution extraction is skipped as fully covered

#### Scenario: Chunk bounds remain deterministic

- **WHEN** the same uncovered interval is planned more than once
- **THEN** the generated chunks have identical inclusive bounds
- **AND** every chunk observes the existing maximum 15-day span and overlap
  policy

### Requirement: Ambiguous legacy mode does not create admission coverage

The system SHALL create admission-specific coverage only when a local
`admission_id` has been resolved unambiguously.

#### Scenario: Run without admission id preserves compatibility

- **WHEN** a full-sync run has no `admission_id`
- **THEN** extraction may preserve the existing all-overlapping-admissions path
- **AND** it does not claim explicit coverage for any single local admission
