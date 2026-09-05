## ADDED Requirements

### Requirement: Exit reconciliation health is aggregate and alertable

The pipeline health diagnostic SHALL report coverage and age for exit evidence,
reconciliation cases, ambiguities, open/closed duplicate candidates and missing
extraction dates using aggregate-safe output.

#### Scenario: Exit reconciliation is healthy

- **WHEN** no configured threshold or invariant is violated
- **THEN** health reports aggregate counts and oldest ages
- **AND** exits with status zero

#### Scenario: Unreconciled backlog exceeds threshold

- **WHEN** pending or ambiguous reconciliation count or age exceeds configured
  limits
- **THEN** health is unhealthy
- **AND** output identifies only status groups, counts and ages

#### Scenario: Inequivalent duplicate remains

- **WHEN** an open admission has a source-confirmed equivalent closed record
- **THEN** health reports an aggregate duplicate invariant violation
- **AND** prints no admission or patient identifier

### Requirement: Extraction coverage distinguishes confirmed zero and missing data

Health SHALL distinguish nonzero success, zero confirmed by two successful
attempts, failed extraction and missing date coverage using durable
`IngestionRun` stage metadata rather than in-memory extraction results or
`DailyDischargeCount`.

#### Scenario: Zero is confirmed

- **WHEN** durable stage metadata records both successful empty attempts and
  `zero_confirmed=true`
- **THEN** coverage treats the date as complete

#### Scenario: Zero is unconfirmed

- **WHEN** durable stage metadata records only one successful empty attempt or
  omits `zero_confirmed=true`
- **THEN** coverage treats the date as incomplete
- **AND** health can return nonzero under the configured boundary

#### Scenario: Recovery gap exceeds automatic limit

- **WHEN** more than seven dates require catch-up
- **THEN** health reports an aggregate operator-action condition
- **AND** does not start recovery itself

### Requirement: Reconciliation health remains read-only and identity-safe

Health evaluation MUST NOT create reconciliation cases, enqueue work, call the
source or modify clinical state, and MUST NOT emit names, record numbers, CSV
content or clinical text.

#### Scenario: Health evaluates unhealthy data

- **WHEN** one or more reconciliation invariants fail
- **THEN** no database row is mutated
- **AND** no source request occurs
- **AND** only aggregate-safe output is produced
