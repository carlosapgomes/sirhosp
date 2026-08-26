## MODIFIED Requirements

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

## ADDED Requirements

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
