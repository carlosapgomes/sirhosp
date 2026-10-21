## MODIFIED Requirements

### Requirement: Dashboard shows discharges today instead of last 24 hours

The dashboard SHALL display the number of source-captured effective patient
exits whose `saida_em` belongs to the current `America/Bahia` calendar date.
This management indicator MUST NOT require admission reconciliation and MUST
NOT present the medical-summary count as a competing primary card.

#### Scenario: Dashboard displays today's captured patient exits

- **WHEN** an authenticated user accesses the dashboard
- **AND** five discharge records have `saida_em` on the current local date
- **AND** three additional records have `saida_em` yesterday within the last 24
  hours
- **THEN** the patient-exit card shows `5`

#### Scenario: Pending reconciliation does not suppress an exit

- **WHEN** a discharge record has `saida_em` on the current local date
- **AND** its reconciliation status is `pending`, `ambiguous` or `conflict`
- **THEN** the dashboard patient-exit card includes it

#### Scenario: Dashboard shows zero when no exit was captured today

- **WHEN** the current local date has no discharge record with `saida_em`
- **THEN** the patient-exit card shows `0`

#### Scenario: Dashboard displays today's hospital exits

- **WHEN** five records have `saida_em` today and three exited yesterday
- **THEN** the patient-exit card shows `5`

#### Scenario: Dashboard displays today's medical summaries

- **WHEN** records have `alta_em` today
- **THEN** they do not create a competing primary discharge card
- **AND** remain available on the protected quality surface

#### Scenario: Dashboard shows zero for an empty indicator

- **WHEN** no record has `saida_em` today
- **THEN** the patient-exit card shows `0`

#### Scenario: Dashboard displays today's discharge count

- **WHEN** five records have `saida_em` on today's Bahia date
- **THEN** the primary patient-exit card shows `5`

#### Scenario: Dashboard shows zero when no discharges today

- **WHEN** no discharge evidence has `saida_em` today
- **THEN** the patient-exit card shows `0`

### Requirement: Discharge card navigates to the chart page

The system SHALL make the dashboard patient-exit card navigate to the primary
captured-exit chart and SHALL keep summary/reconciliation diagnostics outside
that main management flow.

#### Scenario: User clicks the patient-exit card

- **WHEN** an authenticated user clicks the patient-exit card
- **THEN** the system navigates to `/painel/altas/`

#### Scenario: Main dashboard does not compete with summary diagnostics

- **WHEN** an authenticated user accesses the main dashboard
- **THEN** the discharge area emphasizes captured patient exits
- **AND** medical-summary and reconciliation comparisons are not presented as a
  second primary discharge card

#### Scenario: User clicks an exit card

- **WHEN** an authenticated user clicks the patient-exit card
- **THEN** the system navigates to `/painel/altas/`

#### Scenario: User clicks the discharge card

- **WHEN** an authenticated user clicks the patient-exit card
- **THEN** the system navigates to `/painel/altas/`

### Requirement: Discharge chart page shows daily bars with moving averages

The system SHALL provide `/painel/altas/` with one daily management series:
source-captured patient exits grouped by `saida_em`. It SHALL keep moving
averages on that series, visually distinguish weekends and MUST NOT plot
medical-summary or reconciliation series on the primary chart.

#### Scenario: Only captured exits are displayed on the main chart

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the main chart identifies its bar series as patient exits captured by
  `saida_em`
- **AND** it does not include `alta_em` summaries or reconciled-exit bars

#### Scenario: Both event series are displayed

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the former summary and canonical series are replaced by the single
  captured-exit series
- **AND** their comparison remains available only on the protected quality
  surface

#### Scenario: Pending reconciliation remains visible in management totals

- **WHEN** a displayed day has 60 discharge records with `saida_em`
- **AND** only 15 have completed admission reconciliation
- **THEN** the main chart shows 60 exits for that day

#### Scenario: Weekend bars are visually differentiated

- **WHEN** the displayed period includes weekdays and weekend dates
- **THEN** Saturday and Sunday exit bars use different tones from weekdays
- **AND** the legend explains the weekend distinction

#### Scenario: Existing moving-average overlays remain available

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the captured-exit series includes SMA-7, EMA-7 and SMA-30

#### Scenario: Chart renders with default 90-day period

- **WHEN** the selected period is omitted
- **THEN** the series covers the 90 calendar days up to yesterday
- **AND** today's partial date is not included

#### Scenario: Moving averages are absent for insufficient history

- **WHEN** the chart shows fewer than 7 or 30 calendar points
- **THEN** SMA-7 and EMA-7 start at point 7
- **AND** SMA-30 starts at point 30

#### Scenario: Moving averages are None for insufficient history

- **WHEN** fewer than seven or thirty calendar points are available
- **THEN** the corresponding leading moving-average values are null

#### Scenario: Chart handles empty data gracefully

- **WHEN** the selected period has no captured patient exits
- **THEN** the page renders without error
- **AND** displays an empty-state message

### Requirement: Chart period is customizable via querystring

The system SHALL allow the user to customize the primary exit-chart period
through `?dias=N`, defaulting to 90 consecutive calendar days and filling days
without captured exits with zero.

#### Scenario: User requests a 30-day period

- **WHEN** an authenticated user accesses `/painel/altas/?dias=30`
- **THEN** the chart contains exactly the 30 calendar dates ending yesterday

#### Scenario: Day without a captured exit remains on the axis

- **WHEN** no discharge record has `saida_em` on one date inside the selected
  period
- **THEN** that date remains on the chart axis with value zero
- **AND** moving averages preserve calendar continuity

#### Scenario: Invalid period parameter falls back to default

- **WHEN** an authenticated user accesses `/painel/altas/?dias=abc`
- **THEN** the chart shows the default 90-day period

#### Scenario: Period selector is available on the page

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** a period selector is rendered with options for 30, 60, 90, 180 and
  365 days

### Requirement: Discharge chart page includes weekday average chart

The system SHALL render a second chart with average captured patient exits per
weekday, computed from every calendar day in the same selected period,
including zero-exit days.

#### Scenario: Weekday average chart is shown below the main chart

- **WHEN** an authenticated user accesses `/painel/altas/?dias=90`
- **THEN** the page shows a chart ordered Monday through Sunday
- **AND** each value is based on `saida_em` counts from the selected period

#### Scenario: Weekday average includes zero-exit dates

- **WHEN** one weekday occurrence inside the selected period has no captured
  exits
- **THEN** that occurrence contributes zero to the weekday average

#### Scenario: Weekday average respects selected period

- **WHEN** the user selects a 30-day period
- **THEN** only those 30 consecutive calendar days contribute to weekday
  averages

#### Scenario: Weekday average chart handles sparse or empty data

- **WHEN** the selected period is sparse or empty
- **THEN** zero dates remain part of the calculation and scripts remain valid

#### Scenario: Weekday average handles an empty period

- **WHEN** the period has no captured exits
- **THEN** the page renders without broken scripts
- **AND** the secondary chart degrades gracefully

### Requirement: Discharge data is displayed in America/Bahia timezone

The system SHALL group management exits by the explicit `America/Bahia` local
boundary of `saida_em`. Medical-summary and reconciliation diagnostics SHALL
use the same local-day convention on their secondary protected surface.

#### Scenario: Exit at 23:55 remains on the local date

- **WHEN** `saida_em` is 23:55 in `America/Bahia` on date D
- **THEN** the management indicator counts the exit on D

#### Scenario: Exit at 00:05 moves to the new date

- **WHEN** `saida_em` is 00:05 in `America/Bahia` on date E
- **THEN** the management indicator counts the exit on E
- **AND** does not count it on D

#### Scenario: Medical summary does not move the management exit

- **WHEN** `alta_em` is on D and `saida_em` is on E
- **THEN** the primary chart counts the patient exit only on E

#### Scenario: Medical summary and exit cross midnight

- **WHEN** `alta_em` is on D and `saida_em` is on E
- **THEN** the main management indicator counts only the exit on E
- **AND** the protected quality surface preserves both event dates

#### Scenario: Discharge at 23:55 is counted in the correct day

- **WHEN** `saida_em` is 23:55 in `America/Bahia` on D
- **THEN** the management indicator counts it on D

#### Scenario: Discharge at 00:05 is counted in the new day

- **WHEN** `saida_em` is 00:05 in `America/Bahia` on E
- **THEN** the management indicator counts it on E
- **AND** does not count it on D

## ADDED Requirements

### Requirement: Hourly discharge analytics use effective patient exit time

The hourly distribution and specialty summary on the discharge management page
SHALL use the hour of `saida_em`, never `alta_em`, so late-exit analysis reflects
bed release rather than medical-summary registration.

#### Scenario: Summary signed before physical exit

- **WHEN** a discharge record has `alta_em` at 14:00 and `saida_em` at 18:00
- **THEN** the hourly management chart counts the exit at 18:00

#### Scenario: Specialty aggregation remains available

- **WHEN** captured exits in the selected hourly interval carry specialty values
- **THEN** the page groups their `saida_em` counts by hour and specialty

### Requirement: Discharge list follows the captured-exit management metric

The discharge list reached from the management chart SHALL query discharge
evidence by `saida_em` for the selected local date and SHALL not depend on the
legacy aggregate-record relationship.

#### Scenario: User opens a date with pending exits

- **WHEN** an authenticated user opens the discharge list for date D
- **AND** records with `saida_em` on D are still pending reconciliation
- **THEN** the list includes those records
- **AND** its total equals the captured-exit management count for D

### Requirement: Reconciliation details remain available outside the main chart

The protected reconciliation surface SHALL provide an aggregate comparison of
captured exits, reconciled hospital exits and medical summaries without adding
those competing series back to the primary management chart.

#### Scenario: Authorized reviewer accesses quality comparison

- **WHEN** a user with the reconciliation-review permission accesses the
  reconciliation surface
- **THEN** the user can compare captured exits, reconciled exits and medical
  summaries over an explicit period
- **AND** no patient identity is embedded in the aggregate chart payload

#### Scenario: Ordinary user cannot access quality comparison

- **WHEN** an authenticated user without reconciliation-review permission tries
  to access the protected comparison
- **THEN** access is denied consistently with the existing reconciliation queue
