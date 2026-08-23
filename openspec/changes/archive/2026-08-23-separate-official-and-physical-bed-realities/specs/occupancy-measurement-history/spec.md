## RENAMED Requirements

- FROM: `### Requirement: Standard group occupancy uses raw occupied legacy records`
- TO: `### Requirement: Standard group occupancy uses version-appropriate occupied evidence`

## MODIFIED Requirements

### Requirement: Standard group occupancy uses version-appropriate occupied evidence

For a `standard` group, the system SHALL apply the immutable algorithm selected
by the applicable catalog, divide the resulting occupied numerator once by the
official capacity and SHALL NOT cap the result at 100 percent. V1 and v2 SHALL
retain their row-counting semantics; v3 SHALL count only unambiguous normalized
physical positions.

#### Scenario: Legacy v1 or v2 group keeps row semantics

- **WHEN** a v1 or v2 standard group contains occupied legacy rows
- **THEN** its persisted numerator retains the algorithm's original row count
- **AND** no later physical-position rule reinterprets that measurement

#### Scenario: V3 simple group is calculated from positions

- **WHEN** a v3 standard group with capacity 10 has eight unambiguous occupied
  positions
- **THEN** its numerator is 8
- **AND** its occupancy percentage is 80.00
- **AND** its exceeded-by value is 0

#### Scenario: V3 group exceeds capacity

- **WHEN** a v3 standard group with capacity 8 has 10 unambiguous occupied
  positions
- **THEN** its occupancy percentage is 125.00
- **AND** its exceeded-by value is 2
- **AND** its availability is 0

#### Scenario: Non-occupied states do not enter the numerator

- **WHEN** a v3 group contains empty, reserved, maintenance or isolation
  positions
- **THEN** those positions remain in the physical evidence
- **AND** they do not enter the occupied numerator

#### Scenario: Percentage rounding is deterministic

- **WHEN** a percentage has more than two decimal places
- **THEN** it is persisted as `Decimal` with two places using `ROUND_HALF_UP`

## ADDED Requirements

### Requirement: V3 normalizes physical positions before official calculation

For `occupancy-v3`, the system SHALL normalize every exact-run census row into
one physical-position result using source identity plus bed identity, SHALL
collapse only exact duplicates and SHALL preserve ambiguity instead of choosing
one conflicting row.

#### Scenario: Exact duplicate is counted once

- **WHEN** two occupied rows have the same normalized source, bed, status,
  record number, patient name and age band
- **THEN** v3 counts one occupied physical position
- **AND** records one aggregate duplicate row excluded
- **AND** preserves both raw snapshots unchanged

#### Scenario: Shared record in distinct beds remains distinct

- **WHEN** two occupied rows share a record number but have different normalized
  bed identities
- **THEN** v3 counts two occupied positions
- **AND** performs no mother-child pairing or patient-level deduplication

#### Scenario: Same position has divergent occupant evidence

- **WHEN** one normalized source and bed has divergent occupied signatures
- **THEN** v3 classifies one conflicting physical position
- **AND** excludes every row for that position from official numerators
- **AND** marks the point measurement physically partial

#### Scenario: Same position has divergent status evidence

- **WHEN** one normalized source and bed is simultaneously reported with
  different statuses
- **THEN** v3 classifies one conflicting physical position
- **AND** does not select a preferred status
- **AND** marks the point measurement physically partial

#### Scenario: Bed identity is absent

- **WHEN** a census row has no usable normalized bed identity
- **THEN** v3 preserves it as an unidentified raw row
- **AND** excludes an occupied unidentified row from official numerators
- **AND** marks the point measurement physically partial

#### Scenario: Position normalization applies across all sectors

- **WHEN** duplicate or conflicting positions occur outside code `654`
- **THEN** v3 applies the same normalization rules
- **AND** does not special-case deduplication to the 3A

### Requirement: V3 persists aggregate reconciliation without identifiers

Each v3 measurement SHALL persist a closed, versioned aggregate reconciliation
sufficient to explain the official numerator and physical status totals without
persisting row-level identity.

#### Scenario: Official numerator bridge closes

- **WHEN** a v3 measurement is materialized
- **THEN** its reconciliation accounts for raw occupied rows, duplicate occupied
  rows, conflicts, unidentified occupied rows, unknown-age 3A rows,
  non-calculable occupied positions and the resulting official numerator
- **AND** the bridge values are nonnegative integers
- **AND** the arithmetic closes exactly

#### Scenario: Physical status partition closes

- **WHEN** a v3 measurement contains unambiguous positions, conflicts,
  duplicates and unidentified rows
- **THEN** its physical aggregate separates identified position statuses,
  conflicting positions, duplicate extra rows and unidentified rows
- **AND** duplicates do not increase physical-position total

#### Scenario: Reconciliation remains private

- **WHEN** snapshots contain names, record numbers, beds, exact ages or clinical
  text
- **THEN** measurement and group history contain none of those values
- **AND** reconciliation keys come only from the documented aggregate allowlist
- **AND** logs and errors contain no row-level signature or position key

### Requirement: V3 exposes official availability without cross-sector compensation

Every calculable v3 group SHALL persist its nonnegative official availability,
and the parent measurement SHALL sum group availability and group excess
independently.

#### Scenario: Sector has remaining capacity

- **WHEN** a group has capacity 10 and official occupied numerator 7
- **THEN** group availability is 3
- **AND** group exceeded-by is 0

#### Scenario: Sector is over capacity

- **WHEN** a group has capacity 10 and official occupied numerator 12
- **THEN** group availability is 0
- **AND** group exceeded-by is 2

#### Scenario: Hospital does not offset one sector with another

- **WHEN** one sector has availability 4 and another has exceeded-by 3
- **THEN** hospital availability includes all 4 available units
- **AND** hospital exceeded-by includes all 3 excess positions
- **AND** neither value is netted against the other

#### Scenario: Non-calculable group has no official availability

- **WHEN** a group is `unrated`, `unmapped` or `linked_slots_pending`
- **THEN** its official availability remains null
- **AND** its physical evidence remains available separately

### Requirement: V3 and prior algorithms remain historically isolated

The system SHALL dispatch the algorithm from immutable applicable catalog
context and SHALL never recalculate an existing measurement when v3 is
published.

#### Scenario: V3 catalog is applicable

- **WHEN** a complete census local date uses a catalog declaring
  `occupancy-v3`
- **THEN** its measurement records `occupancy-v3`
- **AND** applies physical-position normalization

#### Scenario: Earlier v2 measurement remains unchanged

- **WHEN** a v3 catalog becomes effective
- **THEN** existing v2 measurements keep their stored row-based numerators,
  percentages, exceeded-by values and partiality
- **AND** new availability or reconciliation fields do not reinterpret them

#### Scenario: Repeated v3 materialization is idempotent

- **WHEN** v3 materialization is requested twice for the same census run
- **THEN** the existing measurement and reconciliation are returned
- **AND** no field, group or daily summary is recalculated
