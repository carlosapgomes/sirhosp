## MODIFIED Requirements

### Requirement: Automatic backfill uses only approved cohorts

The backfill SHALL automatically process only source-confirmed duplicate pairs,
exit records with matching admission date and valid `saida_em`,
mirror-confirmed exits, and deaths with complete datetime plus one
compatible admission.

#### Scenario: Exact discharge cohort is eligible

- **WHEN** a discharge record has valid `saida_em`
- **AND** one canonical admission has the same patient and local admission date
- **THEN** it is eligible for automatic reconciliation

#### Scenario: Confirmed duplicate cohort is eligible

- **WHEN** an open/closed pair has fresh source confirmation of one episode
- **THEN** it is eligible for automatic merge before discharge replay

#### Scenario: Mirror-exit cohort is eligible

- **WHEN** a discharge record is still `pending` and is not eligible for the
  exact discharge cohort
- **AND** its patient resolves uniquely and exactly one canonical
  admission of that patient is already closed with a `discharge_date`
  whose interval contains the record's `alta_em`
- **THEN** it is eligible for automatic mirror-exit reconciliation that
  emits the provenance event without mutating the admission

#### Scenario: Mirror ambiguity is excluded

- **WHEN** a pending discharge record has more than one closed candidate
  admission in the mirrored interval, or its patient does not resolve
- **THEN** it is excluded from automatic apply and counted for manual
  review with an explicit mirror reason

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
hospital discharges, mirror-confirmed exits, complete deaths and finally
manual review of ambiguous cases.

#### Scenario: Multiple cohorts are selected

- **WHEN** one plan contains candidates from more than one cohort
- **THEN** duplicate resolution completes before exit reconciliation
- **AND** mirror-exit reconciliation runs after exact discharge replay
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

#### Scenario: Mirror-exit rollback restores the evidence

- **WHEN** a mirror-exit item is rolled back by batch or operation
- **THEN** the linked discharge record returns to its prior status in the same
  transaction as the reversal event
- **AND** the admission keeps its mirrored `discharge_date` untouched
- **AND** the canonical series keeps counting the admission while its latest
  reconciled exit event remains `hospital_discharge` (documented asymmetry:
  reverting the provenance registration does not revert the mirrored exit)

#### Scenario: Rollback precondition fails

- **WHEN** a later incompatible mutation exists
- **THEN** no part of the rollback is applied
- **AND** the conflict is reported without patient identity in command output
