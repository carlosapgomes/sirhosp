# Spec Delta

## MODIFIED Requirements

### Requirement: V5 page summarizes the real hospital situation

For a v5 measurement, the authenticated page SHALL render one aggregate
real-situation summary between the official summary and the unit list,
derived only from persisted v5 reconciliation counts, covering identified
patients inside and outside the official rate and the operational states of
beds reported by the source system, counted per bed rather than per census
line.

#### Scenario: Real situation shows all identified patients

- **WHEN** v5 reconciliation is available
- **THEN** the summary displays the total of identified patients
- **AND** it breaks that total down into patients in the official rate and
  patients outside it
- **AND** the displayed breakdown closes arithmetically

#### Scenario: Operational states are summarized

- **WHEN** the reconciliation reports operational positions by status
- **THEN** the summary displays counts for vacant, reserved, maintenance and
  isolation states
- **AND** each bed whose census lines agree on one state counts exactly once
  in that state, regardless of how many lines repeat it
- **AND** none of those states enters the identified patient totals

#### Scenario: Divergent beds are excluded and surfaced

- **WHEN** one bed carries divergent operational states across its census
  lines, including occupied lines plus operational-marker lines
- **THEN** no state counts for that bed in the summary badges
- **AND** the summary displays the count of divergent beds labeled as not
  counted
- **AND** that line is omitted when the count is zero

#### Scenario: Bedless operational lines stay out of the badges

- **WHEN** operational census lines carry no bed
- **THEN** they do not enter any state badge of the summary
- **AND** their count is available on the operational-states detail page
  rather than on the summary card

#### Scenario: Incomplete identity is surfaced when present

- **WHEN** the reconciliation reports incomplete identity rows
- **THEN** the summary displays that count labeled as not counted
- **AND** that line is omitted when the count is zero

#### Scenario: Real situation summary is private

- **WHEN** the real-situation summary is rendered
- **THEN** it contains no name, record, bed, exact age or source row
  signature

#### Scenario: Historical measurements keep their persisted semantics

- **WHEN** the exact measurement's reconciliation predates the per-bed
  counting schema
- **THEN** the summary keeps rendering the persisted line-based counts
  without recomputing them
- **AND** the operational-states detail page explains that historical
  semantics for that photo

## ADDED Requirements

### Requirement: V5 operational-states detail page

The authenticated operational-states detail page SHALL explain, for one
exact v5 measurement and grouped by source sector, how every operational
bed state was counted: unambiguous beds by state, divergent beds, collapsed
repeated lines, occupied-plus-state cases and bedless operational lines,
without nominal data.

#### Scenario: Detail is pinned to the exact measurement photo

- **WHEN** an authenticated user opens the operational-states detail from
  the summary card
- **THEN** the page scopes to the census photo of that card's measurement
- **AND** its header displays that photo's capture time
- **AND** no other or newer census is silently substituted

#### Scenario: Invalid or non-v5 measurement is rejected

- **WHEN** the detail page is requested for a nonexistent measurement id
  or for a measurement whose algorithm is not `occupancy-v5`
- **THEN** the page responds with a not-found status
- **AND** renders no operational evidence

#### Scenario: Stale photo is flagged

- **WHEN** the opened measurement no longer owns the latest census photo
- **THEN** the page displays a notice that a more recent census exists
- **AND** keeps rendering the requested photo's detail

#### Scenario: Per-sector breakdown is complete

- **WHEN** the photo's census carries operational lines
- **THEN** the page groups the evidence by source sector
- **AND** each sector shows unambiguous beds by state, divergent beds with
  their distinct informed states, repeated lines collapsed per bed,
  occupied-plus-state cases and bedless operational line counts
- **AND** sectors without any of those cases show their unambiguous counts
  only

#### Scenario: Arithmetic closes with the summary card

- **WHEN** the measurement's reconciliation uses the per-bed counting
  schema
- **THEN** the page's unambiguous beds summed by state equal the summary
  card badges
- **AND** its divergent-bed count equals the summary's divergent line
- **AND** the page exposes this closure without requiring user arithmetic

#### Scenario: Historical row-based photo is explained

- **WHEN** the measurement's reconciliation predates the per-bed counting
  schema
- **THEN** the page labels that the summary badges of that photo counted
  census lines
- **AND** lists the divergent, repeated and bedless cases of that photo so
  the line-based number can be audited

#### Scenario: Detail page carries no nominal data

- **WHEN** the detail page is rendered for any sector or case
- **THEN** it displays no patient name and no patient record
- **AND** operational evidence is limited to sector identity, bed label,
  state classification and integer counts

#### Scenario: Detail page anonymous access stays protected

- **WHEN** an unauthenticated user requests the operational-states detail
  page
- **THEN** the response redirects to login
- **AND** no operational or patient detail is rendered
