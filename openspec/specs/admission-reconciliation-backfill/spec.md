# admission-reconciliation-backfill Specification

## Purpose

TBD - created by archiving change reconcile-patient-exits-and-stale-admissions. Update Purpose after archive.

## Requirements

### Requirement: Backfill is dry-run by default and bounded on apply

The system SHALL provide a deterministic reconciliation backfill that performs
no mutation unless apply is explicit and requires a positive limit for every
applied batch.

#### Scenario: Default invocation is non-mutating

- **WHEN** an operator runs the backfill without `--apply`
- **THEN** it prints only aggregate candidate counts by cohort
- **AND** creates, updates or merges no clinical record

#### Scenario: Applied batch requires limit and backup reference

- **WHEN** the operator requests apply without a positive limit or identified
  backup reference
- **THEN** the command fails before mutation

#### Scenario: Initial canary is limited

- **WHEN** the first production apply is authorized
- **THEN** the runbook limits it to at most 50 patients
- **AND** requires validation before a later limit may increase to at most 100

### Requirement: Automatic backfill uses only approved cohorts

The backfill SHALL automatically process only source-confirmed duplicate pairs,
exit records with matching admission date and valid `saida_em`, and deaths with
complete datetime plus one compatible admission.

#### Scenario: Exact discharge cohort is eligible

- **WHEN** a discharge record has valid `saida_em`
- **AND** one canonical admission has the same patient and local admission date
- **THEN** it is eligible for automatic reconciliation

#### Scenario: Confirmed duplicate cohort is eligible

- **WHEN** an open/closed pair has fresh source confirmation of one episode
- **THEN** it is eligible for automatic merge before discharge replay

#### Scenario: Complete death cohort is eligible

- **WHEN** death evidence has a complete datetime and uniquely matches an
  admission
- **THEN** it is eligible for automatic reconciliation as `death`

#### Scenario: Non-exact temporal match is excluded

- **WHEN** evidence is only temporally compatible but admission date differs
- **THEN** it is excluded from automatic apply and exposed for manual review

#### Scenario: Exit report is absent

- **WHEN** an open admission outside the census has no usable exit evidence
- **THEN** it is excluded from automatic closure
- **AND** remains eligible for source confirmation and manual review

### Requirement: Backfill order is deterministic

The operational order MUST be source-confirmed duplicate resolution, exact
hospital discharges, complete deaths and finally manual review of ambiguous
cases.

#### Scenario: Multiple cohorts are selected

- **WHEN** one plan contains candidates from more than one cohort
- **THEN** duplicate resolution completes before exit reconciliation
- **AND** ambiguous cases are never pulled into automatic cohorts by fallback

### Requirement: Every applied change is reversible

Backfill apply SHALL use the same append-only reconciliation and merge audits as
online processing. Each item SHALL have an operation UUID and each applied
command SHALL assign one batch UUID that groups its ordered item operations;
command-level rollback MUST use the batch UUID atomically.

#### Scenario: Applied batch succeeds

- **WHEN** a bounded command modifies admissions
- **THEN** every item has before and after state plus operation UUID
- **AND** one batch UUID groups the exact ordered operation UUIDs
- **AND** audit retention is indefinite

#### Scenario: Operator requests batch rollback

- **WHEN** every grouped item still matches its recorded operation post-state
- **THEN** rollback by batch UUID restores all grouped operations atomically in
  reverse order
- **AND** records append-only rollback events linked to the batch UUID

#### Scenario: One item rollback is requested outside backfill

- **WHEN** an authorized operator targets one online operation UUID
- **THEN** only that operation is validated and reversed
- **AND** it cannot be mistaken for a whole backfill batch

#### Scenario: Rollback precondition fails

- **WHEN** a later incompatible mutation exists
- **THEN** no part of the rollback is applied
- **AND** the conflict is reported without patient identity in command output

### Requirement: Production execution is separately authorized

Implementation completion SHALL NOT execute the production backfill; the
runbook MUST require an identified backup, benchmark decision, explicit
operator approval and pause between initial batches.

#### Scenario: Change implementation completes

- **WHEN** code, tests and documentation are accepted
- **THEN** no production admission has been changed by the implementation
  workflow

#### Scenario: Benchmark permits normal operation

- **WHEN** bounded benchmark results stay within documented database, queue and
  source-system thresholds
- **THEN** an operator may authorize limited backfill during normal operation

#### Scenario: Benchmark is inconclusive or unsafe

- **WHEN** thresholds are exceeded or evidence is incomplete
- **THEN** apply remains blocked pending a maintenance window

### Requirement: Summary refresh is a later operation

Admissions changed by backfill SHALL be identifiable for a separate bounded
summary refresh and MUST NOT start summary generation inside the reconciliation
transaction.

#### Scenario: Backfill closes admissions

- **WHEN** a batch succeeds
- **THEN** its audit identifies affected canonical admissions
- **AND** no summary pipeline is started transactionally

#### Scenario: Operator refreshes summaries later

- **WHEN** reconciliation validation is complete
- **THEN** the runbook provides a separate bounded summary refresh step
