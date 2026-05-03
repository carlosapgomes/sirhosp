# daily-discharge-tracking Specification

## Purpose

Define rastreamento diário de contagem de altas hospitalares, com tabela
dedicada, management command de atualização e gráfico interativo no portal.

## Requirements

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
chart of daily discharge counts with three moving average lines (SMA-7, EMA-7,
and SMA-30), and SHALL visually distinguish weekend bars in the main series.

#### Scenario: Weekend bars are visually differentiated

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** the displayed period includes weekdays and weekend dates
- **THEN** bars for Saturdays and Sundays use different tones from weekdays
- **AND** the legend explains the weekend visual distinction

#### Scenario: Existing moving-average overlays remain available

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the bar chart still renders the existing moving-average datasets
- **AND** weekend highlighting does not remove or hide these datasets

#### Scenario: Chart renders with default 90-day period

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** `DailyDischargeCount` has data for the last 90 days
- **THEN** a bar chart is rendered with daily counts
- **AND** three line datasets are overlaid: SMA-7, EMA-7, and SMA-30
- **AND** today's date is NOT included in the chart data

#### Scenario: Moving averages are None for insufficient history

- **WHEN** the chart shows day 2 of the series
- **THEN** SMA-7 shows no value (None/gap) for days 1-6
- **AND** SMA-7 shows a value starting from day 7
- **AND** EMA-7 shows a value starting from day 7 (seeded at index 6)
- **AND** SMA-30 shows a value starting from day 30

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

### Requirement: Discharge chart page includes weekday average chart

The system SHALL render, below the main chart on `/painel/altas/`, a second
chart with average discharges per weekday (Monday through Sunday) computed from
the same selected period.

#### Scenario: Weekday average chart is shown below the main chart

- **WHEN** an authenticated user accesses `/painel/altas/?dias=90`
- **AND** there are historical daily discharge records
- **THEN** the page shows a second chart below the main chart
- **AND** the X axis is ordered Monday to Sunday
- **AND** each bar value corresponds to the weekday average in that period

#### Scenario: Weekday average respects selected period

- **WHEN** an authenticated user accesses `/painel/altas/?dias=30`
- **AND** there are daily discharge records older than 30 days
- **THEN** the weekday averages are computed only from the last 30 displayed
  days (up to yesterday)

#### Scenario: Weekday average chart handles sparse or empty data

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** the period has no daily discharge records
- **THEN** the page renders without error
- **AND** the secondary chart area degrades gracefully without broken scripts

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
