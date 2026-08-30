## ADDED Requirements

### Requirement: Repeated automatic full-sync is deferred with a fixed upper bound

The system SHALL reuse `IngestionRun.next_retry_at` to defer a new automatic
`full_sync` for an admission whose most recent targeted full-sync result failed,
and the defer interval MUST be fixed at no more than 60 minutes from that
terminal failure.

#### Scenario: Recent terminal failure defers automatic follow-up

- **WHEN** the latest terminal `full_sync` or `full_admission_sync` for an
  admission failed less than 60 minutes ago
- **AND** admissions processing automatically enqueues a new `full_sync` for
  that admission
- **THEN** the new run is queued with `next_retry_at` equal to 60 minutes after
  the terminal failure time
- **AND** the existing worker eligibility filter does not claim it early

#### Scenario: Expired guard does not add delay

- **WHEN** the latest targeted terminal failure for an admission occurred at
  least 60 minutes ago
- **THEN** a new automatic `full_sync` is immediately eligible
- **AND** the guard does not add another interval

#### Scenario: Later success resets the guard

- **WHEN** the most recent terminal targeted sync for an admission succeeded
- **THEN** a new automatic `full_sync` is immediately eligible
- **AND** an older failure does not defer it

#### Scenario: Manual synchronization ignores automatic deferment

- **WHEN** an operator enqueues `full_admission_sync` manually
- **THEN** that manual run is immediately eligible under its existing contract
- **AND** the automatic cross-run guard does not alter its enqueue path

#### Scenario: Retry inside the same run remains unchanged

- **WHEN** a retryable attempt fails before exhausting `max_attempts`
- **THEN** the same run keeps the existing approximately 60-second retry
  backoff
- **AND** deterministic `invalid_payload` failures remain fail-fast

### Requirement: Cross-run deferment derives state from existing run history

The bounded guard SHALL derive its decision from existing terminal run history
and MUST NOT introduce a circuit-breaker table, counter, scheduler or queue.

#### Scenario: Guard evaluation needs no separate state

- **WHEN** automatic follow-up eligibility is calculated
- **THEN** the latest terminal targeted run for the same local admission is the
  source of failure/success state
- **AND** `finished_at` and `next_retry_at` are the source of timing state
