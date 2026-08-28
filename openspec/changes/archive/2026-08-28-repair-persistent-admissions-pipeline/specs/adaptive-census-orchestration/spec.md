# adaptive-census-orchestration Delta Specification

## MODIFIED Requirements

### Requirement: Orchestrator executes one safe census cycle

The orchestrator SHALL execute a safe census cycle by running census extraction
and then processing only the snapshot produced by that complete extraction. A
processing rejection SHALL be represented as a controlled failed outcome and
MUST NOT terminate the loop with `SystemExit`.

#### Scenario: Successful single cycle

- **WHEN** the orchestrator is asked to run one cycle
- **AND** the queue is drained and cooldown elapsed
- **AND** `extract_census` completes with at least 40 distinct sectors
- **THEN** it identifies exactly one new successful census extraction run
- **AND** runs `process_census_snapshot` with that run id
- **AND** reports success and the one-shot command returns status zero

#### Scenario: Extraction fails

- **WHEN** `extract_census` fails
- **THEN** the orchestrator does not run `process_census_snapshot`
- **AND** reports `extraction_failed` and one-shot returns nonzero

#### Scenario: Extraction is incomplete

- **WHEN** `extract_census` detects fewer than 40 distinct sectors
- **THEN** it does not run `process_census_snapshot`
- **AND** reports extraction failure and one-shot returns nonzero

#### Scenario: Extraction run is ambiguous

- **WHEN** extraction returns successfully but does not produce exactly one new
  successful census extraction run
- **THEN** snapshot processing is not called
- **AND** the cycle reports ambiguity and one-shot returns nonzero

#### Scenario: Snapshot processing rejects the selected run

- **WHEN** extraction succeeds and `process_census_snapshot` raises
  `CommandError`
- **THEN** the cycle returns the controlled outcome `processing_failed`
- **AND** no unhandled `SystemExit` terminates one-shot or loop execution
- **AND** no clinical batch or patient ingestion run is created from the
  rejected snapshot

#### Scenario: One-shot cycle is safely blocked

- **WHEN** active work or the coordination lock safely blocks a one-shot cycle
- **THEN** extraction is not started
- **AND** the command reports no work and returns status zero

#### Scenario: One-shot cycle returns an unknown outcome

- **WHEN** one-shot receives an outcome outside its known taxonomy
- **THEN** it reports the unexpected outcome
- **AND** returns nonzero
