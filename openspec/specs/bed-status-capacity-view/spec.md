# bed-status-capacity-view Specification

## Purpose

TBD - created by archiving change add-versioned-sector-capacity-occupancy-history. Update Purpose after archive.

## Requirements

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

### Requirement: Page uses clean versioned source names

The v4 page SHALL use the exact catalog membership's clean source alias as the
primary source label and SHALL retain the raw source name only as secondary
provenance.

#### Scenario: Prefixed source label has clean alias

- **WHEN** the exact source row has a technical prefix such as a floor/location
  code
- **THEN** the unit displays the clean catalog alias as primary text
- **AND** may display the raw label as subordinate `Nome no sistema de origem`

#### Scenario: Alias belongs to exact catalog

- **WHEN** a newer catalog later changes an alias
- **THEN** historical exact measurements and presentations retain their
  applicable catalog context
- **AND** the current catalog is never substituted ad hoc

#### Scenario: Historical membership lacks alias

- **WHEN** a v1/v2/v3 catalog has no clean source alias
- **THEN** presentation uses its documented historical fallback
- **AND** does not edit or backfill the membership

### Requirement: Page explains how occupied evidence was treated

For v4, the page SHALL render a section `Como as ocupações foram tratadas` from
persisted aggregate reconciliation and SHALL distinguish consolidation,
computation under warning, omission by ambiguity, missing identity and policy
scope.

#### Scenario: Duplicate wording explains consolidation

- **WHEN** duplicate occupied extras are positive
- **THEN** the page labels them `Linhas duplicadas consolidadas`
- **AND** explains that the corresponding position was counted once

#### Scenario: Occupant-only conflict was counted

- **WHEN** v4 counted an occupied position with divergent occupant evidence
- **THEN** the page reports positions counted with occupant warning separately
- **AND** explains that no patient alternative was treated as authoritative

#### Scenario: Status or age conflict was not counted

- **WHEN** v4 omitted occupied evidence because status or partition age was
  ambiguous
- **THEN** the page reports positions and affected occupied lines by reason
- **AND** states explicitly that they were not computed in the official
  numerator

#### Scenario: Missing position was not counted

- **WHEN** occupied rows lack usable bed identity
- **THEN** the page labels them `não computadas por ausência de posição`
- **AND** does not call them physical positions

#### Scenario: Unrated position is valid but out of scope

- **WHEN** unambiguous occupied positions belong to an `unrated` group
- **THEN** the page labels them valid positions outside the official-rate scope
- **AND** does not present them as a data-quality failure

#### Scenario: Unmapped and pending remain distinct

- **WHEN** occupied evidence is unmapped or linked-pending
- **THEN** each state receives its own label and count
- **AND** neither is conflated with intentional `unrated` policy

#### Scenario: Aggregate explanation remains private

- **WHEN** the treatment section is rendered
- **THEN** it contains no patient name, record number, bed, exact age or
  clinical text

### Requirement: Authenticated users can inspect non-authoritative quality cases

Every authenticated `/beds` user SHALL be able to expand v4 conflict and
unidentified-row cases from the exact latest census, while anonymous users
remain redirected and no candidate is selected as authoritative.

#### Scenario: Occupant conflict alternatives are visible

- **WHEN** an authenticated user expands an occupant-conflict position
- **THEN** each distinct alternative is visible with the existing authorized
  patient detail and equivalent-row count
- **AND** every alternative is labeled `registro divergente — não autoritativo`
- **AND** no alternative is styled or linked as the chosen truth

#### Scenario: Status or age alternatives are visible

- **WHEN** an authenticated user expands a status or age conflict
- **THEN** all distinct alternatives and the conflict reason are visible
- **AND** the page does not choose a status or age group

#### Scenario: Unidentified occupied row is actionable

- **WHEN** an authenticated user expands a source unit with an occupied row
  lacking bed identity
- **THEN** the row appears in a separate quality-case list
- **AND** it is not counted or labeled as a physical position

#### Scenario: Exact duplicates are not repeated

- **WHEN** alternatives contain equivalent duplicate lines
- **THEN** the detail shows one alternative plus occurrence count
- **AND** does not repeat identical patient rows

#### Scenario: Anonymous access remains protected on quality details

- **WHEN** an unauthenticated user requests `/beds/`
- **THEN** the user is redirected to login
- **AND** no quality-case detail is rendered

#### Scenario: Details are not persisted in aggregate history

- **WHEN** quality cases are assembled for the page
- **THEN** names, records and beds exist only in exact-run presentation memory
- **AND** none is copied to measurement, daily summary, log or report

### Requirement: Hospital total identifies v4 warnings without suppressing the day

The official summary SHALL display persisted v4 considered occupancy,
availability, independent excess and rate, SHALL mark quality warnings and SHALL
explain that warned v4 measurements remain eligible for daily statistics.

#### Scenario: Warned v4 point is displayed

- **WHEN** the exact v4 measurement has quality warnings
- **THEN** official cards are labeled `com ressalvas de qualidade`
- **AND** the page identifies considered occupations rather than claiming
  conflict-free occupancy
- **AND** explains that the measurement still contributes to daily statistics

#### Scenario: Clean v4 point is displayed

- **WHEN** the exact v4 measurement has no warning
- **THEN** no warning badge is displayed
- **AND** persisted official values remain unchanged

#### Scenario: Historical v3 partial point remains historical

- **WHEN** the exact measurement uses v3 and is physically partial
- **THEN** the page retains its original daily-ineligible explanation
- **AND** does not apply v4 wording or eligibility retroactively

#### Scenario: Exact-run remains mandatory

- **WHEN** the latest census lacks its own measurement
- **THEN** official summary remains pending
- **AND** no older measurement, alias, warning or rate is reused

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

#### Scenario: V5 anonymous access remains protected

- **WHEN** an unauthenticated user requests `/beds/`
- **THEN** response redirects to login as before
- **AND** no patient or operational detail is rendered

#### Scenario: V5 terminology is unambiguous

- **WHEN** a v5 page is rendered
- **THEN** user-facing v5 sections contain none of `registro divergente`,
  `não autoritativo` or generic physical `conflito`
- **AND** historical algorithm labels remain available only where needed to
  explain older measurements
