# daily-discharge-tracking Specification

## Purpose

Define rastreamento diário de contagem de altas hospitalares, com tabela
dedicada, management command de atualização e gráfico interativo no portal.

## ADDED Requirements

### Requirement: Daily discharge count is stored in a dedicated tracking table

The system SHALL persist daily discharge counts in a `DailyDischargeCount`
model with fields `date` (unique) and `count`, automatically updated by a
management command that aggregates `Admission.discharge_date` grouped by day.

#### Scenario: Management command populates counts from admission data

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** there are 3 admissions with `discharge_date` on date D and 2 on date E
- **THEN** `DailyDischargeCount` contains `{date: D, count: 3}` and
  `{date: E, count: 2}`

#### Scenario: Re-running the command updates existing counts

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** a `DailyDischargeCount` already exists for date D with count 3
- **AND** a new admission is discharged on date D (total now 4)
- **THEN** the existing record for date D is updated to count 4

#### Scenario: Command handles empty admission data gracefully

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** no admissions have `discharge_date` set
- **THEN** the command completes without error and no records are created

### Requirement: Discharge extraction triggers count refresh automatically

The system SHALL invoke `refresh_daily_discharge_counts` after each successful
execution of `extract_discharges`.

#### Scenario: Successful extraction triggers count refresh

- **WHEN** `extract_discharges` completes with status `succeeded`
- **THEN** `refresh_daily_discharge_counts` is executed automatically
- **AND** `DailyDischargeCount` reflects all admissions including the ones
  just processed

#### Scenario: Failed extraction does not trigger count refresh

- **WHEN** `extract_discharges` completes with status `failed`
- **THEN** `refresh_daily_discharge_counts` is NOT executed

### Requirement: Dashboard shows discharges today instead of last 24 hours

The system SHALL display the count of admissions discharged on the current
calendar day (server timezone) in the dashboard card, replacing the previous
24-hour sliding window metric.

#### Scenario: Dashboard displays today's discharge count

- **WHEN** an authenticated user accesses the dashboard
- **AND** there are 5 admissions with `discharge_date` on today's date
- **AND** there are 3 additional admissions with `discharge_date` within the
  last 24 hours but on yesterday's date
- **THEN** the discharge card shows "5" (only today's discharges)

#### Scenario: Dashboard shows zero when no discharges today

- **WHEN** an authenticated user accesses the dashboard
- **AND** no admissions have `discharge_date` on today's date
- **THEN** the discharge card shows "0"

### Requirement: Discharge card navigates to the chart page

The system SHALL make the "Altas no dia" card on the dashboard clickable,
navigating to the discharge chart page.

#### Scenario: User clicks the discharge card

- **WHEN** an authenticated user clicks the "Altas no dia" card on the
  dashboard
- **THEN** the system navigates to `/painel/altas/`

### Requirement: Discharge chart page shows daily bars with moving averages

The system SHALL provide a chart page at `/painel/altas/` that displays a bar
chart of daily discharge counts with three moving average lines (3-day, 10-day,
and 30-day).

#### Scenario: Chart renders with default 90-day period

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** `DailyDischargeCount` has data for the last 90 days
- **THEN** a bar chart is rendered with daily counts
- **AND** three line datasets are overlaid: MA-3, MA-10, and MA-30
- **AND** today's date is NOT included in the chart data

#### Scenario: Moving averages are None for insufficient history

- **WHEN** the chart shows day 2 of the series
- **THEN** MA-3 shows no value (None/gap) for days 1-2
- **AND** MA-3 shows a value starting from day 3
- **AND** MA-10 shows a value starting from day 10
- **AND** MA-30 shows a value starting from day 30

#### Scenario: Chart handles empty data gracefully

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** `DailyDischargeCount` has no records
- **THEN** the page renders without error
- **AND** displays a message indicating no data is available

### Requirement: Chart period is customizable via querystring

The system SHALL allow the user to customize the chart period through a
`?dias=N` querystring parameter, defaulting to 90 days.

#### Scenario: User requests a 30-day period

- **WHEN** an authenticated user accesses `/painel/altas/?dias=30`
- **AND** `DailyDischargeCount` has at least 30 days of data
- **THEN** the chart shows only the last 30 days (up to yesterday)

#### Scenario: Invalid period parameter falls back to default

- **WHEN** an authenticated user accesses `/painel/altas/?dias=abc`
- **THEN** the chart shows the default 90-day period

#### Scenario: Period selector is available on the page

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** a period selector is rendered with options for 30, 60, 90, 180,
  and 365 days

### Requirement: Chart page requires authentication

The system SHALL require authentication to access the discharge chart page,
consistent with other operational portal pages.

#### Scenario: Anonymous user accesses discharge chart

- **WHEN** an anonymous user accesses `/painel/altas/`
- **THEN** the user is redirected to login

### Requirement: Discharge data is displayed in America/Sao_Paulo timezone

The system SHALL compute daily discharge groupings and "today" boundaries using
the configured Django timezone (America/Sao_Paulo), which is the same UTC-3
offset as the source system's America/Bahia timezone.

#### Scenario: Discharge at 23:55 is counted in the correct day

- **WHEN** an admission has `discharge_date` at 23:55 America/Sao_Paulo on
  date D
- **THEN** that discharge is counted in `DailyDischargeCount` for date D
- **AND** the dashboard "Altas no dia" includes it on date D

#### Scenario: Discharge at 00:05 is counted in the new day

- **WHEN** an admission has `discharge_date` at 00:05 America/Sao_Paulo on
  date E (the day after D)
- **THEN** that discharge is counted in `DailyDischargeCount` for date E
- **AND** is NOT counted for date D
