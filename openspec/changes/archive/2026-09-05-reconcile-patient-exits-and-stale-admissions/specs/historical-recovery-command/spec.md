## MODIFIED Requirements

### Requirement: Historical recovery command aggregates step results

The recovery command SHALL aggregate per-date/per-extractor results, including
safe reconciliation counters, into a final command outcome and retry failed or
semantically unconfirmed steps at the end of the batch when retries are enabled.

#### Scenario: All selected extractions succeed

- **WHEN** all selected extractor service calls return successful, semantically
  confirmed results
- **THEN** the command exits successfully
- **AND** the final summary reports zero failed steps
- **AND** discharge and death steps expose aggregate reconciliation statuses
  without patient identity

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

#### Scenario: Unconfirmed zero is a failed step

- **WHEN** a discharge extraction returns zero rows without a successful second
  confirmation
- **THEN** the step is not counted as succeeded
- **AND** normal retry limits apply

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

## ADDED Requirements

### Requirement: Recovery preserves unresolved evidence for later work

A successful extraction step SHALL retain unresolved reconciliation statuses
without fabricating patients, admissions, exit times or successful matches.

#### Scenario: Report persists an ambiguous row

- **WHEN** report extraction succeeds but one row has ambiguous admission match
- **THEN** the step reports the aggregate ambiguity count
- **AND** preserves the row for authorized review
- **AND** does not fail unrelated deterministic reconciliations

#### Scenario: Recovery is repeated

- **WHEN** an operator recovers the same date again
- **THEN** report persistence and already-reconciled exits remain idempotent
- **AND** pending evidence may be retried under the current matching rules
