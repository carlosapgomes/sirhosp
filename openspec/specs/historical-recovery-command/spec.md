# historical-recovery-command Specification

## Purpose

Define deterministic historical data recovery over date ranges, including
service orchestration, dry-run behavior, failure aggregation, and retry handling.

## Requirements

### Requirement: Historical recovery command plans deterministic date ranges

The system SHALL provide a `recover_historical_data` Django management command
that plans recovery over a single date or inclusive date range.

#### Scenario: Single date recovery is planned

- **WHEN** an operator runs `python manage.py recover_historical_data --date
  DD/MM/AAAA`
- **THEN** the command plans recovery for exactly that date
- **AND** the planned extractor order is deterministic

#### Scenario: Date range recovery is planned inclusively

- **WHEN** an operator runs `python manage.py recover_historical_data
  --start-date 01/06/2026 --end-date 03/06/2026`
- **THEN** the command plans recovery for `01/06/2026`, `02/06/2026`, and
  `03/06/2026`
- **AND** no date outside the inclusive range is planned

#### Scenario: Invalid date input fails before extraction

- **WHEN** the operator provides an invalid date or an end date before the start
  date
- **THEN** the command fails with a clear validation error
- **AND** no extractor service is called

#### Scenario: Ambiguous date input fails before extraction

- **WHEN** the operator provides both `--date` and `--start-date`/`--end-date`
- **THEN** the command fails with a clear validation error
- **AND** no extractor service is called

### Requirement: Historical recovery command calls extractor services directly

The recovery command SHALL orchestrate the Python-callable extraction services
for discharges, admissions, deaths, and official census without invoking other
Django management commands.

#### Scenario: Default recovery runs all extractors in deterministic order

- **WHEN** the operator runs recovery for a valid date without selecting
  extractors
- **THEN** the command calls the discharge extraction service for that date
- **AND** the command calls the admission extraction service for that date
- **AND** the command calls the death extraction service for that date
- **AND** the command calls the official census extraction service for that date
- **AND** the calls occur in the default order: discharges, admissions, deaths,
  official census

#### Scenario: Selected extractor subset runs in default order

- **WHEN** the operator provides one or more `--extractor` options
- **THEN** only the selected extractor services are called
- **AND** selected extractors still run in the default deterministic order

#### Scenario: Recovery does not use management commands as integration boundary

- **WHEN** recovery executes extractor steps
- **THEN** it calls service functions directly
- **AND** it does not call `call_command` for extractor commands
- **AND** it does not spawn Django management command subprocesses

### Requirement: Historical recovery command supports dry-run planning

The recovery command SHALL support dry-run mode to show planned dates and
extractors without executing services.

#### Scenario: Dry run prints plan and skips execution

- **WHEN** the operator runs `recover_historical_data` with `--dry-run`
- **THEN** the command prints the planned dates and extractors
- **AND** no extractor service is called
- **AND** no retry round is executed
- **AND** the command exits successfully when input validation succeeds

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
