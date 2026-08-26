# bed-status-capacity-view Delta

## ADDED Requirements

### Requirement: V5 page summarizes the real hospital situation

For a v5 measurement, the authenticated page SHALL render one aggregate
real-situation summary between the official summary and the unit list,
derived only from persisted v5 reconciliation counts, covering identified
patients inside and outside the official rate and the operational states
reported by the source system.

#### Scenario: Real situation shows all identified patients

- **WHEN** v5 reconciliation is available
- **THEN** the summary displays the total of identified patients
- **AND** it breaks that total down into patients in the official rate and
  patients outside it
- **AND** the displayed breakdown closes arithmetically

#### Scenario: Operational states are summarized

- **WHEN** the reconciliation reports operational rows by status
- **THEN** the summary displays counts for vacant, reserved, maintenance and
  isolation states
- **AND** none of those states enters the identified patient totals

#### Scenario: Incomplete identity is surfaced when present

- **WHEN** the reconciliation reports incomplete identity rows
- **THEN** the summary displays that count labeled as not counted
- **AND** that line is omitted when the count is zero

#### Scenario: Real situation summary is private

- **WHEN** the real-situation summary is rendered
- **THEN** it contains no name, record, bed, exact age or source row
  signature

### Requirement: V5 unit headers expose official metrics

For each v5 presentation unit, the page SHALL expose in the always-visible
unit header the persisted official metrics of every official group of that
unit, without requiring expansion, using the same persisted values rendered
in the unit body.

#### Scenario: Calculable group shows capacity and balance

- **WHEN** a unit has one calculable group with registered capacity
- **THEN** its header displays the group patient count, capacity, occupancy
  percentage and balance badges
- **AND** a group within capacity displays its remaining balance
- **AND** no balance badge replaces the persisted values of the body

#### Scenario: Over-capacity group is explicit in the header

- **WHEN** a calculable group exceeds its official capacity
- **THEN** the header displays text `Acima da capacidade` with the
  absolute exceeded-by count, visible without expanding the unit body

#### Scenario: Zero patients are explicit

- **WHEN** a v5 unit has no identified patients
- **THEN** its header displays an explicit zero-patient badge
- **AND** the header never omits the patient-count badge

#### Scenario: Unrated group shows no rate

- **WHEN** a unit's official group is unrated
- **THEN** the header displays the patient count and `fora da taxa oficial`
- **AND** displays no capacity, percentage or balance badge for that group

#### Scenario: Multi-group unit shows one metric set per group

- **WHEN** one unit contains more than one official group, such as the 3A
  Adulto and Infantil partitions
- **THEN** the header displays one metric set per group labeled by partition
- **AND** displays no combined capacity, rate or patient total for the
  merged groups

#### Scenario: Source-code count stays out of the header

- **WHEN** a v5 unit aggregates multiple source codes
- **THEN** the header does not display a source-code count badge
- **AND** the source aliases remain visible in the expanded unit body

### Requirement: V5 page queries are bounded by a fixed budget

The authenticated v5 page SHALL render a number of SQL queries that does not
grow with the number of official groups or memberships of the exact catalog.

#### Scenario: Query count does not scale with catalog size

- **WHEN** the authenticated page renders exact v5 measurements backed by
  catalogs of different group counts
- **THEN** the measured query counts differ by at most a small fixed
  allowance
- **AND** no per-group or per-membership query pattern remains

## MODIFIED Requirements

### Requirement: Over-capacity state is explicit and accessible

The page SHALL display both visual and textual warning when a calculable
group has occupancy greater than 100 percent, visible in the unit header
without expanding the unit body.

#### Scenario: Group exceeds official capacity

- **WHEN** a group measurement has percentage greater than 100.00
- **THEN** its unit header is visually highlighted
- **AND** the unit header contains text indicating over-capacity visible
  without expansion
- **AND** it displays the absolute exceeded-by count

#### Scenario: Group is not over capacity

- **WHEN** a group measurement has percentage less than or equal to 100.00
- **THEN** it does not display the over-capacity warning

### Requirement: V5 page groups identified patients without hiding source evidence

For each v5 presentation unit, the authenticated page SHALL show one patient
item per normalized record within the official group and SHALL show all exact-
run name variants, source aliases and reported beds without persisting them.
Counting policy SHALL be conveyed at the unit level, not per patient item.

#### Scenario: Patient has no bed

- **WHEN** an identified patient has an empty bed value
- **THEN** the patient is listed and labeled `sem leito informado`
- **AND** the patient is counted in the official numerator of its unit

#### Scenario: Patient has multiple reported beds

- **WHEN** duplicate lines of one record in a group report different beds
- **THEN** one patient item lists every distinct bed value
- **AND** the patient counts once

#### Scenario: Different patients share bed text

- **WHEN** two records report the same bed text
- **THEN** both patient items remain visible and counted
- **AND** the page factually reports `pacientes informados com o mesmo leito`
- **AND** does not call either record divergent or non-authoritative

#### Scenario: Patient name varies

- **WHEN** one record has multiple name variants
- **THEN** one patient item displays all variants
- **AND** states `Nome informado de formas diferentes em N linhas`
- **AND** does not select a canonical variant

#### Scenario: Record appears in multiple official groups

- **WHEN** one record is present in different groups
- **THEN** each affected group shows the factual warning
  `Prontuário informado em mais de um setor oficial neste censo`
- **AND** the page does not select a true group

#### Scenario: Counting policy is conveyed at the unit level

- **WHEN** a v5 unit lists identified patients
- **THEN** no per-patient `contado na taxa oficial` or
  `fora da taxa oficial` badge is rendered
- **AND** the counting policy of the unit is visible in its header
- **AND** factual exceptions such as cross-group records, name variants and
  missing beds remain visible

### Requirement: V5 page explains patient-count reconciliation safely

The v5 page SHALL render aggregate persisted reconciliation from patient lines
to official numerator with factual quality labels and no identifiers, after
the unit list and in a container collapsed by default.

#### Scenario: Patient bridge is displayed

- **WHEN** v5 reconciliation is available
- **THEN** it displays valid identity rows, duplicate lines, standard patients,
  unrated patients, pending/unmapped patients and official numerator
- **AND** displayed arithmetic closes

#### Scenario: Age fallback is explained

- **WHEN** 3A patients use RN or Adulto fallback
- **THEN** the aggregate section reports counts by fallback reason
- **AND** explains that fallback patients remain counted and daily-eligible

#### Scenario: Aggregate section is private

- **WHEN** reconciliation is rendered
- **THEN** it contains no name, record, bed, exact age or source row signature

#### Scenario: Bridge is compact by default

- **WHEN** the v5 page is rendered
- **THEN** the reconciliation section appears after the unit list
- **AND** its container is collapsed by default
- **AND** expanding it reveals the same aggregate content as before
