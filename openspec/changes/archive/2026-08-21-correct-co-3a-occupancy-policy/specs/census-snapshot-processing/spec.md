## ADDED Requirements

### Requirement: Census snapshots preserve a normalized occupancy age band

For every newly extracted census row, the system SHALL derive and persist only
the normalized age band required by occupancy classification, using the row's
own legacy `Idade` value and bed status.

#### Scenario: Integer below twelve is classified as child

- **WHEN** an occupied census row has an integer age from 0 through 11
- **THEN** its persisted occupancy age band is `under_12`

#### Scenario: Integer twelve or greater is classified as adult

- **WHEN** an occupied census row has integer age 12 or greater
- **THEN** its persisted occupancy age band is `age_12_or_over`

#### Scenario: Legacy month and day formats are normalized

- **WHEN** an occupied census row has a valid legacy age such as `1m` or
  `1m3d`
- **THEN** the system interprets its month/day units deterministically
- **AND** persists the corresponding age band without persisting that raw age
  in occupancy history

#### Scenario: Unknown occupied age remains explicit

- **WHEN** an occupied census row has a blank, negative, unsupported or
  structurally invalid age
- **THEN** its persisted occupancy age band is `unknown`
- **AND** the system does not infer age from name, record number, specialty or
  another row

#### Scenario: Non-occupied row has no applicable age band

- **WHEN** a census row is empty, reserved, in maintenance or in isolation
- **THEN** its persisted occupancy age band is `not_applicable`

#### Scenario: Historical snapshots are not backfilled

- **WHEN** the additive age-band migration is applied
- **THEN** existing snapshots receive a safe non-classifying default
- **AND** no historical age is reconstructed from patient data

### Requirement: Age classification does not change clinical census processing

The system SHALL restrict the normalized age band to capacity and occupancy
calculation and SHALL preserve the source sector and all existing clinical
processing behavior.

#### Scenario: Virtual 3A sectors do not replace the clinical source sector

- **WHEN** a code `654` row is classified for occupancy
- **THEN** its stored source code and source sector remain unchanged
- **AND** patient movement, ingestion and clinical views continue using the
  original 3A sector

#### Scenario: Unknown age does not block clinical processing

- **WHEN** an otherwise complete accepted census contains an occupied code
  `654` row with age band `unknown`
- **THEN** the clinical batch and patient ingestion flow continue normally
- **AND** only the occupancy result records the aggregate age-classification
  gap
