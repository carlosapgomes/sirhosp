## ADDED Requirements

### Requirement: Complete snapshot processing records patient absence

The system SHALL preserve all existing occupancy, patient, movement and
ingestion effects and, after processing a complete run, SHALL compare occupied
patient identity with the preceding complete run to update conservative absence
observations.

#### Scenario: Patient disappears from a complete run

- **WHEN** a patient with a canonical open admission was occupied in the
  preceding complete run
- **AND** is absent from the newly processed complete run
- **THEN** the system records the first absence observation for that admission
- **AND** does not set `Admission.discharge_date`

#### Scenario: Patient remains absent

- **WHEN** a later consecutive complete run also omits the patient
- **THEN** the same reconciliation case advances idempotently
- **AND** duplicate cases are not created

#### Scenario: Patient remains present

- **WHEN** a patient is occupied in both complete runs
- **THEN** no absence suspicion is created

#### Scenario: Patient reappears

- **WHEN** a census-only absence case exists and the patient is occupied again
- **THEN** the case is resolved as reappeared
- **AND** the admission remains unchanged

#### Scenario: No preceding complete run exists

- **WHEN** the selected run is the first usable complete census
- **THEN** it establishes comparison baseline only
- **AND** creates no absence suspicion

### Requirement: Rejected snapshots have no absence effect

Incomplete, ambiguous or rejected snapshots MUST NOT create, advance, reset or
resolve an absence sequence.

#### Scenario: Completeness guard rejects current run

- **WHEN** snapshot processing rejects a run for insufficient sectors
- **THEN** no stale-admission case changes

#### Scenario: Run provenance is ambiguous

- **WHEN** selected rows do not resolve to one census ingestion run
- **THEN** no stale-admission case changes
- **AND** existing clinical fail-closed behavior is preserved
