# adaptive-census-orchestration Specification

## MODIFIED Requirements

### Requirement: Orchestrator executes one safe census cycle

The orchestrator SHALL execute a safe census cycle by running census extraction
and then processing the snapshot produced by that extraction only when the
extraction is complete enough for operational use.

#### Scenario: Successful single cycle

- **WHEN** the orchestrator is asked to run one cycle
- **AND** the queue is drained
- **AND** the cooldown interval has elapsed
- **AND** `extract_census` completes with at least 40 distinct sectors
- **THEN** it runs `extract_census`
- **AND** it identifies exactly one new successful `census_extraction` run
- **AND** it runs `process_census_snapshot` with that run id
- **AND** it reports the created batch id and enqueued counts when available

#### Scenario: Extraction fails

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` fails
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** it exits or reports failure without enqueuing a new census batch

#### Scenario: Extraction is incomplete

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` detects fewer than 40 distinct sectors
- **THEN** it MUST treat the cycle as an extraction failure
- **AND** it MUST NOT run `process_census_snapshot`
- **AND** it reports the incomplete coverage as an operational failure

#### Scenario: Extraction run is ambiguous

- **WHEN** `extract_census` returns successfully
- **AND** the orchestrator cannot identify exactly one new successful
  `census_extraction` run from the cycle
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** it reports the ambiguity as an operational failure
