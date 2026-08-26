## MODIFIED Requirements

### Requirement: Daily summary uses equal-weight arithmetic measurements

The system SHALL give every daily-eligible census measurement equal weight,
SHALL preserve v2/v3 historical exclusion rules, SHALL treat every successfully
materialized v4 measurement as eligible and SHALL record v4 quality warnings
separately from historical exclusion reasons.

#### Scenario: Clean and warned v4 measurements both contribute

- **WHEN** one local v4 day contains a clean measurement and a measurement with
  conflict or missing-position warnings
- **THEN** both measurements contribute one equal observation to hospital and
  official-group statistics
- **AND** neither receives time weighting

#### Scenario: V4 warning count is preserved

- **WHEN** a day contains v4 measurements with and without quality warnings
- **THEN** total and eligible counts include every v4 measurement
- **AND** `quality_warning_measurement_count` counts only warned v4 measurements
- **AND** warning count does not increment historical exclusion counters

#### Scenario: V3 position exclusion remains historical

- **WHEN** a day belongs to `occupancy-v3` and a measurement is physically
  partial
- **THEN** it remains excluded from hospital and official-group statistics
- **AND** `position_excluded_measurement_count` preserves its original meaning

#### Scenario: V2 and v3 age exclusions remain historical

- **WHEN** a v2 or v3 point measurement is age-partial
- **THEN** its original daily eligibility rule remains unchanged
- **AND** activation of v4 does not rebuild its summary

#### Scenario: V4 statistics use persisted considered occupations

- **WHEN** warned v4 measurements omit status-conflict, age-conflict or
  unidentified occupied evidence
- **THEN** daily statistics use each immutable persisted considered numerator
- **AND** presentation identifies the values as occupations considered with
  quality warnings

#### Scenario: Mean rounding remains deterministic

- **WHEN** a v4 arithmetic mean has more than two decimal places
- **THEN** only the final mean is rounded with `ROUND_HALF_UP`
- **AND** no interpolation or duration weighting is introduced

### Requirement: A day with no eligible measurement has no fabricated rate

The system SHALL preserve null official statistics when a historical v2/v3 day
has measurements but none eligible, while a v4 day with at least one
successfully materialized measurement SHALL have at least one eligible
observation even when every measurement has warnings.

#### Scenario: Historical all-partial day remains null

- **WHEN** a v3 day contains only physically partial measurements
- **THEN** eligible count remains zero
- **AND** mean, minimum, maximum and exceeded-by fields remain null

#### Scenario: V4 all-warning day remains observable

- **WHEN** every v4 measurement in one day has a quality warning
- **THEN** eligible count equals total measurement count
- **AND** official statistics are calculated from persisted considered values
- **AND** warning count equals total measurement count

## ADDED Requirements

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
