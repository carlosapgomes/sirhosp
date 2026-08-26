## MODIFIED Requirements

### Requirement: Standard group occupancy uses version-appropriate occupied evidence

For a `standard` group, the system SHALL apply the immutable algorithm selected
by the applicable catalog, divide the resulting occupied numerator once by the
official capacity and SHALL NOT cap the result at 100 percent. V1 and v2 SHALL
retain row-counting semantics, v3 SHALL count only fully unambiguous normalized
positions, and v4 SHALL count normalized positions whose occupied state and
official classification are unambiguous even when occupant identity conflicts.

#### Scenario: V1 through v3 remain historical

- **WHEN** v4 becomes supported
- **THEN** existing v1/v2 row semantics and v3 conflict semantics remain stored
  unchanged
- **AND** no earlier measurement is recalculated

#### Scenario: V4 occupant-only conflict counts occupancy once

- **WHEN** one normalized position has multiple occupied alternatives with the
  same effective age selector but divergent occupant evidence
- **THEN** v4 counts one occupied physical position
- **AND** assigns it once to the applicable calculable group
- **AND** selects no patient alternative as authoritative

#### Scenario: V4 status conflict is not counted

- **WHEN** one normalized position has divergent occupied and non-occupied
  statuses
- **THEN** v4 counts one status-conflict case
- **AND** assigns no occupied state or official group numerator to that position

#### Scenario: V4 age conflict in partitioned source is not assigned

- **WHEN** occupied alternatives of one position in an age-partitioned source
  disagree on the effective age selector
- **THEN** the physical position remains occupied evidence
- **AND** it enters neither age-partitioned official numerator
- **AND** no Adulto or Infantil selector is chosen

#### Scenario: Non-partitioned age drift does not suppress occupancy

- **WHEN** occupied alternatives in a non-partitioned source differ only in age
  metadata
- **THEN** v4 counts one occupied position
- **AND** records a quality warning without inventing an age partition

#### Scenario: Percentage and excess remain deterministic

- **WHEN** a v4 calculable group is materialized
- **THEN** percentage uses `ROUND_HALF_UP` with two decimal places
- **AND** percentage may exceed 100 percent
- **AND** availability and excess remain non-compensated setorial values

## ADDED Requirements

### Requirement: V4 classifies physical conflicts by their effect

For `occupancy-v4`, the system SHALL collapse exact duplicates before conflict
classification, SHALL use source identity plus bed as the physical key and
SHALL classify remaining ambiguity without using record number as a position
key.

#### Scenario: Exact duplicates are consolidated first

- **WHEN** equivalent rows repeat under one physical key
- **THEN** one signature remains for conflict classification
- **AND** extra equivalent rows are recorded as duplicates
- **AND** the corresponding position can still count once

#### Scenario: Occupant evidence diverges but occupation agrees

- **WHEN** unique alternatives under one key are occupied and use the same
  effective age selector but differ in name or record evidence
- **THEN** the result is `occupant_conflict`
- **AND** the occupied position counts once
- **AND** candidate identity remains non-authoritative

#### Scenario: Status evidence diverges

- **WHEN** unique alternatives under one key have different statuses
- **THEN** the result is `status_conflict`
- **AND** no preferred status is selected
- **AND** the position is omitted from official numerators

#### Scenario: Partition selector diverges

- **WHEN** unique occupied alternatives in a partitioned code resolve to
  different or unknown selectors
- **THEN** the result is `age_conflict`
- **AND** the position is omitted from partitioned official numerators

#### Scenario: Occupied row lacks physical identity

- **WHEN** an occupied row has no usable bed identity
- **THEN** it remains an unidentified raw case
- **AND** it is omitted from official numerators because it cannot be safely
  deduplicated

#### Scenario: Shared record in different beds remains distinct

- **WHEN** the same record evidence appears in two normalized beds
- **THEN** v4 preserves two positions
- **AND** performs no patient-level deduplication or mother-child inference

### Requirement: V4 reconciliation distinguishes every treatment

Each v4 measurement SHALL persist a schema 2 allowlisted aggregate
reconciliation whose occupied-row bridge and counted-position bridge close
exactly and whose labels distinguish consolidation, ambiguity, missing identity
and policy scope.

#### Scenario: Raw occupied-row bridge closes

- **WHEN** a v4 measurement is materialized
- **THEN** raw occupied rows equal duplicate occupied extras plus occupant
  conflict extras plus occupied rows omitted by status conflict, age conflict,
  missing identity or unknown partition plus counted occupied positions
- **AND** all values are nonnegative integers

#### Scenario: Counted occupied-position bridge closes

- **WHEN** a v4 measurement contains calculable, unrated, unmapped or pending
  occupied positions
- **THEN** counted occupied positions equal official numerator plus separate
  counts for each non-calculable policy state
- **AND** intentional `unrated` evidence is not conflated with `unmapped`

#### Scenario: Occupant conflict contributes one representative

- **WHEN** an occupant-only conflict contains multiple unique occupied
  alternatives and exact duplicate extras
- **THEN** one occupied position enters the counted-position bridge
- **AND** remaining unique alternatives and duplicate extras are accounted for
  exactly once in the raw-row bridge

#### Scenario: Physical status partition remains closed

- **WHEN** v4 contains unambiguous positions, occupant conflicts, status
  conflicts, age conflicts, duplicates and unidentified rows
- **THEN** each position or raw exception belongs to one documented aggregate
  category
- **AND** no duplicate extra row increases physical-position total

#### Scenario: Reconciliation remains private

- **WHEN** raw alternatives contain names, records, beds or exact ages
- **THEN** persisted measurement and group history contain none of those values
- **AND** logs and errors contain no physical key or row signature

### Requirement: V4 records actionable quality without rejecting accepted census

Every successfully materialized v4 measurement SHALL record whether quality
warnings exist, while remaining a valid immutable point measurement for a
census already accepted by the primary extraction gate.

#### Scenario: Clean v4 measurement

- **WHEN** a v4 measurement has no conflict, unidentified occupied row, unknown
  partition or occupied unmapped position
- **THEN** its v4 quality warning is false

#### Scenario: V4 measurement has actionable gap

- **WHEN** v4 contains any occupant, status or age conflict, occupied row without
  position, unknown partition or occupied unmapped position
- **THEN** its quality warning is true
- **AND** aggregate reason counts remain available for summary and presentation

#### Scenario: Repeated v4 materialization is idempotent

- **WHEN** v4 materialization is requested twice for the same census run
- **THEN** the original measurement, warning and reconciliation are returned
- **AND** no group or daily summary is recalculated

### Requirement: V4 preserves prior algorithms and activation boundaries

The system SHALL dispatch v4 only from a future catalog explicitly declaring
`occupancy-v4` and SHALL preserve all prior measurements, summaries and
catalogs without backfill.

#### Scenario: V4 catalog becomes applicable

- **WHEN** an accepted census local date uses a catalog declaring
  `occupancy-v4`
- **THEN** its measurement records `occupancy-v4`
- **AND** applies typed conflict semantics

#### Scenario: Earlier v3 remains strict

- **WHEN** an earlier v3 measurement is physically partial
- **THEN** it keeps its original omitted numerator and daily-ineligible meaning
- **AND** v4 does not reinterpret its reconciliation or warning state

#### Scenario: Deployment does not activate v4

- **WHEN** v4 code and migrations are deployed
- **THEN** the applicable v3 catalog remains selected until a future v4 catalog
  becomes effective
- **AND** no startup, migration or build performs activation
