## ADDED Requirements

### Requirement: Physical-position quality gaps do not block clinical processing

The system SHALL restrict v3 deduplication and conflict handling to occupancy
measurement and presentation, while clinical census processing continues from
the preserved raw snapshots.

#### Scenario: Exact duplicate is suppressed only from occupancy

- **WHEN** an otherwise complete accepted census contains an exact duplicate
  physical position
- **THEN** v3 occupancy counts the position once
- **AND** existing patient, movement and ingestion processing retain their
  prior raw-snapshot behavior

#### Scenario: Conflicting position produces a partial measurement

- **WHEN** an otherwise complete accepted census contains one conflicting
  physical position
- **THEN** a physically partial v3 measurement is persisted
- **AND** clinical batch creation and patient enqueuing continue normally
- **AND** only official daily occupancy eligibility is affected

#### Scenario: Unidentified occupied row produces a partial measurement

- **WHEN** an otherwise complete accepted census contains an occupied row
  without usable bed identity
- **THEN** v3 occupancy preserves an aggregate unidentified count and partial
  flag
- **AND** clinical processing continues without inferring a bed or patient
