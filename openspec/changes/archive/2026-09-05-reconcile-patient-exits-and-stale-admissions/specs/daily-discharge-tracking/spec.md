## MODIFIED Requirements

### Requirement: Daily discharge count is stored in a dedicated tracking table

The system SHALL persist daily hospital-exit counts in `DailyDischargeCount`
using canonical `Admission.discharge_date` whose append-only reconciliation
provenance identifies `hospital_discharge` derived from `saida_em`, excluding
`death`, and SHALL make the aggregate refresh service its sole writer. Historical counts SHALL be
rebuilt in `America/Bahia` without grouping by `alta_em` or report execution
date; `raw_data` MUST contain no patient-level report rows.

#### Scenario: Management command populates counts from effective exits

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** there are 3 `hospital_discharge` admissions with canonical exit on
  date D and 2 on date E
- **AND** a death closes another admission on date D
- **THEN** `DailyDischargeCount` contains `{date: D, count: 3}` and
  `{date: E, count: 2}`

#### Scenario: Re-running the command updates existing counts

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** a `DailyDischargeCount` already exists for date D with count 3
- **AND** a newly reconciled admission exits on date D
- **THEN** the existing record for date D is updated to the canonical count

#### Scenario: Medical-summary time does not affect exit count

- **WHEN** `alta_em` belongs to date D and `saida_em` belongs to date E
- **THEN** the hospital exit is counted on E
- **AND** the medical-summary indicator is counted on D

#### Scenario: Command handles empty admission data gracefully

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** no canonical admissions have `hospital_discharge` reconciliation
  provenance and `discharge_date` set
- **THEN** the command completes without error and no exit count is fabricated

#### Scenario: Extraction cannot overwrite the operational aggregate

- **WHEN** discharge XLS evidence is persisted before or after an aggregate
  refresh
- **THEN** extraction does not create or update `DailyDischargeCount`
- **AND** the table remains derived only from canonical hospital exits

#### Scenario: Historical patient rows are removed from aggregate storage

- **WHEN** the aggregate rebuild is applied
- **THEN** patient-bearing `DailyDischargeCount.raw_data` is cleared
- **AND** the aggregate retains only date, count and non-identifying metadata

#### Scenario: Management command populates counts from admission data

- **WHEN** `refresh_daily_discharge_counts` is executed
- **AND** there are 3 admissions with `discharge_date` on date D and 2 on date E
- **THEN** `DailyDischargeCount` contains `{date: D, count: 3}` and
  `{date: E, count: 2}`

### Requirement: Discharge extraction triggers count refresh automatically

The system SHALL refresh effective hospital-exit counts after each successful,
semantically confirmed discharge extraction and reconciliation; this refresh
MUST be the only extraction-triggered writer of `DailyDischargeCount`.

#### Scenario: Successful extraction triggers count refresh

- **WHEN** `extract_discharges` completes with status `succeeded`
- **AND** zero or nonzero report output has been semantically confirmed
- **THEN** `refresh_daily_discharge_counts` is executed automatically
- **AND** `DailyDischargeCount` reflects canonical exits by `saida_em`

#### Scenario: Failed or unconfirmed extraction does not trigger count refresh

- **WHEN** discharge extraction fails or returns an unconfirmed zero
- **THEN** `refresh_daily_discharge_counts` is not executed

#### Scenario: Failed extraction does not trigger count refresh

- **WHEN** `extract_discharges` completes with status `failed`
- **THEN** `refresh_daily_discharge_counts` is NOT executed

### Requirement: Dashboard shows discharges today instead of last 24 hours

The dashboard SHALL display separate current-calendar-day values for effective
hospital exits by `saida_em` and medical discharge summaries by `alta_em`, with
hospital exits as the primary operational indicator.

#### Scenario: Dashboard displays today's hospital exits

- **WHEN** an authenticated user accesses the dashboard
- **AND** five admissions have `discharge_date` on the current local date
- **AND** three additional admissions exited yesterday within the last 24 hours
- **THEN** the primary hospital-exit card shows `5`

#### Scenario: Dashboard displays today's medical summaries

- **WHEN** four discharge records have `alta_em` on the current local date
- **THEN** the medical-summary card shows `4`
- **AND** those records do not count as hospital exits without `saida_em`

#### Scenario: Dashboard shows zero for an empty indicator

- **WHEN** the current local date has no event for one indicator
- **THEN** that indicator shows `0` without affecting the other

#### Scenario: Dashboard displays today's discharge count

- **WHEN** an authenticated user accesses the dashboard
- **AND** there are 5 admissions with `discharge_date` on today's date
- **AND** there are 3 additional admissions with `discharge_date` within the
  last 24 hours but on yesterday's date
- **THEN** the primary hospital-exit card shows "5" (only today's effective exits)

#### Scenario: Dashboard shows zero when no discharges today

- **WHEN** an authenticated user accesses the dashboard
- **AND** no admissions have `discharge_date` on today's date
- **THEN** the hospital-exit card shows "0" without affecting the
  medical-summary card

### Requirement: Discharge card navigates to the chart page

The system SHALL make both the primary `Saídas hospitalares no dia` card and the
`Sumários de alta registrados` card navigate to the discharge chart page.

#### Scenario: User clicks an exit card

- **WHEN** an authenticated user clicks either discharge-related card
- **THEN** the system navigates to `/painel/altas/`

#### Scenario: User clicks the discharge card

- **WHEN** an authenticated user clicks the hospital-exit card
  ("Saídas hospitalares no dia") on the dashboard
- **THEN** the system navigates to `/painel/altas/`

### Requirement: Discharge chart page shows daily bars with moving averages

The system SHALL provide `/painel/altas/` with separate daily series for
hospital exits by `saida_em` and medical summaries by `alta_em`, keep moving
averages on the primary hospital-exit series and visually distinguish weekends.

#### Scenario: Both event series are displayed

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the chart identifies hospital exits and medical summaries as separate
  series
- **AND** neither timestamp is relabeled as the other

#### Scenario: Weekend bars are visually differentiated

- **WHEN** the displayed period includes weekdays and weekend dates
- **THEN** primary hospital-exit bars for Saturdays and Sundays use different
  tones from weekdays
- **AND** the legend explains the weekend distinction

#### Scenario: Existing moving-average overlays remain available

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the primary exit series includes SMA-7, EMA-7 and SMA-30
- **AND** the medical-summary series does not replace those overlays

#### Scenario: Chart renders with default 90-day period

- **WHEN** the selected period is omitted
- **THEN** both series cover the default 90 days up to yesterday
- **AND** today's partial date is not included

#### Scenario: Moving averages are absent for insufficient history

- **WHEN** the chart shows fewer than 7 or 30 primary-series points
- **THEN** SMA-7 and EMA-7 start at point 7
- **AND** SMA-30 starts at point 30

#### Scenario: Chart handles empty data gracefully

- **WHEN** neither series has records in the selected period
- **THEN** the page renders without error
- **AND** displays an empty-state message

#### Scenario: Moving averages are None for insufficient history

- **WHEN** the chart shows day 2 of the primary exit series
- **THEN** SMA-7 shows no value (None/gap) for days 1-6
- **AND** SMA-7 shows a value starting from day 7
- **AND** EMA-7 shows a value starting from day 7 (seeded at index 6)
- **AND** SMA-30 shows a value starting from day 30

### Requirement: Discharge data is displayed in America/Bahia timezone

The system SHALL replace the previous configured-timezone grouping contract for
discharge events with explicit `America/Bahia` boundaries for `saida_em`,
`alta_em`, canonical `discharge_date`, dashboard cards and historical rebuilds.

#### Scenario: Exit at 23:55 remains on the local date

- **WHEN** `saida_em` is 23:55 in `America/Bahia` on date D
- **THEN** the hospital exit is counted on D

#### Scenario: Exit at 00:05 moves to the new date

- **WHEN** `saida_em` is 00:05 in `America/Bahia` on date E
- **THEN** the hospital exit is counted on E
- **AND** is not counted on D

#### Scenario: Medical summary and exit cross midnight

- **WHEN** `alta_em` is on D and `saida_em` is on E
- **THEN** the two indicators remain on their respective local dates

#### Scenario: Discharge at 23:55 is counted in the correct day

- **WHEN** an admission has `discharge_date` at 23:55 `America/Bahia` on
  date D
- **THEN** that exit is counted in `DailyDischargeCount` for date D
- **AND** the dashboard hospital-exit card includes it on date D

#### Scenario: Discharge at 00:05 is counted in the new day

- **WHEN** an admission has `discharge_date` at 00:05 `America/Bahia` on
  date E (the day after D)
- **THEN** that exit is counted in `DailyDischargeCount` for date E
- **AND** is NOT counted for date D

## ADDED Requirements

### Requirement: Historical indicator rebuild reports aggregate provenance

The system SHALL rebuild effective-exit history from canonical admissions and
medical-summary history from discharge evidence while reporting aggregate
before/after provenance in command output without requiring a new persisted
audit model.

#### Scenario: Historical rebuild runs in dry-run

- **WHEN** an operator previews the rebuild
- **THEN** aggregate before and after counts are reported without mutation

#### Scenario: Historical rebuild is applied

- **WHEN** an authorized bounded rebuild is applied
- **THEN** `DailyDischargeCount` reflects exits by `saida_em`
- **AND** the medical-summary series remains derivable from `alta_em`
- **AND** aggregate before/after counts are emitted without patient identity

## RENAMED Requirements

- FROM: `### Requirement: Discharge data is displayed in America/Sao_Paulo timezone`
- TO: `### Requirement: Discharge data is displayed in America/Bahia timezone`
