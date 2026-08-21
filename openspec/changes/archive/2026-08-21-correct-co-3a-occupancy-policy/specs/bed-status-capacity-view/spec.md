## MODIFIED Requirements

### Requirement: Capacity rows follow official groups

When an exact measurement exists, the page SHALL show one summary row per
measured official group or unmapped sector and SHALL preserve source-sector and
bed detail without duplicating an exact-census row.

#### Scenario: Shared group appears once

- **WHEN** more than one source code belongs to one capacity group
- **THEN** the page shows one official group row with combined counts and one
  capacity state
- **AND** the expansion identifies the contributing source sectors and beds

#### Scenario: Age-partitioned groups receive only matching occupied beds

- **WHEN** a v2 measurement contains occupied code `654` rows with valid age
  bands
- **THEN** each row appears exactly once under Adulto or Infantil
- **AND** it never appears in both virtual sectors

#### Scenario: Non-age-classifiable 3A positions appear once

- **WHEN** the exact latest census contains non-occupied code `654` rows or
  occupied rows with unknown age
- **THEN** the page shows them once in `3A – posições sem classificação etária`
- **AND** that auxiliary grouping has no capacity, percentage or official
  sector count

#### Scenario: Existing bed detail remains available

- **WHEN** an authenticated user expands a measured group or the 3A auxiliary
  grouping
- **THEN** individual beds retain their existing status labels
- **AND** occupied beds retain the patient display already authorized on this
  page

#### Scenario: Unmapped sector remains visible

- **WHEN** the latest measurement contains an `unmapped` sector
- **THEN** the page shows it with its observed counts
- **AND** capacity and percentage are displayed as unavailable

### Requirement: Page communicates registered legacy occupancy

The page SHALL label the indicator as `Lotação registrada no sistema legado`,
SHALL not imply that stale patients were removed and SHALL explain sectors
intentionally excluded by the corrected policy.

#### Scenario: Corrected Centro Obstétrico is displayed without rate

- **WHEN** a v2 measurement contains CO status counts
- **THEN** the page displays the combined CO raw counts
- **AND** displays `Capacidade não cadastrada` or equivalent
- **AND** displays `Não incluído na taxa de ocupação da unidade` or equivalent
- **AND** displays no numerator, percentage, exceeded-by or adjusted rate

#### Scenario: Legacy CO measurement remains historical

- **WHEN** the page displays an exact persisted v1 measurement
- **THEN** its stored CO values remain as originally measured
- **AND** the page does not recalculate them with corrected policy

### Requirement: Page distinguishes capacity and calculation coverage

The page SHALL display algorithm-appropriate official coverage and SHALL label
whether the denominator represents source codes or official sectors.

#### Scenario: Corrected official-sector coverage is shown

- **WHEN** the page displays a corrected v2 measurement
- **THEN** it displays `39 de 43 setores oficiais com capacidade cadastrada`
- **AND** it displays `39 de 43 setores oficiais com lotação calculável`

#### Scenario: Corrected Obstetrícia 3A is calculated

- **WHEN** the page displays v2 groups `OBST-3A-ADULTO` and
  `OBST-3A-INFANTIL`
- **THEN** it displays capacities 32 and 16 respectively
- **AND** it displays each persisted occupied count, percentage and exceeded-by
- **AND** it does not display the old cama-berço pending message

#### Scenario: Legacy v1 coverage remains meaningful

- **WHEN** the page displays an exact v1 measurement
- **THEN** it retains the stored 44/47 capacity and 43/47 calculable source-code
  coverage labels
- **AND** does not relabel those values as 39/43 official-sector coverage

#### Scenario: Sector has no official capacity

- **WHEN** a group is `unrated` or `unmapped`
- **THEN** the page displays `Capacidade não cadastrada` or equivalent
- **AND** it does not display zero percent

### Requirement: Hospital total uses only calculable groups

The page SHALL display hospital occupancy using the exact measurement's
persisted numerator and calculable capacity and SHALL not recalculate totals in
the view.

#### Scenario: Corrected catalog hospital totals are displayed

- **WHEN** a page displays a v2 measurement using the corrected catalog
- **THEN** it identifies known capacity 666
- **AND** it identifies calculable capacity 666
- **AND** its hospital percentage excludes CO, the other unrated groups,
  unmapped groups and occupied 3A rows with unknown age

#### Scenario: Initial catalog hospital totals remain historical

- **WHEN** the page displays an exact v1 measurement
- **THEN** it identifies stored known capacity 658 and calculable capacity 626
- **AND** it does not apply corrected totals retroactively

## ADDED Requirements

### Requirement: Page warns when corrected occupancy is age-partial

The page SHALL display an aggregate, non-identifying warning whenever the exact
v2 measurement omitted an occupied 3A row because its age was unknown.

#### Scenario: Partial corrected measurement is displayed

- **WHEN** the exact measurement has a positive unknown-age occupied count
- **THEN** the page labels its point-in-time rate as partial
- **AND** displays the aggregate number of omitted 3A rows
- **AND** explains that the measurement is excluded from official daily means
- **AND** exposes no exact age, name or record number in the warning

#### Scenario: Complete corrected measurement has no partial warning

- **WHEN** the exact v2 measurement has zero unknown-age occupied rows
- **THEN** the page does not display the age-partial warning
