# services-portal-navigation Specification

## MODIFIED Requirements

### Requirement: Dashboard daily event cards navigate to detailed lists

The system SHALL keep daily operational cards for altas, admissões and óbitos
navigating to list pages filtered by the displayed date.

#### Scenario: User opens admissions list from dashboard

- **WHEN** an authenticated user clicks the admissions daily card on the
  dashboard
- **THEN** the system navigates to the admissions list page
- **AND** the selected date matches the date displayed on the dashboard card

#### Scenario: User opens deaths list from dashboard

- **WHEN** an authenticated user clicks the deaths daily card on the dashboard
- **THEN** the system navigates to the deaths list page
- **AND** the selected date matches the date displayed on the dashboard card

### Requirement: Admission and death list pages expose chart navigation

The system SHALL expose a chart navigation option on admissions and deaths list
pages, matching the existing discoverability pattern from the discharge list.

#### Scenario: Admission list links to admission charts

- **WHEN** an authenticated user accesses the admissions list page
- **THEN** the page includes a link labeled `Ver gráfico de admissões`
- **AND** the link points to `/painel/admissoes/`

#### Scenario: Death list links to death charts

- **WHEN** an authenticated user accesses the deaths list page
- **THEN** the page includes a link labeled `Ver gráfico de óbitos`
- **AND** the link points to `/painel/obitos/`

#### Scenario: Existing date search remains available

- **WHEN** an authenticated user accesses admissions or deaths list pages
- **THEN** the date selector remains available
- **AND** the dashboard back link remains available
