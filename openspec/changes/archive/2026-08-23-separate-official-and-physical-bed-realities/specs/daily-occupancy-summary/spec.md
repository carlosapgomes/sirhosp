## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Legacy daily summaries remain unchanged by v3 eligibility

V3 position-quality rules SHALL apply only to newly materialized v3 days and
SHALL NOT rebuild or reinterpret persisted v1/v2 summaries.

#### Scenario: V3 catalog becomes effective

- **WHEN** the first v3 point measurement is created
- **THEN** earlier daily summaries keep their stored algorithm, counts and
  statistics
- **AND** no backfill or bulk refresh is invoked
