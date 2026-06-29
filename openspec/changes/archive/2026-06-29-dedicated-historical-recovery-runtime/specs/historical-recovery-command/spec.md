# historical-recovery-command Specification Delta

## ADDED Requirements

### Requirement: Historical recovery command can run through dedicated batch runtime

The existing `recover_historical_data` management command SHALL remain the
operator-facing interface for historical recovery when executed through the
production `historical_recovery` batch runtime.

#### Scenario: Dedicated runtime preserves command behavior

- **WHEN** an operator runs `recover_historical_data` through the dedicated
  `historical_recovery` runtime with valid arguments
- **THEN** the command plans and executes recovery according to the existing
  historical recovery command requirements
- **AND** no extractor behavior, retry behavior, dry-run behavior or persistence
  behavior changes because of the runtime selection

#### Scenario: Dedicated runtime supports selected extractor subsets

- **WHEN** an operator runs the dedicated runtime with one or more `--extractor`
  options
- **THEN** only the selected extractor services are called
- **AND** selected extractors still run in the default deterministic order

#### Scenario: Dedicated runtime supports dry-run planning

- **WHEN** an operator runs the dedicated runtime with `--dry-run`
- **THEN** the command prints the planned dates and extractors
- **AND** no extractor service is called
