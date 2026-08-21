## MODIFIED Requirements

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

## ADDED Requirements

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
