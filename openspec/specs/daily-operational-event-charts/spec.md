# daily-operational-event-charts Specification

## ADDED Requirements

### Requirement: Admission chart page shows daily bars

The system SHALL provide an authenticated chart page for admissions at
`/painel/admissoes/` using persisted `DailyAdmissionCount` records.

#### Scenario: Authenticated user opens admission chart page

- **WHEN** an authenticated user accesses `/painel/admissoes/`
- **THEN** the page renders successfully
- **AND** it includes a daily bar chart titled `Admissões por Dia`

#### Scenario: Admission daily chart respects selected period

- **WHEN** an authenticated user accesses `/painel/admissoes/?dias=30`
- **AND** there are admission daily counts older than 30 displayed days
- **THEN** the chart includes only the selected period up to yesterday

#### Scenario: Admission daily chart handles empty data

- **WHEN** an authenticated user accesses `/painel/admissoes/`
- **AND** there are no `DailyAdmissionCount` records in the selected period
- **THEN** the page renders without error
- **AND** it shows an empty-state message instead of a broken chart

### Requirement: Admission chart page includes weekday average bars

The system SHALL render a second bar chart on `/painel/admissoes/` with average
admissions per weekday, computed from the same selected period.

#### Scenario: Admission weekday average chart is shown

- **WHEN** an authenticated user accesses `/painel/admissoes/?dias=90`
- **AND** there are admission daily counts in the selected period
- **THEN** the page shows `Média de Admissões por Dia da Semana`
- **AND** the X axis is ordered Monday through Sunday
- **AND** each bar value corresponds to the weekday average in that period

#### Scenario: Admission weekday average handles sparse data

- **WHEN** the selected admission period does not include observations for all
  weekdays
- **THEN** missing weekday buckets are represented with average `0.0`
- **AND** the chart remains renderable

### Requirement: Death chart page shows daily bars

The system SHALL provide an authenticated chart page for deaths at
`/painel/obitos/` using persisted `DailyDeathCount` records.

#### Scenario: Authenticated user opens death chart page

- **WHEN** an authenticated user accesses `/painel/obitos/`
- **THEN** the page renders successfully
- **AND** it includes a daily bar chart titled `Óbitos por Dia`

#### Scenario: Death daily chart respects selected period

- **WHEN** an authenticated user accesses `/painel/obitos/?dias=30`
- **AND** there are death daily counts older than 30 displayed days
- **THEN** the chart includes only the selected period up to yesterday

#### Scenario: Death daily chart handles empty data

- **WHEN** an authenticated user accesses `/painel/obitos/`
- **AND** there are no `DailyDeathCount` records in the selected period
- **THEN** the page renders without error
- **AND** it shows an empty-state message instead of a broken chart

### Requirement: Death chart page includes weekday average bars

The system SHALL render a second bar chart on `/painel/obitos/` with average
deaths per weekday, computed from the same selected period.

#### Scenario: Death weekday average chart is shown

- **WHEN** an authenticated user accesses `/painel/obitos/?dias=90`
- **AND** there are death daily counts in the selected period
- **THEN** the page shows `Média de Óbitos por Dia da Semana`
- **AND** the X axis is ordered Monday through Sunday
- **AND** each bar value corresponds to the weekday average in that period

#### Scenario: Death weekday average handles sparse data

- **WHEN** the selected death period does not include observations for all
  weekdays
- **THEN** missing weekday buckets are represented with average `0.0`
- **AND** the chart remains renderable

### Requirement: Event chart period is customizable

The system SHALL allow users to customize admission and death chart periods
through a `?dias=N` querystring parameter, defaulting to 90 days.

#### Scenario: Invalid period parameter falls back to default

- **WHEN** an authenticated user accesses `/painel/admissoes/?dias=abc`
- **OR** an authenticated user accesses `/painel/obitos/?dias=abc`
- **THEN** the page uses the default 90-day period

#### Scenario: Period selector is available

- **WHEN** an authenticated user accesses either event chart page
- **THEN** the page renders period options for 30, 60, 90, 180, and 365 days

### Requirement: Event chart pages require authentication

The system SHALL require authentication to access admission and death chart
pages, consistent with other operational portal pages.

#### Scenario: Anonymous user accesses admission chart

- **WHEN** an anonymous user accesses `/painel/admissoes/`
- **THEN** the user is redirected to login

#### Scenario: Anonymous user accesses death chart

- **WHEN** an anonymous user accesses `/painel/obitos/`
- **THEN** the user is redirected to login
