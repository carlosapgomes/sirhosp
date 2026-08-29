# fix-fullsync-failure-exhaustion Delta Specification

## ADDED Requirements

### Requirement: Deterministic payload failures fail fast without exhausting attempts

The system SHALL stop retrying extraction attempts whose failure reason is
deterministic payload invalidity and SHALL terminate the run fail-fast on
the first attempt, recording the terminal failure and closing the batch.

#### Scenario: Known invalid payload ends the run without further attempts

- **WHEN** an extraction attempt fails with `failure_reason=invalid_payload`
- **THEN** the run transitions to terminal `failed` on that attempt
- **AND** no retry is enqueued (`next_retry_at` stays null, status not
  requeued)
- **AND** a `FinalRunFailure` row is recorded with the current attempt
  count
- **AND** the batch closure logic runs as in any terminal failure

#### Scenario: Transient deadline failures remain retryable

- **WHEN** an extraction attempt fails with `failure_reason=timeout`
- **THEN** the existing retry policy applies unchanged (requeue while
  `attempt_count < max_attempts`, backoff +60s)

#### Scenario: Retry decision is shared by both workers

- **WHEN** either worker (`process_ingestion_runs` or
  `process_ingestion_runs_persistent_session`) marks a run failed
- **THEN** the retry decision comes from the same pure policy function on
  `failure_reason`

#### Scenario: Fail-fast logging is sanitized

- **WHEN** a run fails fast on a deterministic payload failure
- **THEN** the worker logs an aggregate-only line (run label and reason)
  without identifiers, payload content, URLs or raw errors

### Requirement: Evolution extraction budget scales with window volume

The system SHALL dimension the evolution extraction timeout by the gap
window span through a pure function with a configurable cap, and the
persistent worker SHALL use that budget per window instead of a fixed
value.

#### Scenario: Short window keeps the base budget

- **WHEN** the window span is zero/one day
- **THEN** the budget equals the base seconds (current default 120)

#### Scenario: Long legitimate window receives a scaled budget

- **WHEN** the window span grows
- **THEN** the budget grows linearly per day up to the cap (default 600s)
- **AND** the function is deterministic for the same inputs

#### Scenario: Oversized volume remains bounded

- **WHEN** extraction exceeds the budget even after scaling
- **THEN** the flow raises the typed timeout error and the run fails with
  reason `timeout` (bounded behavior preserved)

#### Scenario: Invalid window dates fail sanitized

- **WHEN** dates are unparseable or inverted
- **THEN** the budget function raises a sanitized typed error without
  leaking values

#### Scenario: Persistent worker uses the scaled budget

- **WHEN** the persistent worker extracts evolutions for a gap window
- **THEN** the `timeout` passed to the adapter comes from the window
  budget function

### Requirement: Payload validations are characterized against real code

The system SHALL keep every known payload validation covered by
characterization/regression tests against the real extraction and
classification code, distinguishing genuinely invalid content from
recoverable parsing paths.

#### Scenario: Empty PDF object attribute is rescued by the viewer frame

- **WHEN** the PDF `<object>` tag exists with an empty `data` attribute and
  a viewer frame carries a PDF URL
- **THEN** the flow resolves the PDF URL through the viewer fallback and
  proceeds

#### Scenario: Genuinely absent report fails deterministically

- **WHEN** no PDF object and no viewer frame URL exist
- **THEN** the flow raises the sanitized absence error classified as
  `invalid_payload`

#### Scenario: Each known payload validation maps to invalid_payload

- **WHEN** content violates a known validation (non-list JSON root, invalid
  JSON, missing container, HTML response where PDF expected, missing
  `%PDF-` signature)
- **THEN** the real classifier maps the raised error to `invalid_payload`
- **AND** each validation path has its own regression test

#### Scenario: Characterization suite is sensitivity-proven

- **WHEN** a validation or fallback is temporarily mutated
- **THEN** the corresponding characterization test fails (suite detects
  regressions)

### Requirement: Observability contracts remain unchanged

The system SHALL preserve the existing health-check and characterization
contracts while the fix changes the underlying failure dynamics.

#### Scenario: Taxonomy and outputs unchanged

- **WHEN** the health check or the characterization command runs after the
  fix
- **THEN** reasons, stages and aggregate outputs use the same taxonomy and
  formats as before the fix

#### Scenario: Reduced attempt burning is observable

- **WHEN** a deterministic payload failure occurs post-fix
- **THEN** the terminal failure records the reduced attempt count and the
  aggregate metrics reflect fewer repeated attempts per patient
