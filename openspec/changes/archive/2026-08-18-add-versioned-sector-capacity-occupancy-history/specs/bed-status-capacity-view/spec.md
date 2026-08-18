# bed-status-capacity-view Specification

## ADDED Requirements

### Requirement: Bed status page uses the exact latest-census measurement

The authenticated `/beds` page SHALL enrich the latest census only when an
occupancy measurement exists for the exact `IngestionRun` represented by that
census.

#### Scenario: Exact measurement is available

- **WHEN** the latest census rows belong to one run with an occupancy
  measurement
- **THEN** the page displays capacity statistics from that measurement
- **AND** it displays the census capture time and catalog effective date

#### Scenario: Latest measurement is pending

- **WHEN** the latest census has no exact occupancy measurement
- **THEN** the page preserves its existing raw sector and bed-status table
- **AND** it labels capacity statistics as pending or unavailable
- **AND** it does not calculate capacity ad hoc in the view

#### Scenario: Older measurement is not reused

- **WHEN** an older census has a measurement but the latest census does not
- **THEN** the page does not display the older percentage as current

#### Scenario: Anonymous access remains protected

- **WHEN** an unauthenticated user requests `/beds/`
- **THEN** the user is redirected to login as before this change

### Requirement: Capacity rows follow official groups

When an exact measurement exists, the page SHALL show one summary row per
measured capacity group or unmapped sector and SHALL preserve source-sector and
bed detail inside the expansion.

#### Scenario: Shared group appears once

- **WHEN** more than one source code belongs to one capacity group
- **THEN** the page shows one official group row with combined counts and one
  capacity
- **AND** the expansion identifies the contributing source sectors and beds

#### Scenario: Existing bed detail remains available

- **WHEN** an authenticated user expands a measured group
- **THEN** individual beds retain their existing status labels
- **AND** occupied beds retain the patient display already authorized on this
  page

#### Scenario: Unmapped sector remains visible

- **WHEN** the latest measurement contains an `unmapped` sector
- **THEN** the page shows it with its observed counts
- **AND** capacity and percentage are displayed as unavailable

### Requirement: Page communicates registered legacy occupancy

The page SHALL label the indicator as `Lotação registrada no sistema legado`
and SHALL not imply that suspected stale patients were removed.

#### Scenario: Centro Obstétrico contains suspected stale occupants

- **WHEN** the `CO` measurement includes occupied rows suspected of stale
  administrative status
- **THEN** the displayed numerator and percentage match the raw measurement
- **AND** no adjusted percentage is displayed

### Requirement: Over-capacity state is explicit and accessible

The page SHALL display both visual and textual warning when a calculable group
has occupancy greater than 100 percent.

#### Scenario: Group exceeds official capacity

- **WHEN** a group measurement has percentage greater than 100.00
- **THEN** its row is visually highlighted
- **AND** it contains text indicating over-capacity
- **AND** it displays the absolute exceeded-by count

#### Scenario: Group is not over capacity

- **WHEN** a group measurement has percentage less than or equal to 100.00
- **THEN** it does not display the over-capacity warning

### Requirement: Page distinguishes capacity and calculation coverage

The page SHALL display capacity coverage separately from calculable occupancy
coverage using the observed-sector denominator from the latest measurement.

#### Scenario: Initial complete census coverage is shown

- **WHEN** all 47 initial codes are observed
- **THEN** the page displays `44 de 47 setores com capacidade cadastrada`
- **AND** it displays `43 de 47 setores com lotação calculável`

#### Scenario: Obstetrícia 3A remains pending

- **WHEN** the page displays `OBST-3A` under the initial catalog
- **THEN** it displays capacity 32
- **AND** it displays that lotação awaits the cama-berço mapping
- **AND** it does not show an approximate percentage

#### Scenario: Sector has no official capacity

- **WHEN** a group is `unrated` or `unmapped`
- **THEN** the page displays `Capacidade não cadastrada` or equivalent
- **AND** it does not display zero percent

### Requirement: Hospital total uses only calculable groups

The page SHALL display hospital occupancy using the measurement's calculable
numerator and calculable capacity, while separately showing known capacity.

#### Scenario: Initial catalog hospital totals are displayed

- **WHEN** a measurement uses the initial catalog with all 47 codes observed
- **THEN** the page identifies known capacity 658
- **AND** it identifies calculable capacity 626
- **AND** its hospital percentage excludes pending, unrated and unmapped groups
