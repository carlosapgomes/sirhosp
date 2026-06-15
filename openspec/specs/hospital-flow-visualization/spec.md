# hospital-flow-visualization Specification

## Purpose

Define a visualização temporal de "Fluxo Hospitalar" no portal, que
confronta o estoque diário de pacientes internados (ADC do census
snapshot, abrangendo todos os setores, incluindo observação de
emergência) com o fluxo diário (admissões como entrada; altas mais
óbitos como saída). Permite ao gestor local distinguir pressão da rede
(inflow alto) de gargalo de alta (outflow baixo), e oferece drill-down
por setor e um painel de resíduo (indicador de qualidade dos dados)
visível apenas a administradores.

## Requirements

### Requirement: Fluxo Hospitalar page shows stock vs. flow over time

The portal SHALL display a temporal visualization that confronts the
daily inpatient stock (ADC from census snapshots) with the daily flow
(admissions in, discharges plus deaths out).

#### Scenario: Show flow pressure chart for default window

- **WHEN** an authenticated user opens the Fluxo Hospitalar page
- **THEN** the page shows a chart covering the last 90 days by default
- **AND** the chart displays divergent bars (admissions up, discharges
  plus deaths down) per day
- **AND** the chart overlays an ADC line on a secondary axis

#### Scenario: User changes time window

- **WHEN** the user selects 30 or 180 days
- **THEN** the chart updates to cover the selected window
- **AND** all series (bars and ADC line) reflect the new window

#### Scenario: Day without census snapshot

- **WHEN** a day in the window has flow data but no census snapshot
- **THEN** the ADC line shows a gap (null point) for that day
- **AND** flow bars are still rendered for that day
- **AND** the ADC value is not projected or interpolated

### Requirement: Stock is computed from census snapshots of all sectors

The ADC SHALL be computed as the daily average of occupied beds across
all census snapshots, including emergency observation sectors.

#### Scenario: Stock includes emergency observation sectors

- **WHEN** the ADC is computed for a day
- **THEN** it counts occupied beds from all sectors captured in the
  snapshot
- **AND** it does not exclude sectors omitted by the official census

### Requirement: Flow uses dedicated extraction sources

Inflow and outflow SHALL come from dedicated extraction tables, not from
the admission mirror model.

#### Scenario: Daily inflow and outflow per day

- **WHEN** the flow series is computed for a day
- **THEN** inflow equals the admission count for that date
- **AND** outflow equals the discharge count plus the death count for
  that date

### Requirement: Fluxo Hospitalar page is authentication-protected

The Fluxo Hospitalar page MUST require authenticated access.

#### Scenario: Anonymous access

- **WHEN** an anonymous user accesses the Fluxo Hospitalar route
- **THEN** the user is redirected to login

### Requirement: Sidebar exposes Fluxo Hospitalar entry

The sidebar navigation SHALL include a Fluxo Hospitalar entry positioned
after the Leitos entry.

#### Scenario: Navigate from sidebar

- **WHEN** an authenticated user clicks the Fluxo Hospitalar entry in the
  sidebar
- **THEN** the system navigates to the Fluxo Hospitalar page
- **AND** the entry is visually marked as active

### Requirement: Sector drill-down filters the visualization

The Fluxo Hospitalar page SHALL provide a sector selector that filters
both the stock and flow series to the selected sector.

#### Scenario: Filter by sector

- **WHEN** the user selects a sector from the selector
- **THEN** the chart recomputes to show only that sector
- **AND** the ADC reflects occupied beds in that sector only
- **AND** a control returns to the hospital-total view

### Requirement: Admin sees a residual quality-control panel

The Fluxo Hospitalar page SHALL display a residual quality-control panel
visible only to admin users.

#### Scenario: Admin user sees residual panel

- **WHEN** an admin user opens the Fluxo Hospitalar page
- **THEN** the page shows a panel with the daily residual of the
  conservative identity
- **AND** the panel includes a short legend explaining the residual as a
  data-quality indicator

#### Scenario: Non-admin user does not see residual panel

- **WHEN** a non-admin user opens the Fluxo Hospitalar page
- **THEN** the residual quality-control panel is not rendered
