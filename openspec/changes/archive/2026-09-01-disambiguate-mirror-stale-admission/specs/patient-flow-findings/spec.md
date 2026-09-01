## MODIFIED Requirements

### Requirement: Patient flow findings are separate from technical outcomes

The system SHALL calculate current operational findings without suppressing a
technical failure and SHALL return closed presentation fields `code`, `label`,
`severity` and `requires_manual_review`.

#### Scenario: Recent attendance without admission is informational

- **WHEN** the latest recognized run proves a recent encounter and no admission
  has subsequently appeared
- **THEN** the patient receives `recent_encounter_without_admission`
- **AND** the finding does not require manual review

#### Scenario: Newborn waiting for registration is informational

- **WHEN** a current-census patient is zero through four local days old and has
  no admission
- **THEN** the patient receives `newborn_waiting_registration`
- **AND** the system does not create an admission or claim an error-free source
  document

#### Scenario: Possible newborn companion requires review

- **WHEN** a current-census patient is five through 28 local days old, has no
  admission and is in the configured Obstetrícia 3A source sector
- **THEN** the patient receives `possible_newborn_companion`
- **AND** the finding explicitly requires manual review

#### Scenario: Recent admission awaits first evolution

- **WHEN** the current admission began less than 48 hours ago and has no events
- **THEN** the patient receives `recent_admission_awaiting_first_evolution`
- **AND** observation-sector context may refine the label without becoming the
  sole evidence

#### Scenario: Older active admission with recent movement is a stale mirror

- **WHEN** an active admission is at least 48 hours old, its patient remains in
  the current census, it has no event in the previous 48 hours and the
  patient entered a sector within the previous 48 hours
- **THEN** the patient receives `mirror_stale_admission`
- **AND** the finding requires manual review to close the orphan admission in
  the internal mirror
- **AND** the system does not mutate the admission, the movement ledger or any
  run

#### Scenario: Older active admission without recent movement can be suspected residual

- **WHEN** an active admission is at least 48 hours old, its patient remains in
  the current census, it has no event in the previous 48 hours and the patient
  has no sector entry within the previous 48 hours
- **THEN** the patient receives `suspected_legacy_residual`
- **AND** the finding requires manual review
- **AND** the system does not claim that discharge is confirmed

#### Scenario: Invalid movement evidence fails closed

- **WHEN** the latest sector entry timestamp is in the future relative to the
  evaluation instant
- **THEN** the movement is treated as absent and the patient keeps the
  legacy-residual reading

#### Scenario: Timeout remains technical

- **WHEN** a patient satisfies an operational finding and the corresponding
  full-sync failed with timeout or another normalized reason
- **THEN** the finding and technical failure remain independently visible
- **AND** the technical run is not changed to succeeded

### Requirement: Findings are current, auto-resolving and query-bounded

The system SHALL derive findings from current census, demographics, admissions,
events, the patient movement ledger and allowlisted stage outcomes without
introducing a second mutable workflow state.

#### Scenario: New evidence removes an obsolete finding

- **WHEN** a later capture creates an admission/evolution or the patient leaves
  the current census so that a rule no longer holds
- **THEN** subsequent page evaluation no longer returns the obsolete finding
- **AND** no manual cleanup row is required

#### Scenario: Mirror staleness resolves itself

- **WHEN** the orphan admission receives a discharge or a new admission is
  mirrored while the movement evidence ages past 48 hours
- **THEN** subsequent page evaluation no longer returns `mirror_stale_admission`

#### Scenario: Bulk page classification avoids N plus one queries

- **WHEN** a current census page classifies many patients
- **THEN** the query count remains within a fixed allowance of five bulk
  queries independent of the patient count
- **AND** templates perform no database query or business classification
