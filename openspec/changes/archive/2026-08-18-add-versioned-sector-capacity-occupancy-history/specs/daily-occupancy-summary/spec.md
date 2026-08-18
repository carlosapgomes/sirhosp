# daily-occupancy-summary Specification

## ADDED Requirements

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

The system SHALL give every accepted census measurement in a day equal weight
and SHALL store first, last, mean, minimum and maximum statistics.

#### Scenario: Hospital daily metrics use all same-day measurements

- **WHEN** a local day contains multiple calculable hospital measurements
- **THEN** the summary stores their count and first and last capture timestamps
- **AND** it stores mean, minimum and maximum occupied values
- **AND** it stores mean, minimum and maximum occupancy percentages
- **AND** it stores the greatest exceeded-by value

#### Scenario: Mean rounds only the final result

- **WHEN** the arithmetic mean contains more than two decimal places
- **THEN** the system computes from exact numerators and capacities
- **AND** rounds the final stored mean to two places with `ROUND_HALF_UP`

#### Scenario: No time weighting is applied

- **WHEN** intervals between same-day census captures differ
- **THEN** each measurement still contributes one equal observation
- **AND** no interpolation or duration weighting is performed

### Requirement: Daily group summaries preserve non-calculable states

The system SHALL persist one daily group summary for every group or unmapped
sector represented in the day's measurements.

#### Scenario: Standard group has complete daily statistics

- **WHEN** a standard group is represented by calculable measurements
- **THEN** its daily summary includes mean, minimum and maximum occupied and
  percentage values

#### Scenario: Pending or unrated group has no percentage summary

- **WHEN** a group is `linked_slots_pending`, `unrated` or `unmapped`
- **THEN** its daily summary keeps measurement count and raw occupied
  statistics
- **AND** all percentage summary fields remain null

### Requirement: Daily summaries contain coverage evidence

The hospital daily summary SHALL retain enough aggregate coverage information
to show whether capacity and rate calculations were partial during the day.

#### Scenario: Coverage is stable throughout the day

- **WHEN** every measurement has the same observed and covered sector counts
- **THEN** the daily summary stores those counts and complete measurement count

#### Scenario: Coverage changes during the day

- **WHEN** same-day measurements have different observed or covered sector
  counts
- **THEN** the daily summary preserves minimum and maximum capacity coverage
- **AND** it preserves minimum and maximum calculable coverage
