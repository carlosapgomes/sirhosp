# occupancy-measurement-history Specification

## Purpose

TBD - created by archiving change add-versioned-sector-capacity-occupancy-history. Update Purpose after archive.

## Requirements

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
values used at calculation time so future catalog, partition or algorithm
changes cannot alter its meaning.

#### Scenario: Group values are copied into history

- **WHEN** a group measurement is created
- **THEN** it stores the stable key, display name, policy, capacity, component
  codes, component names, membership selectors, observed counts and calculation
  status

#### Scenario: Later catalog does not change history

- **WHEN** a newer catalog changes a name, capacity, membership or selector
- **THEN** an existing measurement keeps all previously resolved values
- **AND** it is not automatically recalculated

#### Scenario: Legacy algorithm remains recorded

- **WHEN** a measurement uses a catalog without age partitions
- **THEN** it records algorithm version `occupancy-v1`

#### Scenario: Corrected algorithm is recorded

- **WHEN** a measurement uses the corrected age-partitioned catalog
- **THEN** it records algorithm version `occupancy-v2`

### Requirement: Shared groups consume capacity only once

The system SHALL aggregate all member codes of a shared standard group before
applying the group's single capacity, while an unrated shared group SHALL retain
raw counts without capacity or percentage.

#### Scenario: Cardiologia combines two codes

- **WHEN** codes `719` and `2156` contain occupied rows
- **THEN** their occupied counts are summed under `ENF-2B-CARD`
- **AND** capacity 15 is applied once

#### Scenario: Corrected Centro Obstétrico combines five unrated codes

- **WHEN** the corrected catalog observes codes `20`, `1110`, `1112`, `1114`
  or `1116`
- **THEN** all five codes remain represented once under `CO`
- **AND** their raw status counts are preserved
- **AND** capacity, occupied numerator, percentage and exceeded-by remain null

#### Scenario: Legacy CO measurement remains immutable

- **WHEN** an existing `occupancy-v1` measurement contains calculated CO values
- **THEN** those stored values remain unchanged
- **AND** the corrected policy does not recalculate them

### Requirement: Non-calculable groups remain explicit

The system SHALL preserve observed counts for pending groups, unrated groups and
unmapped sectors while leaving their occupancy percentage null.

#### Scenario: Initial Obstetrícia 3A remains historical pending evidence

- **WHEN** code `654` was measured under the initial catalog
- **THEN** its v1 group measurement retains capacity 32 and raw status counts
- **AND** calculation status remains `linked_slots_pending`
- **AND** numerator, percentage and exceeded-by remain null

#### Scenario: Known unrated sector is observed

- **WHEN** corrected policy observes CO or code `733`, `1522` or `1002`
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

The system SHALL retain source-code coverage diagnostics and SHALL expose
algorithm-appropriate official coverage without reinterpreting historical
measurements.

#### Scenario: Initial v1 measurement retains source-code coverage

- **WHEN** all 47 initial source codes are observed under the initial catalog
- **THEN** capacity coverage remains `44 of 47`
- **AND** calculable coverage remains `43 of 47`
- **AND** known capacity remains 658
- **AND** calculable capacity remains 626

#### Scenario: Corrected v2 measurement exposes official-sector coverage

- **WHEN** a census uses the corrected catalog
- **THEN** official-sector capacity coverage is `39 of 43`
- **AND** official-sector calculable coverage is `39 of 43`
- **AND** known capacity is 666
- **AND** calculable capacity is 666

#### Scenario: Corrected hospital rate excludes non-calculable groups

- **WHEN** v2 hospital occupancy is calculated
- **THEN** occupied rows from CO, the other unrated groups and unmapped groups
  are excluded from the hospital numerator
- **AND** those groups contribute no capacity to the hospital denominator

#### Scenario: Unknown sector lowers only source diagnostics

- **WHEN** an unknown source sector appears in a corrected census
- **THEN** it remains visible in source-code coverage diagnostics
- **AND** it does not become an official sector or change the 39/43 official
  catalog coverage

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

The capacity and occupancy history tables MUST contain only catalog data,
sector identifiers, aggregate counts, normalized partition metadata and
calculation metadata.

#### Scenario: Occupied rows are aggregated

- **WHEN** a measurement is persisted from snapshots containing patient names,
  record numbers and age source values
- **THEN** no patient name, record number, exact age or clinical text is copied
  into parent, group or aggregate JSON fields

#### Scenario: Unknown 3A ages are audited safely

- **WHEN** a corrected measurement omits occupied 3A rows with unknown age
- **THEN** it stores only their aggregate count and partial-classification flag
- **AND** logs and errors contain no row-level patient data

### Requirement: Corrected 3A occupancy partitions each occupied row by age

For an `occupancy-v2` measurement, the system SHALL classify each occupied code
`654` row exactly once from its own persisted age band and SHALL calculate the
two official 3A sectors independently.

#### Scenario: Adult 3A occupancy is calculated

- **WHEN** code `654` has occupied rows with `age_12_or_over`
- **THEN** those rows enter only `OBST-3A-ADULTO`
- **AND** its percentage is occupied adult rows divided by capacity 32

#### Scenario: Child 3A occupancy is calculated

- **WHEN** code `654` has occupied rows with `under_12`
- **THEN** those rows enter only `OBST-3A-INFANTIL`
- **AND** its percentage is occupied child rows divided by capacity 16

#### Scenario: Shared record number is not deduplicated or paired

- **WHEN** two occupied code `654` rows share a record number
- **THEN** each row is classified from its own age band and counted once
- **AND** the system does not infer a mother-child relationship

#### Scenario: Non-occupied 3A row enters neither age numerator

- **WHEN** a code `654` row is empty, reserved, in maintenance or in isolation
- **THEN** it enters neither Adult nor Infantil occupied numerator
- **AND** it is retained for one-time auxiliary presentation from the exact
  census snapshots

#### Scenario: Unknown occupied age produces a partial point measurement

- **WHEN** an occupied code `654` row has age band `unknown`
- **THEN** only that row is excluded from both 3A and hospital numerators
- **AND** capacities 32, 16 and hospital calculable capacity 666 remain fixed
- **AND** the measurement stores a nonzero unknown-age count and partial flag

#### Scenario: Corrected 3A can exceed capacity

- **WHEN** either 3A virtual sector has more occupied classified rows than its
  capacity
- **THEN** its percentage is not capped at 100 percent
- **AND** its exceeded-by value is persisted normally

### Requirement: Corrected materialization does not alter clinical processing

Age-partition gaps and corrected unrated CO SHALL be valid occupancy results and
SHALL NOT block processing of an otherwise complete census.

#### Scenario: Partial 3A measurement continues clinical flow

- **WHEN** a complete accepted census creates a partial v2 occupancy measurement
- **THEN** clinical batch creation and patient enqueuing continue
- **AND** the aggregate quality warning is available to `/beds` and daily
  summarization

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
