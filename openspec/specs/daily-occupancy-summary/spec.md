# daily-occupancy-summary Specification

## Purpose

TBD - created by archiving change add-versioned-sector-capacity-occupancy-history. Update Purpose after archive.

## Requirements

### Requirement: Each measured local day has one persisted summary

The system SHALL persist one hospital daily occupancy summary for each local
date with at least one occupancy measurement and SHALL associate it with that
day's catalog and algorithm version.

#### Scenario: First measurement creates the daily summary

- **WHEN** the first measurement for a date in `America/Bahia` is persisted
- **THEN** one daily parent summary and its group summaries are persisted
- **AND** measurement count is 1

#### Scenario: Day without measurement has no fabricated summary

- **WHEN** no accepted post-activation census measurement exists for a local
  date
- **THEN** the system does not create a zero or interpolated daily summary

### Requirement: Daily summary is refreshed deterministically

The system SHALL update the applicable daily summary after a new measurement is
created and SHALL derive it only from immutable measurements for that local
date.

#### Scenario: Additional same-day measurement updates summary

- **WHEN** a second distinct census measurement is persisted for the same local
  date
- **THEN** the existing daily summary is updated rather than duplicated
- **AND** its measurement count becomes 2

#### Scenario: Delayed accepted census completes its original date

- **WHEN** a measurement is first persisted after midnight but its census
  capture belongs to the previous local date
- **THEN** the previous date's summary is updated from all measurements for
  that date

#### Scenario: Idempotent measurement does not alter summary

- **WHEN** materialization returns an already existing measurement
- **THEN** the daily summary is not rewritten or counted again

#### Scenario: Future catalog does not rebuild prior summary

- **WHEN** a new catalog version becomes effective
- **THEN** summaries for earlier dates retain their stored catalog, values and
  algorithm version

### Requirement: Daily summary uses equal-weight arithmetic measurements

The system SHALL give every daily-eligible census measurement equal weight,
SHALL preserve v2/v3 historical exclusion rules, SHALL preserve v4 considered-
position semantics and SHALL treat every successfully materialized v5
identified-patient measurement as eligible while recording aggregate quality
warnings separately.

#### Scenario: V5 clean and warned measurements both contribute

- **WHEN** one v5 day contains measurements with and without identity, fallback
  or cross-group warnings
- **THEN** every successfully materialized measurement contributes one equal
  observation to hospital and official-group statistics
- **AND** no time weighting or interpolation is applied

#### Scenario: V5 statistics use persisted patient numerators

- **WHEN** a v5 daily summary is refreshed
- **THEN** mean, minimum and maximum use immutable persisted identified-patient
  numerators
- **AND** mean percentage uses exact numerator/capacity values before final
  `ROUND_HALF_UP`

#### Scenario: Historical algorithms remain unchanged

- **WHEN** v5 becomes effective
- **THEN** v1–v4 summaries retain stored algorithms, eligibility, warning counts
  and statistics
- **AND** no earlier local date is rebuilt

### Requirement: Daily group summaries preserve non-calculable states

The system SHALL persist one daily group summary for every official group or
unmapped sector represented by eligible measurements and SHALL preserve
non-calculable states without inventing percentages.

#### Scenario: Standard group has complete daily statistics

- **WHEN** a standard group is represented by eligible calculable measurements
- **THEN** its daily summary includes mean, minimum and maximum occupied and
  percentage values

#### Scenario: Age-partial measurement is omitted from all official group means

- **WHEN** a v2 measurement has an unknown occupied 3A age
- **THEN** that measurement contributes to no official daily group mean,
  minimum, maximum or exceeded-by value
- **AND** its point measurement remains stored for audit

#### Scenario: Pending or unrated group has no percentage summary

- **WHEN** a group is `linked_slots_pending`, `unrated` or `unmapped`
- **THEN** its daily summary keeps applicable aggregate evidence
- **AND** all percentage summary fields remain null

### Requirement: Daily summaries contain coverage evidence

The hospital daily summary SHALL retain source diagnostic coverage, official
sector coverage and eligibility evidence sufficient to identify partial daily
statistics.

#### Scenario: Corrected official coverage is stable throughout the day

- **WHEN** every eligible measurement uses the corrected complete catalog
- **THEN** the daily summary records 43 official sectors and 39 calculable
  official sectors
- **AND** it retains source-code coverage diagnostics separately

#### Scenario: Source coverage changes during the day

- **WHEN** same-day eligible measurements have different observed or covered
  source-code counts
- **THEN** the daily summary preserves minimum and maximum source capacity
  coverage
- **AND** it preserves minimum and maximum source calculable coverage

#### Scenario: Day contains an age-partial measurement

- **WHEN** at least one same-day v2 measurement has an unknown occupied 3A age
- **THEN** the daily summary records its age-excluded count
- **AND** official averages use only the eligible count

### Requirement: A day with no eligible measurement has no fabricated rate

The system SHALL preserve null official statistics for historical days with no
eligible measurement, while a v5 day with at least one successfully materialized
measurement SHALL have at least one eligible observation even if every
measurement has aggregate warnings.

#### Scenario: V5 all-warning day remains observable

- **WHEN** every v5 measurement in one local day has a quality warning
- **THEN** eligible count equals total measurement count
- **AND** official statistics use the persisted patient numerators
- **AND** warning count equals total measurement count

### Requirement: Legacy daily summaries remain immutable

The corrected daily eligibility rule SHALL apply only to `occupancy-v2` and
SHALL NOT rebuild or reinterpret persisted `occupancy-v1` summaries.

#### Scenario: Corrected catalog becomes effective

- **WHEN** the first corrected v2 measurement is created
- **THEN** earlier v1 daily summaries keep their stored counts and statistics
- **AND** no backfill command is invoked

### Requirement: Legacy daily summaries remain unchanged by v3 eligibility

V3 position-quality rules SHALL apply only to newly materialized v3 days and
SHALL NOT rebuild or reinterpret persisted v1/v2 summaries.

#### Scenario: V3 catalog becomes effective

- **WHEN** the first v3 point measurement is created
- **THEN** earlier daily summaries keep their stored algorithm, counts and
  statistics
- **AND** no backfill or bulk refresh is invoked

### Requirement: V4 daily quality evidence remains aggregate and private

The daily summary SHALL persist only counts needed to communicate v4 quality
and SHALL not copy conflict alternatives or row-level identity.

#### Scenario: Warned measurements update daily audit

- **WHEN** a warned v4 measurement refreshes its local-day summary
- **THEN** the summary increments one aggregate warning count
- **AND** no patient name, record number, bed or conflict signature is stored

#### Scenario: Idempotent v4 materialization does not double warning count

- **WHEN** an existing v4 measurement is returned idempotently
- **THEN** the daily warning count is not incremented again
- **AND** the summary is not rewritten

### Requirement: V4 daily policy has no backfill

V4 eligibility and warning counters SHALL apply only to days materialized under
v4 and SHALL NOT rebuild or reinterpret v1, v2 or v3 summaries.

#### Scenario: First v4 day is summarized

- **WHEN** the first v4 measurement is persisted after future activation
- **THEN** its day uses v4 eligibility and warning semantics
- **AND** all earlier summaries retain stored algorithm, counts and statistics

### Requirement: V5 daily quality remains aggregate and private

The daily summary SHALL reuse its aggregate warning-measurement count for v5 and
SHALL never copy patient, name-variant, record, bed or age detail.

#### Scenario: Warned v5 measurement refreshes summary

- **WHEN** a v5 measurement with RN fallback, incomplete identity, cross-group
  record, name variation or occupied unmapped evidence is persisted
- **THEN** the day warning count includes that measurement once
- **AND** reason detail remains only in the immutable aggregate point
  reconciliation

#### Scenario: Bed absence alone does not exclude

- **WHEN** a v5 patient is counted without a bed value
- **THEN** the measurement remains eligible
- **AND** historical age/position exclusion counters do not increment

#### Scenario: Operational states do not affect daily rate

- **WHEN** v5 censuses contain changing counts of vacant, reserved, maintenance
  or isolation rows
- **THEN** those states do not change patient numerator, capacity or rate
- **AND** daily history does not call them conflicts

#### Scenario: Idempotent v5 materialization does not double count warning

- **WHEN** an existing v5 measurement is returned
- **THEN** its daily summary and warning count are not rewritten or incremented

### Requirement: V5 daily policy has no backfill

V5 patient-counting and fallback semantics SHALL apply only to local days whose
applicable catalog declares v5.

#### Scenario: First v5 day is summarized

- **WHEN** the first v5 measurement is created after future activation
- **THEN** its day records `occupancy-v5`
- **AND** all earlier v4 and prior days remain immutable
