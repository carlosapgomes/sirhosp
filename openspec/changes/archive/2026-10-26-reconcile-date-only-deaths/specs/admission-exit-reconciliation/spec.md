# Spec Delta: admission-exit-reconciliation

## RENAMED Requirements

- FROM: `### Requirement: Date-only death evidence does not synthesize time`
- TO: `### Requirement: Date-only death evidence reconciles at date precision`

## MODIFIED Requirements

### Requirement: Date-only death evidence reconciles at date precision

A `DeathRecord` with a complete source datetime and a unique admission SHALL
close that admission as `death` at that datetime. Death evidence with only a
date SHALL reconcile at date precision: the uniquely matching admission
closes on the death's local date with an explicit date-only precision marker
on the reconciliation event, and no surface MAY display or consume an hour
for that closure as if it were source information. Ambiguous or unresolved
date-only evidence SHALL stay pending and MUST NOT close any admission.

#### Scenario: Death datetime uniquely matches

- **WHEN** death evidence contains a valid datetime and resolves exactly one
  admission
- **THEN** the admission is closed at that datetime with exit type `death`
- **AND** the event is excluded from hospital-discharge indicators

#### Scenario: Death has only a date

- **WHEN** death evidence has no source hour and exactly one admission's
  known period contains the death's `America/Bahia` local date
- **THEN** that admission closes on that local date with exit type `death`
- **AND** the reconciliation event carries an explicit date-only precision
  marker
- **AND** no surface displays an hour for that closure
- **AND** midnight, noon or end of day is never presented as the source hour

#### Scenario: Death date is ambiguous

- **WHEN** death evidence has no source hour and more than one admission's
  known period contains the death's local date
- **THEN** reconciliation stays pending
- **AND** no admission closes
- **AND** the case is counted for manual review

#### Scenario: Death admission is unresolved

- **WHEN** death evidence cannot uniquely resolve an admission
- **THEN** no synthetic admission is created
- **AND** source synchronization is enqueued for later reconciliation
