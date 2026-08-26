## MODIFIED Requirements

### Requirement: Capacity rows follow official groups

When an exact v5 measurement exists, `/beds` SHALL present one unified
expandable list derived from the exact catalog graph, with official persisted
values and identified patients deduplicated by official group rather than by
physical bed.

#### Scenario: Shared group lists patient once

- **WHEN** one record appears under multiple source codes of the same official
  group
- **THEN** the unit lists one patient and one contribution to the official
  numerator
- **AND** retains every source alias and reported bed in its authenticated detail

#### Scenario: 3A lists patient in one partition

- **WHEN** a v5 record from code 654 is resolved by reliable age or fallback
- **THEN** it appears once under Adulto or Infantil
- **AND** never appears in both group numerators
- **AND** no combined 3A capacity/rate is created

#### Scenario: Unrated unit lists patients without rate

- **WHEN** identified patients belong to CO or another unrated group
- **THEN** the unit lists those patients and source states
- **AND** displays no capacity, balance, percentage or excess

### Requirement: Page communicates official and source-system realities

The page SHALL use `sistema de origem`, SHALL preserve exact-run official values
and SHALL distinguish patient occupancy from the operational states and bed
texts reported by the source.

#### Scenario: V5 headings are explicit

- **WHEN** an authenticated user opens a v5 exact census
- **THEN** the official summary identifies patients versus capacity
- **AND** the detailed section is titled `Setores, pacientes e estados de leitos`
- **AND** it does not imply that reported bed labels define the numerator

#### Scenario: Historical UI remains historical

- **WHEN** the exact measurement uses v1–v4
- **THEN** its stored official values remain unchanged
- **AND** v5 patient counting is not applied ad hoc by the view

### Requirement: Hospital total uses only calculable groups

The v5 official summary SHALL display one official-capacity value, identified
patients from calculable groups, non-compensated official balance, independent
excess and rate from the exact persisted measurement.

#### Scenario: V5 summary has no duplicate capacity cards

- **WHEN** known and calculable capacity both equal the official capacity
- **THEN** v5 renders one card `Capacidade oficial`
- **AND** does not render separate `Capacidade conhecida` or
  `Capacidade calculável` cards

#### Scenario: Coverage is secondary metadata

- **WHEN** the complete v5 catalog applies
- **THEN** the page communicates 39 of 43 sectors with capacity and calculation
  and four outside the rate as subordinate metadata
- **AND** does not repeat 666 in coverage cards

#### Scenario: Patient-based official cards are clear

- **WHEN** a v5 measurement is displayed
- **THEN** the numerator card is `Pacientes identificados`
- **AND** availability wording is `Saldo da capacidade oficial`
- **AND** explanatory text states that saldo is not a nominal vacant-bed list

## ADDED Requirements

### Requirement: V5 page groups identified patients without hiding source evidence

For each v5 presentation unit, the authenticated page SHALL show one patient
item per normalized record within the official group and SHALL show all exact-
run name variants, source aliases and reported beds without persisting them.

#### Scenario: Patient has no bed

- **WHEN** an identified patient has an empty bed value
- **THEN** the patient is listed and labeled `sem leito informado`
- **AND** official detail shows that the patient was counted

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

### Requirement: V5 page separates incomplete identity and operational states

The v5 detail SHALL render incomplete identity separately from operational
source rows, and neither category SHALL be described as patient-position
conflict.

#### Scenario: Incomplete identity is visible but not counted

- **WHEN** a row has only valid record or only apparent patient name, or has an
  invalid record format
- **THEN** it appears under `Identificação incompleta — não contada`
- **AND** the page does not call it a patient or a physical conflict

#### Scenario: Operational rows retain source state

- **WHEN** rows represent vacancy, reservation, maintenance or isolation
- **THEN** every row is shown with its state and reported bed, if any
- **AND** none enters the patient numerator or reduces official capacity

#### Scenario: Same bed has multiple operational states

- **WHEN** the same normalized bed text has different operational-state rows
- **THEN** all states remain visible
- **AND** the page reports `estados informados para o mesmo leito`
- **AND** it does not choose a state or add an occupancy-quality conflict

#### Scenario: Single operational row is not conflict

- **WHEN** one v5 row is solely vacant, reserved, maintenance or isolation
- **THEN** it appears exactly as that state
- **AND** no `conflito`, `registro divergente` or `não autoritativo` label appears

### Requirement: V5 page explains patient-count reconciliation safely

The v5 page SHALL render aggregate persisted reconciliation from patient lines
to official numerator with factual quality labels and no identifiers.

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

### Requirement: V5 exact-run authorization and privacy are preserved

V5 presentation SHALL use only the latest census exact measurement, SHALL remain
available to authenticated users under existing authorization and SHALL keep all
row-level identity ephemeral.

#### Scenario: Exact measurement is pending

- **WHEN** the latest census lacks its own measurement
- **THEN** official values remain pending
- **AND** no older v5 numerator, catalog or patient grouping is reused

#### Scenario: Authenticated user expands patient detail

- **WHEN** an authenticated user expands a v5 unit
- **THEN** authorized names, records and links may be rendered from exact-run
  snapshots in memory
- **AND** none is copied to measurement, summary, logs or reports

#### Scenario: Anonymous access remains protected

- **WHEN** an unauthenticated user requests `/beds/`
- **THEN** response redirects to login as before
- **AND** no patient or operational detail is rendered

#### Scenario: V5 terminology is unambiguous

- **WHEN** a v5 page is rendered
- **THEN** user-facing v5 sections contain none of `registro divergente`,
  `não autoritativo` or generic physical `conflito`
- **AND** historical algorithm labels remain available only where needed to
  explain older measurements
