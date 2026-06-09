# sector-indicators-page Specification

## ADDED Requirements

### Requirement: Sector indicators page shows aggregated analytics

The system SHALL provide an authenticated page at `/setores/indicadores/`
displaying four analytical cards based on `PatientMovement` data.

#### Scenario: Page renders with period selector

- **WHEN** an authenticated user accesses `/setores/indicadores/`
- **THEN** the page renders a period selector (7d, 30d, 90d, 180d)
  defaulting to 30d

### Requirement: Average stay by sector indicator

The system SHALL display average length of stay per sector computed from
`PatientMovement` records in the selected period.

#### Scenario: Average stay is computed correctly

- **WHEN** the indicators page renders with a 30d period
- **THEN** the "Permanência Média por Setor" card shows the average days
  patients spent in each sector
- **AND** sectors are ordered by average stay descending

#### Scenario: Sectors with single movement show N/A

- **WHEN** a sector has only one patient movement in the period
- **THEN** the average stay for that sector shows "N/A" or is omitted

### Requirement: Top destination sectors from origin indicator

The system SHALL display which sectors most frequently receive patients
from a selected origin sector.

#### Scenario: Origin sector selector filters destinations

- **WHEN** an authenticated user selects an origin sector via dropdown
- **THEN** the "Setores que mais recebem de X" card updates to show
  destination sectors ranked by count

#### Scenario: Default origin shows all flows

- **WHEN** no specific origin sector is selected
- **THEN** the card shows the most common destination sectors across
  all origin sectors

### Requirement: Long-stay patients indicator

The system SHALL identify patients who have been in the same sector for
more than 15 consecutive days.

#### Scenario: Long-stay patients are listed

- **WHEN** there are patients whose `last_seen_at - first_seen_at` exceeds
  15 days and `discharge_type` is empty
- **THEN** the "Pacientes >15 dias no mesmo setor" card lists those
  patients grouped by sector

#### Scenario: No long-stay patients shows zero state

- **WHEN** no patients meet the long-stay criteria
- **THEN** the card shows "Nenhum paciente" or equivalent

### Requirement: Sector bottleneck indicator

The system SHALL identify sectors where entries exceed departures in the
selected period, indicating potential operational bottlenecks.

#### Scenario: Bottlenecks are detected

- **WHEN** the indicators page renders
- **THEN** the "Gargalos: entradas > saídas" card shows sectors where
  the number of new `PatientMovement` entries exceeds the number of
  departures (non-empty `discharge_type` or movement to another sector)
  in the selected period

#### Scenario: No bottlenecks shows zero state

- **WHEN** all sectors have balanced or negative net flow
- **THEN** the card shows "Nenhum gargalo detectado"

### Requirement: Sector indicators page requires authentication

The system SHALL require authentication to access the sector indicators
page.

#### Scenario: Anonymous user is redirected

- **WHEN** an anonymous user accesses `/setores/indicadores/`
- **THEN** the user is redirected to login
