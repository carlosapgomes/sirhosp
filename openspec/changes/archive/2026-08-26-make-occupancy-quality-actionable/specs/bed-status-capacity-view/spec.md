## MODIFIED Requirements

### Requirement: Capacity rows follow official groups

When an exact measurement exists, `/beds` SHALL present persisted official
group values and normalized source positions inside one unified expandable list
of presentation units, rather than maintaining two independent detailed lists.

#### Scenario: One-to-one mapping appears once

- **WHEN** one official group maps to one source code
- **THEN** one presentation unit shows its official values and physical source
  summary
- **AND** every normalized position appears once in the unit detail

#### Scenario: Shared official group has multiple sources

- **WHEN** one official group maps to multiple source codes
- **THEN** one presentation unit shows the shared official capacity once
- **AND** shows each clean source alias and its positions separately inside the
  same expansion

#### Scenario: One source is split across official groups

- **WHEN** code `654` maps to Adulto and Infantil official groups
- **THEN** one physical presentation unit shows both official rows
- **AND** shows the source 3A positions only once
- **AND** no hardcoded code-specific branch is required to build the unit

#### Scenario: Unrated shared unit remains visible

- **WHEN** CO maps multiple source codes to one unrated group
- **THEN** one unit shows CO outside the official rate
- **AND** retains every clean source alias and normalized physical status

#### Scenario: Unmapped source has its own warning unit

- **WHEN** an exact census contains a source absent from the catalog
- **THEN** one warning unit preserves its physical evidence
- **AND** does not invent official capacity or clean catalog identity

### Requirement: Page communicates official and source-system realities

The page SHALL use user-facing terminology `sistema de origem`, SHALL retain two
semantically separate aggregate summaries and SHALL make treatment of every
quality category explicit.

#### Scenario: Aggregate summaries remain separate

- **WHEN** an authenticated user opens `/beds` with a v4 exact measurement
- **THEN** `Capacidade oficial e ocupação` remains visibly distinct
- **AND** `Posições registradas no sistema de origem` remains visibly distinct
- **AND** neither summary is hidden behind a tab

#### Scenario: Detailed list is unified

- **WHEN** aggregate summaries have been rendered
- **THEN** exactly one detailed section `Setores e posições` follows
- **AND** no second long sector list requires the user to find the sector again

#### Scenario: Legacy terminology is absent from v4 UI

- **WHEN** the v4 page is rendered
- **THEN** user-facing headings and explanations do not use `sistema legado`
- **AND** technical historical algorithm labels remain accurate where needed

#### Scenario: Physical labels do not become official labels

- **WHEN** source position states are displayed
- **THEN** vacant state is not called official availability
- **AND** the source summary displays no official rate

## RENAMED Requirements

- FROM: `### Requirement: Page communicates registered legacy occupancy`
- TO: `### Requirement: Page communicates official and source-system realities`

## ADDED Requirements

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

#### Scenario: Anonymous access remains protected

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
