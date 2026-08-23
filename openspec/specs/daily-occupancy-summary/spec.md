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

The system SHALL give every daily-eligible census measurement in a day equal
weight, SHALL exclude age-partial v2/v3 measurements and physically partial v3
measurements from official statistics, and SHALL preserve total, eligible and
reason-specific excluded measurement counts.

#### Scenario: Hospital daily metrics use all eligible same-day measurements

- **WHEN** a local day contains multiple eligible calculable hospital
  measurements
- **THEN** the summary stores their eligible count and the day's first and last
  capture timestamps
- **AND** it stores mean, minimum and maximum occupied values
- **AND** it stores mean, minimum and maximum occupancy percentages
- **AND** it stores the greatest exceeded-by value

#### Scenario: Mean rounds only the final result

- **WHEN** an eligible arithmetic mean contains more than two decimal places
- **THEN** the system computes from exact numerators and capacities
- **AND** rounds the final stored mean to two places with `ROUND_HALF_UP`

#### Scenario: No time weighting is applied

- **WHEN** intervals between eligible same-day census captures differ
- **THEN** each eligible measurement still contributes one equal observation
- **AND** no interpolation or duration weighting is performed

#### Scenario: Audit counts preserve age and position reasons

- **WHEN** a local day contains eligible, age-partial and physically partial
  measurements
- **THEN** total measurement count includes every point measurement
- **AND** eligible, age-excluded and position-excluded counts are persisted
  separately
- **AND** reason counts may overlap when one measurement has both gaps

#### Scenario: Physical conflict excludes all official group means

- **WHEN** a v3 point measurement is physically partial
- **THEN** it contributes to no hospital or official-group daily mean, minimum,
  maximum or exceeded-by value
- **AND** the immutable point measurement remains available for audit

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

The system SHALL preserve a daily audit summary when measurements exist but
SHALL leave official statistics null if every measurement was excluded for age
or physical-position quality.

#### Scenario: All same-day measurements are partial

- **WHEN** a local day contains measurements but none is daily-eligible
- **THEN** total measurement count reflects all point measurements
- **AND** eligible measurement count is zero
- **AND** reason-specific exclusion counts are preserved
- **AND** official mean, minimum, maximum and exceeded-by fields are null
- **AND** the system does not substitute zero or a prior day's values

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
