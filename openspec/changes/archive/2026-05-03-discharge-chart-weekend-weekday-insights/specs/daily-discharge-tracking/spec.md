# daily-discharge-tracking Specification

## MODIFIED Requirements

### Requirement: Discharge chart page shows daily bars with moving averages

The system SHALL provide a chart page at `/painel/altas/` with daily bars and
moving-average lines, and SHALL visually distinguish weekend bars in the main
series.

#### Scenario: Weekend bars are visually differentiated

- **WHEN** an authenticated user accesses `/painel/altas/`
- **AND** the displayed period includes weekdays and weekend dates
- **THEN** bars for Saturdays and Sundays use different tones from weekdays
- **AND** the legend explains the weekend visual distinction

#### Scenario: Existing moving-average overlays remain available

- **WHEN** an authenticated user accesses `/painel/altas/`
- **THEN** the bar chart still renders the existing moving-average datasets
- **AND** weekend highlighting does not remove or hide these datasets

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
