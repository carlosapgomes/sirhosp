## MODIFIED Requirements

### Requirement: Daily summary uses equal-weight arithmetic measurements

The system SHALL give every daily-eligible census measurement in a day equal
weight, SHALL exclude age-partial v2 measurements from official statistics and
SHALL preserve total, eligible and excluded measurement counts.

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

#### Scenario: Audit count includes excluded measurements

- **WHEN** a local day contains both eligible and age-partial measurements
- **THEN** total measurement count includes both sets
- **AND** eligible and age-excluded counts are persisted separately

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

## ADDED Requirements

### Requirement: A day with no eligible measurement has no fabricated rate

The system SHALL preserve a daily audit summary when measurements exist but
SHALL leave official statistics null if every measurement was excluded for
incomplete 3A age classification.

#### Scenario: All same-day measurements are age-partial

- **WHEN** a local day contains measurements but none is daily-eligible
- **THEN** total measurement count reflects all point measurements
- **AND** eligible measurement count is zero
- **AND** official mean, minimum, maximum and exceeded-by fields are null
- **AND** the system does not substitute zero or a prior day's values

### Requirement: Legacy daily summaries remain immutable

The corrected daily eligibility rule SHALL apply only to `occupancy-v2` and
SHALL NOT rebuild or reinterpret persisted `occupancy-v1` summaries.

#### Scenario: Corrected catalog becomes effective

- **WHEN** the first corrected v2 measurement is created
- **THEN** earlier v1 daily summaries keep their stored counts and statistics
- **AND** no backfill command is invoked
