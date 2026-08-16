# occupancy-measurement-history Specification

## ADDED Requirements

### Requirement: Accepted censuses produce one immutable occupancy measurement

The system SHALL persist at most one occupancy measurement for each accepted
census `IngestionRun` whose local capture date has an applicable catalog.

#### Scenario: First post-activation census is measured

- **WHEN** a complete accepted census is captured on or after the first catalog
  effective date
- **THEN** one parent measurement and its group measurements are persisted
- **AND** the parent references the census run and applicable catalog

#### Scenario: Pre-activation census is not measured

- **WHEN** a census capture date is earlier than the first catalog effective
  date
- **THEN** materialization returns `pre_activation`
- **AND** no measurement is created

#### Scenario: Repeated materialization is idempotent

- **WHEN** materialization is requested again for a census run that already has
  a measurement
- **THEN** the existing measurement is returned
- **AND** no values, children or daily summaries are recalculated

#### Scenario: Command requires a specific run

- **WHEN** an operator invokes the manual materialization command
- **THEN** the operator MUST provide one census run id
- **AND** the command does not scan or backfill other censuses

### Requirement: Measurements snapshot their calculation context

Every measurement SHALL preserve the catalog, algorithm version and resolved
values used at calculation time so future catalog changes cannot alter its
meaning.

#### Scenario: Group values are copied into history

- **WHEN** a group measurement is created
- **THEN** it stores the stable key, display name, policy, capacity, component
  codes, component names, observed counts and calculation status

#### Scenario: Later catalog does not change history

- **WHEN** a newer catalog changes a name, capacity or membership
- **THEN** an existing measurement keeps all previously resolved values
- **AND** it is not automatically recalculated

#### Scenario: Algorithm version is recorded

- **WHEN** a measurement is created by the first implementation
- **THEN** it records algorithm version `occupancy-v1`

### Requirement: Standard group occupancy uses raw occupied legacy records

For a `standard` group, the system SHALL sum rows with
`BedStatus.OCCUPIED` across every member code, divide once by the official
capacity and SHALL NOT cap the result at 100 percent.

#### Scenario: Simple group is calculated

- **WHEN** a standard group with capacity 10 has 8 occupied rows
- **THEN** its numerator is 8
- **AND** its occupancy percentage is 80.00
- **AND** its exceeded-by value is 0

#### Scenario: Group exceeds capacity

- **WHEN** a standard group with capacity 8 has 54 occupied rows
- **THEN** its occupancy percentage is 675.00
- **AND** its exceeded-by value is 46

#### Scenario: Non-occupied states do not enter the numerator

- **WHEN** a group contains empty, reserved, maintenance or isolation rows
- **THEN** those rows remain in the stored aggregate status counts
- **AND** they do not enter the occupied numerator

#### Scenario: Percentage rounding is deterministic

- **WHEN** a percentage has more than two decimal places
- **THEN** it is persisted as `Decimal` with two places using
  `ROUND_HALF_UP`

### Requirement: Shared groups consume capacity only once

The system SHALL aggregate all member codes of a shared standard group before
applying the group's single capacity.

#### Scenario: Cardiologia combines two codes

- **WHEN** codes `719` and `2156` contain occupied rows
- **THEN** their occupied counts are summed under `ENF-2B-CARD`
- **AND** capacity 15 is applied once

#### Scenario: Centro Obstétrico combines five codes

- **WHEN** codes `20`, `1110`, `1112`, `1114` and `1116` contain occupied rows
- **THEN** all five occupied counts are summed under `CO`
- **AND** capacity 8 is applied once

#### Scenario: Suspected stale patients remain counted

- **WHEN** an occupied Centro Obstétrico row has no recent clinical evolution
- **THEN** the occupancy calculation still counts that row
- **AND** no adjusted occupancy percentage is created

### Requirement: Non-calculable groups remain explicit

The system SHALL preserve observed counts for capacity-covered pending groups,
unrated groups and unmapped sectors while leaving their occupancy percentage
null.

#### Scenario: Obstetrícia 3A awaits linked-slot mapping

- **WHEN** code `654` is observed under the initial catalog
- **THEN** its group measurement stores capacity 32 and raw status counts
- **AND** calculation status is `linked_slots_pending`
- **AND** numerator, percentage and exceeded-by are null

#### Scenario: Known unrated sector is observed

- **WHEN** code `733`, `1522` or `1002` is observed
- **THEN** the matching group remains visible with capacity and percentage null
- **AND** its raw status counts are persisted

#### Scenario: Unknown source code is observed

- **WHEN** a non-empty source code has no membership in the applicable catalog
- **THEN** a synthetic group detail with status `unmapped` is persisted
- **AND** the unknown code does not block the measurement or clinical census

#### Scenario: Empty source code uses safe fallback

- **WHEN** a census sector has an empty source code
- **THEN** it remains visible as an unmapped detail using its observed sector
  name as presentation fallback
- **AND** it does not receive capacity by name matching

### Requirement: Hospital measurement exposes known and calculable coverage

The system SHALL calculate capacity coverage and calculable coverage over the
distinct sectors observed in that census and SHALL calculate the hospital rate
using only `standard` groups.

#### Scenario: Initial 47 sectors produce two coverages

- **WHEN** all 47 initial source codes are observed
- **THEN** capacity coverage is `44 of 47`
- **AND** calculable coverage is `43 of 47`
- **AND** known capacity is 658
- **AND** calculable capacity is 626

#### Scenario: Hospital rate excludes non-calculable groups symmetrically

- **WHEN** hospital occupancy is calculated
- **THEN** occupied rows from pending, unrated and unmapped groups are excluded
  from the hospital numerator
- **AND** their capacities are excluded from the hospital denominator

#### Scenario: Unknown sector lowers coverage

- **WHEN** an unknown source sector appears in a census
- **THEN** it enters the observed-sector denominator
- **AND** it enters neither coverage numerator

### Requirement: Source-name drift is audited without automatic remapping

The system SHALL map by source code and record a safe aggregate mismatch when
the observed source name differs from the configured name.

#### Scenario: Configured code arrives with a different name

- **WHEN** a known source code has an observed name different from its catalog
  membership name
- **THEN** it remains in the configured group for that catalog version
- **AND** its component snapshot records `source_name_mismatch=true`
- **AND** no new catalog or identity is created automatically

### Requirement: Measurement persistence contains no patient identifiers

The new capacity and occupancy history tables MUST contain only catalog data,
sector identifiers, aggregate counts and calculation metadata.

#### Scenario: Occupied rows are aggregated

- **WHEN** a measurement is persisted from snapshots containing patient names
  and record numbers
- **THEN** no patient name, record number or clinical text is copied into the
  parent measurement, group measurement or aggregate JSON fields
