## MODIFIED Requirements

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

## ADDED Requirements

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

#### Scenario: Repeated materialization is idempotent

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
