## MODIFIED Requirements

### Requirement: Capacity rows follow official groups

When an exact measurement exists, the official section SHALL show one summary
row per measured official group or unmapped sector using only persisted
algorithm-appropriate official values. Physical positions and patient detail
SHALL appear in the separate legacy section rather than being presented as
official capacity rows.

#### Scenario: Shared official group appears once

- **WHEN** more than one source code belongs to one capacity group
- **THEN** the official section shows one group row with combined official
  numerator and one capacity state
- **AND** the physical section retains each source sector and position once

#### Scenario: V3 age-partitioned groups use normalized positions

- **WHEN** a v3 measurement contains unambiguous occupied code `654` positions
  with valid age bands
- **THEN** the official section assigns each position once to Adulto or Infantil
- **AND** the physical section shows the source 3A position once
- **AND** no position appears in both physical status totals

#### Scenario: V2 auxiliary grouping is visually non-official

- **WHEN** an exact v2 census contains non-occupied code `654` rows or occupied
  rows with unknown age
- **THEN** any compatibility auxiliary grouping is separated from the official
  sector count and official table styling
- **AND** it is not presented as a forty-fourth official sector

#### Scenario: Existing patient detail remains authorized

- **WHEN** an authenticated user expands an unambiguous physical position
- **THEN** it retains the existing status label and authorized patient link
- **AND** exact duplicate rows are not rendered repeatedly

#### Scenario: Conflicting physical position appears once

- **WHEN** one normalized source and bed has conflicting rows
- **THEN** the physical section shows one `Conflito no legado` position
- **AND** does not choose or display one conflicting patient as authoritative

#### Scenario: Unmapped sector remains visible

- **WHEN** the latest exact census contains an `unmapped` source sector
- **THEN** the official section shows it as outside official calculation
- **AND** the physical section shows its unambiguous positions and statuses

### Requirement: Page communicates registered legacy occupancy

The page SHALL distinguish official calculated occupancy from the physical
snapshot registered in the legacy system, SHALL not imply that stale patients
were removed and SHALL explain every aggregate exclusion applied by the exact
measurement algorithm.

#### Scenario: Official and physical headings are simultaneously visible

- **WHEN** an authenticated user opens `/beds` with census data
- **THEN** the page visibly labels one section `Capacidade oficial e ocupação`
- **AND** visibly labels another section `Posições registradas no sistema legado`
- **AND** neither reality is hidden behind a tab by default

#### Scenario: Corrected Centro Obstétrico is outside the official rate

- **WHEN** a v2 or v3 measurement contains CO status evidence
- **THEN** the official section states that CO has no registered official
  capacity and is outside the unit rate
- **AND** displays no CO percentage or official availability
- **AND** the physical section retains its normalized status evidence

#### Scenario: Physical cards use physical labels

- **WHEN** the physical section displays status counts
- **THEN** it labels them as positions occupied, vacant, reserved, in
  maintenance, in isolation or conflicting in the legacy snapshot
- **AND** never labels raw line count as `Total de leitos`
- **AND** never calls legacy vacant status `Disponibilidade oficial`

#### Scenario: Legacy v1 and v2 measurement remains historical

- **WHEN** the latest exact measurement uses v1 or v2
- **THEN** the official section labels the historical algorithm semantics
- **AND** does not recalculate its numerator, percentage or excess with v3

### Requirement: Hospital total uses only calculable groups

The official section SHALL display hospital occupancy from the exact persisted
measurement's calculable numerator and capacity and, for v3, SHALL display
persisted per-sector availability and excess without cross-sector compensation.

#### Scenario: V3 official total is displayed

- **WHEN** the page displays a v3 measurement
- **THEN** it identifies official capacity, considered occupations,
  availability in official capacity, independent excess and official rate
- **AND** labels availability as calculated setorial balance rather than a list
  of nominal vacant beds

#### Scenario: V3 partial official total is displayed

- **WHEN** a v3 measurement has physical or age partiality
- **THEN** its point-in-time official cards are labeled partial
- **AND** the page explains that the census is excluded from official daily
  means

#### Scenario: Corrected v2 hospital total remains historical

- **WHEN** the page displays an exact v2 measurement
- **THEN** it identifies stored known and calculable capacities 666/666 when the
  complete corrected catalog applies
- **AND** does not fabricate v3 availability or deduplication values

#### Scenario: Initial v1 hospital total remains historical

- **WHEN** the page displays an exact v1 measurement
- **THEN** it identifies stored known capacity 658 and calculable capacity 626
  when the complete initial catalog applies
- **AND** does not apply corrected or v3 totals retroactively

## ADDED Requirements

### Requirement: Page reconciles official and physical occupancy safely

For an exact v3 measurement, the page SHALL show an aggregate arithmetic bridge
from legacy occupied rows to official considered occupations using only
persisted reconciliation metadata.

#### Scenario: Complete bridge is displayed

- **WHEN** a v3 measurement has duplicate rows and non-calculable occupied
  positions but no partiality
- **THEN** the bridge shows raw occupied rows, each excluded aggregate category
  and the resulting official numerator
- **AND** the displayed arithmetic closes exactly

#### Scenario: Partial bridge is displayed

- **WHEN** a v3 measurement has conflicts, unidentified occupied rows or unknown
  3A ages
- **THEN** the bridge shows each positive aggregate omission
- **AND** labels the point rate partial and daily-ineligible

#### Scenario: Reconciliation exposes no identity

- **WHEN** the bridge or quality alerts are rendered
- **THEN** they expose no patient name, record number, bed identity, exact age or
  clinical text

### Requirement: Page presents one normalized physical snapshot

The physical section SHALL derive detail from the exact latest census using the
same v3 normalization contract and SHALL clearly separate positions, duplicate
extra rows, conflicts and unidentified rows.

#### Scenario: Physical totals partition identified positions

- **WHEN** the exact census has unambiguous positions in supported statuses
- **THEN** occupied, vacant, reserved, maintenance and isolation counts sum to
  the unambiguous identified-position total
- **AND** conflicts are counted once in a separate status
- **AND** duplicate extra rows are not positions

#### Scenario: Duplicate diagnostic is visible

- **WHEN** exact duplicate rows exist
- **THEN** the page displays their aggregate extra-row count
- **AND** each physical position appears once in sector detail

#### Scenario: Unidentified rows are not called positions

- **WHEN** census rows have no usable bed identity
- **THEN** the page labels them as unidentified legacy rows
- **AND** excludes them from identified-position total

#### Scenario: Official measurement is pending

- **WHEN** the latest census has no exact occupancy measurement
- **THEN** the official section remains pending without reusing an older rate
- **AND** the physical snapshot remains visible with its own capture timestamp

#### Scenario: Anonymous access remains protected on the physical snapshot

- **WHEN** an unauthenticated user requests `/beds/`
- **THEN** the user is redirected to login as before this change
