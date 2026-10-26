# Spec Delta: admission-reconciliation-backfill

## MODIFIED Requirements

### Requirement: Automatic backfill uses only approved cohorts

The backfill SHALL automatically process only source-confirmed duplicate pairs,
exit records with matching admission date and valid `saida_em`,
mirror-confirmed exits, and deaths with date-confirmed evidence — a complete
datetime plus one compatible admission, or a date-only death that uniquely
matches one admission at date granularity.

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

#### Scenario: Date-only death cohort is eligible

- **WHEN** death evidence has no source hour and exactly one admission's
  known period contains the death's local date
- **THEN** it is eligible for automatic reconciliation as `death` at date
  precision
- **AND** the applied event carries the date-only precision marker

#### Scenario: Ambiguous date-only death stays manual

- **WHEN** death evidence has no source hour and more than one admission's
  known period contains the death's local date
- **THEN** it is counted for manual review and never applied automatically

#### Scenario: Non-exact temporal match is excluded

- **WHEN** evidence is only temporally compatible but admission date differs
- **THEN** it is excluded from automatic apply and exposed for manual review

#### Scenario: Exit report is absent

- **WHEN** an open admission outside the census has no usable exit evidence
- **THEN** it is excluded from automatic closure
- **AND** remains eligible for source confirmation and manual review

### Requirement: Backfill order is deterministic

The operational order MUST be source-confirmed duplicate resolution, exact
hospital discharges, mirror-confirmed exits, deaths with date-confirmed
evidence and finally manual review of ambiguous cases.

#### Scenario: Multiple cohorts are selected

- **WHEN** one plan contains candidates from more than one cohort
- **THEN** duplicate resolution completes before exit reconciliation
- **AND** mirror-exit reconciliation runs after exact discharge replay
- **AND** ambiguous cases are never pulled into automatic cohorts by fallback
