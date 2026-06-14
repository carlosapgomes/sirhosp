# Historical Recovery Command Retry Delta

## MODIFIED Requirements

### Requirement: Historical recovery command aggregates step results

The recovery command SHALL aggregate per-date/per-extractor results into a final
command outcome and retry failed steps at the end of the batch when retries are
enabled.

#### Scenario: All selected extractions succeed

- **WHEN** all selected extractor service calls return successful results
- **THEN** the command exits successfully
- **AND** the final summary reports zero failed steps

#### Scenario: One or more selected extractions fail then retry succeeds

- **WHEN** one or more selected extractor service calls return failed results
- **AND** a later end-of-batch retry attempt for those failed steps succeeds
- **THEN** the command exits successfully
- **AND** the final summary reports zero final failed steps
- **AND** the output reports that retry attempts occurred

#### Scenario: One or more selected extractions still fail after retries

- **WHEN** one or more selected extractor service calls return failed results
- **AND** those steps still fail after the configured retry attempts are
  exhausted
- **THEN** the command exits with a non-zero status after retries complete
- **AND** the final summary reports the number of final failed steps

#### Scenario: Successful steps are not retried

- **WHEN** a planned step succeeds during the initial batch or a retry round
- **THEN** later retry rounds do not call that date/extractor step again

#### Scenario: Fail-fast stops after first failure

- **WHEN** the operator provides `--fail-fast`
- **AND** a selected extractor service call fails
- **THEN** the command stops without running later planned steps
- **AND** no retry rounds are executed
- **AND** the command exits with a non-zero status

#### Scenario: Unexpected service exception becomes failed step

- **WHEN** an extractor service raises an unexpected Python exception
- **THEN** the command records that step as failed with a safe error message
- **AND** the command retries or stops according to retry and fail-fast mode
- **AND** credential values are not printed in command output

### Requirement: Historical recovery command supports dry-run planning

The recovery command SHALL support dry-run mode to show planned dates and
extractors without executing services or retries.

#### Scenario: Dry run prints plan and skips execution

- **WHEN** the operator runs `recover_historical_data` with `--dry-run`
- **THEN** the command prints the planned dates and extractors
- **AND** no extractor service is called
- **AND** no retry round is executed
- **AND** the command exits successfully when input validation succeeds

## ADDED Requirements

### Requirement: Historical recovery command limits retry attempts

The recovery command SHALL bound automatic retry attempts for failed steps.

#### Scenario: Default retry limit is three

- **WHEN** the operator runs recovery without specifying a retry limit
- **AND** a step fails during the initial batch
- **THEN** the command retries that failed step at most 3 times after the
  initial batch

#### Scenario: Retry limit can disable retries

- **WHEN** the operator runs recovery with `--max-retries 0`
- **AND** a step fails during the initial batch
- **THEN** the command does not run retry rounds
- **AND** behavior matches the pre-retry aggregation semantics

#### Scenario: Invalid retry limit fails before extraction

- **WHEN** the operator provides a negative retry limit
- **THEN** the command fails with a clear validation error
- **AND** no extractor service is called
