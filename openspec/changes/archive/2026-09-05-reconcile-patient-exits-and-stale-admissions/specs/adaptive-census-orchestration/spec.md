## ADDED Requirements

### Requirement: Successful census cycles trigger bounded absence detection

The adaptive orchestrator SHALL invoke stale-admission observation only after a
complete snapshot has been processed successfully and SHALL preserve existing
coordination, cooldown, failure and batch semantics.

#### Scenario: Complete cycle succeeds

- **WHEN** extraction and run-scoped snapshot processing succeed
- **THEN** the same cycle invokes absence observation for that accepted run
- **AND** reports only aggregate case counters

#### Scenario: Extraction or processing fails

- **WHEN** census extraction fails, completeness is rejected or snapshot
  processing returns `processing_failed`
- **THEN** absence observation is not invoked
- **AND** no prior absence sequence is changed

#### Scenario: Repeated processing is idempotent

- **WHEN** the accepted run is observed more than once
- **THEN** no duplicate case or confirmation run is created

### Requirement: Post-census work preserves orchestrator coordination

Absence observation SHALL execute inside the existing safe-cycle boundary and
MUST NOT introduce an external queue, a second long-lived orchestrator or a
conflicting advisory lock.

#### Scenario: Post-census observation completes

- **WHEN** observation succeeds
- **THEN** the orchestrator releases its existing lock normally
- **AND** later cycles continue to use normal queue-drain eligibility

#### Scenario: Observation fails unexpectedly

- **WHEN** post-census observation raises an error
- **THEN** the cycle reports a controlled failure
- **AND** releases the existing lock
- **AND** does not mark an unobserved absence as confirmed
