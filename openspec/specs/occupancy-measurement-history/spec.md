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
by the applicable catalog, divide the resulting numerator once by official
capacity and SHALL NOT cap the result at 100 percent. V1/v2 SHALL preserve row
semantics, v3/v4 SHALL preserve their position semantics and v5 SHALL count
valid identified patients deduplicated by normalized record within the official
group without using bed identity.

#### Scenario: V1 through v4 remain historical

- **WHEN** v5 becomes supported
- **THEN** persisted v1–v4 measurements, reconciliations and summaries remain
  unchanged
- **AND** no old census is recalculated or reinterpreted

#### Scenario: V5 patient without bed counts

- **WHEN** a v5 standard-group row has a valid numeric record and valid patient
  name but no usable bed value
- **THEN** the patient enters the group numerator
- **AND** absence of bed is retained only as aggregate information and
  authenticated exact-run detail

#### Scenario: Different patients share a bed

- **WHEN** two valid records in the same group report the same bed text
- **THEN** both patients enter the numerator
- **AND** the bed text neither deduplicates nor suppresses either patient

#### Scenario: Percentage, balance and excess remain deterministic

- **WHEN** a v5 calculable group is materialized
- **THEN** percentage uses `ROUND_HALF_UP` with two decimal places and may exceed
  100 percent
- **AND** balance is `max(capacity - identified patients, 0)`
- **AND** excess is `max(identified patients - capacity, 0)`
- **AND** hospital balance and excess are summed independently by group

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

### Requirement: V4 classifies physical conflicts by their effect

For `occupancy-v4`, the system SHALL collapse exact duplicates before conflict
classification, SHALL use source identity plus bed as the physical key and
SHALL classify remaining ambiguity without using record number as a position
key.

#### Scenario: Exact duplicates are consolidated first

- **WHEN** equivalent rows repeat under one physical key
- **THEN** one signature remains for conflict classification
- **AND** extra equivalent rows are recorded as duplicates
- **AND** the corresponding position can still count once

#### Scenario: Occupant evidence diverges but occupation agrees

- **WHEN** unique alternatives under one key are occupied and use the same
  effective age selector but differ in name or record evidence
- **THEN** the result is `occupant_conflict`
- **AND** the occupied position counts once
- **AND** candidate identity remains non-authoritative

#### Scenario: Status evidence diverges

- **WHEN** unique alternatives under one key have different statuses
- **THEN** the result is `status_conflict`
- **AND** no preferred status is selected
- **AND** the position is omitted from official numerators

#### Scenario: Partition selector diverges

- **WHEN** unique occupied alternatives in a partitioned code resolve to
  different or unknown selectors
- **THEN** the result is `age_conflict`
- **AND** the position is omitted from partitioned official numerators

#### Scenario: Occupied row lacks physical identity

- **WHEN** an occupied row has no usable bed identity
- **THEN** it remains an unidentified raw case
- **AND** it is omitted from official numerators because it cannot be safely
  deduplicated

#### Scenario: Shared record in different beds remains distinct

- **WHEN** the same record evidence appears in two normalized beds
- **THEN** v4 preserves two positions
- **AND** performs no patient-level deduplication or mother-child inference

### Requirement: V4 reconciliation distinguishes every treatment

Each v4 measurement SHALL persist a schema 2 allowlisted aggregate
reconciliation whose occupied-row bridge and counted-position bridge close
exactly and whose labels distinguish consolidation, ambiguity, missing identity
and policy scope.

#### Scenario: Raw occupied-row bridge closes

- **WHEN** a v4 measurement is materialized
- **THEN** raw occupied rows equal duplicate occupied extras plus occupant
  conflict extras plus occupied rows omitted by status conflict, age conflict,
  missing identity or unknown partition plus counted occupied positions
- **AND** all values are nonnegative integers

#### Scenario: Counted occupied-position bridge closes

- **WHEN** a v4 measurement contains calculable, unrated, unmapped or pending
  occupied positions
- **THEN** counted occupied positions equal official numerator plus separate
  counts for each non-calculable policy state
- **AND** intentional `unrated` evidence is not conflated with `unmapped`

#### Scenario: Occupant conflict contributes one representative

- **WHEN** an occupant-only conflict contains multiple unique occupied
  alternatives and exact duplicate extras
- **THEN** one occupied position enters the counted-position bridge
- **AND** remaining unique alternatives and duplicate extras are accounted for
  exactly once in the raw-row bridge

#### Scenario: Physical status partition remains closed

- **WHEN** v4 contains unambiguous positions, occupant conflicts, status
  conflicts, age conflicts, duplicates and unidentified rows
- **THEN** each position or raw exception belongs to one documented aggregate
  category
- **AND** no duplicate extra row increases physical-position total

#### Scenario: V4 reconciliation remains private

- **WHEN** raw alternatives contain names, records, beds or exact ages
- **THEN** persisted measurement and group history contain none of those values
- **AND** logs and errors contain no physical key or row signature

### Requirement: V4 records actionable quality without rejecting accepted census

Every successfully materialized v4 measurement SHALL record whether quality
warnings exist, while remaining a valid immutable point measurement for a
census already accepted by the primary extraction gate.

#### Scenario: Clean v4 measurement

- **WHEN** a v4 measurement has no conflict, unidentified occupied row, unknown
  partition or occupied unmapped position
- **THEN** its v4 quality warning is false

#### Scenario: V4 measurement has actionable gap

- **WHEN** v4 contains any occupant, status or age conflict, occupied row without
  position, unknown partition or occupied unmapped position
- **THEN** its quality warning is true
- **AND** aggregate reason counts remain available for summary and presentation

#### Scenario: Repeated v4 materialization is idempotent

- **WHEN** v4 materialization is requested twice for the same census run
- **THEN** the original measurement, warning and reconciliation are returned
- **AND** no group or daily summary is recalculated

### Requirement: V4 preserves prior algorithms and activation boundaries

The system SHALL dispatch v4 only from a future catalog explicitly declaring
`occupancy-v4` and SHALL preserve all prior measurements, summaries and
catalogs without backfill.

#### Scenario: V4 catalog becomes applicable

- **WHEN** an accepted census local date uses a catalog declaring
  `occupancy-v4`
- **THEN** its measurement records `occupancy-v4`
- **AND** applies typed conflict semantics

#### Scenario: Earlier v3 remains strict

- **WHEN** an earlier v3 measurement is physically partial
- **THEN** it keeps its original omitted numerator and daily-ineligible meaning
- **AND** v4 does not reinterpret its reconciliation or warning state

#### Scenario: Deployment does not activate v4

- **WHEN** v4 code and migrations are deployed
- **THEN** the applicable v3 catalog remains selected until a future v4 catalog
  becomes effective
- **AND** no startup, migration or build performs activation

### Requirement: V5 recognizes patient identity deterministically

For `occupancy-v5`, a census row SHALL be an identified-patient row only when
its normalized record is non-empty and digits-only and its normalized name is
non-empty and not an operational-state marker. Record identity SHALL remain a
string so leading zeros are preserved.

#### Scenario: Numeric record and valid name are accepted

- **WHEN** record ` 0012345 ` and a non-operational non-empty name are observed
- **THEN** the normalized identity is textual `0012345`
- **AND** the row is eligible for patient counting

#### Scenario: Non-numeric record is incomplete

- **WHEN** the record is blank, punctuation-only or contains a non-digit
- **THEN** the row does not become an identified patient
- **AND** any partial identity evidence is counted only as an aggregate
  incomplete-identity case

#### Scenario: Operational marker is not a patient name

- **WHEN** the normalized name represents vacancy, cleaning/maintenance,
  reservation or isolation
- **THEN** the row is an operational state rather than an identified patient
- **AND** it does not enter an official numerator

#### Scenario: Incomplete identity is not silently discarded

- **WHEN** exactly one of record or valid name is present
- **THEN** v5 records one aggregate incomplete-identity row
- **AND** the authenticated exact-run page can display it without copying it to
  aggregate history or logs

### Requirement: V5 deduplicates records within each official group

V5 SHALL count a normalized record at most once per official group, including
across multiple source codes mapped to that group, and SHALL not perform global
hospital deduplication across different official groups.

#### Scenario: Duplicate rows in one source count once

- **WHEN** one record appears in multiple rows mapped to the same official group
- **THEN** the group numerator includes one patient
- **AND** aggregate reconciliation records the additional lines as duplicate
  identity rows

#### Scenario: Shared group deduplicates across codes

- **WHEN** one record appears under two source codes belonging to the same
  Cardio official group
- **THEN** it counts once in that group
- **AND** all source and bed evidence remains available only for authenticated
  exact-run presentation

#### Scenario: Record appears in different groups

- **WHEN** one normalized record appears in two different official groups
- **THEN** it counts once in each group
- **AND** hospital numerator remains the sum of group numerators
- **AND** v5 records only an aggregate cross-group record count as a factual
  quality warning

#### Scenario: Name variants do not create patients

- **WHEN** one record has multiple normalized names inside a group
- **THEN** it counts once
- **AND** aggregate quality records one patient with name variation
- **AND** no name variant is persisted or chosen as authoritative

### Requirement: V5 partitions identified 3A patients with deterministic fallback

For the age-partitioned source code, v5 SHALL deduplicate by record before group
assignment, SHALL prefer agreeing reliable age bands and SHALL use normalized
name prefix fallback when reliable age is absent or contradictory.

#### Scenario: Reliable child age wins

- **WHEN** all reliable lines for one record resolve to `under_12`
- **THEN** the patient enters only `OBST-3A-INFANTIL`
- **AND** unknown duplicate lines do not trigger name fallback

#### Scenario: Reliable adult age wins

- **WHEN** all reliable lines for one record resolve to `age_12_or_over`
- **THEN** the patient enters only `OBST-3A-ADULTO`

#### Scenario: Unknown age with RN prefix becomes child

- **WHEN** no reliable age exists and any normalized valid name starts
  literally with `RN`
- **THEN** the patient enters only the Infantil group
- **AND** the aggregate RN-fallback counter increments

#### Scenario: Unknown age without RN prefix becomes adult

- **WHEN** no reliable age exists and no normalized name starts literally with
  `RN`
- **THEN** the patient enters only the Adulto group
- **AND** the aggregate non-RN fallback counter increments

#### Scenario: Reliable bands conflict

- **WHEN** duplicate lines of one record contain both reliable age bands
- **THEN** the reliable age is treated as contradictory
- **AND** the same literal RN fallback determines exactly one group
- **AND** aggregate age-conflict fallback count increments

#### Scenario: Similar prefix is not RN

- **WHEN** a fallback name starts with `R.N.` or another text whose first two
  normalized characters are not exactly `RN`
- **THEN** it uses Adulto fallback

### Requirement: V5 reconciliation is closed, aggregate and private

Each v5 measurement SHALL persist a versioned allowlisted aggregate
reconciliation explaining valid identity rows, within-group duplicate rows,
identified patients by policy, quality reasons and operational-state rows
without storing row-level identity.

#### Scenario: Identity bridge closes

- **WHEN** a v5 measurement is materialized
- **THEN** valid identity rows equal within-group duplicate identity rows plus
  identified-patient assignments to standard, unrated, pending and unmapped
  groups
- **AND** every value is a nonnegative integer

#### Scenario: Patient quality remains aggregate

- **WHEN** records cross groups, names vary, identity is incomplete or age uses
  fallback
- **THEN** reconciliation stores only aggregate counts by reason
- **AND** contains no name, record, bed, exact age or row signature

#### Scenario: Operational rows stay outside occupancy

- **WHEN** the census contains vacant, reserved, maintenance or isolation rows
- **THEN** reconciliation counts their states separately
- **AND** they neither enter the numerator nor reduce fixed capacity
- **AND** repeated or divergent bed-state text is not an occupancy conflict

#### Scenario: Reconciliation mismatch aborts atomically

- **WHEN** the v5 arithmetic does not close
- **THEN** no parent, group or summary row is persisted
- **AND** the error contains no patient or bed identifier

### Requirement: V5 quality is actionable without suppressing the measurement

Every successfully materialized v5 measurement SHALL remain daily-eligible and
SHALL set aggregate quality warning when identity, cross-group, name-variation,
age-fallback or occupied-unmapped evidence requires attention.

#### Scenario: Patient without bed remains valid

- **WHEN** an identified patient lacks a bed
- **THEN** that patient is counted
- **AND** absence of bed is reported informationally without making the point
  partial or ineligible

#### Scenario: Fallback classification remains eligible

- **WHEN** one or more 3A patients use RN or Adulto fallback
- **THEN** the measurement quality warning is true
- **AND** the measurement contributes to daily statistics

#### Scenario: Repeated v5 materialization is idempotent

- **WHEN** v5 materialization is requested twice for the same run
- **THEN** the original measurement, groups, reconciliation and summary are
  returned unchanged

### Requirement: V5 preserves activation boundaries and clinical flow

The system SHALL dispatch v5 only from a future immutable catalog declaring
`occupancy-v5`, SHALL preserve v1–v4 and SHALL not block clinical processing of
an otherwise accepted census.

#### Scenario: V5 catalog becomes applicable

- **WHEN** an accepted census local date uses a catalog declaring
  `occupancy-v5`
- **THEN** its measurement records `occupancy-v5`
- **AND** applies identified-patient semantics

#### Scenario: Deployment does not activate v5

- **WHEN** v5 code and migrations are deployed
- **THEN** v4 remains applicable until the future v5 catalog date
- **AND** startup, migration and build create no catalog or measurement

#### Scenario: Clinical processing continues

- **WHEN** a v5 measurement has quality warnings or patients without beds
- **THEN** census batch closure and clinical patient processing continue
- **AND** no Celery, Redis or new worker is introduced
