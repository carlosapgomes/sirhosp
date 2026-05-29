# sector-occupation-page Specification

## ADDED Requirements

### Requirement: Sector occupation page shows patients by sector and period

The system SHALL provide an authenticated page at `/setores/ocupacao/`
that lists patients who passed through a selected sector within a
specified period.

#### Scenario: Page renders with sector filter

- **WHEN** an authenticated user accesses `/setores/ocupacao/`
- **THEN** the page renders a sector dropdown populated from the latest
  census snapshot
- **AND** a period selector with options (7d, 30d, 90d) defaults to 7d

#### Scenario: Filter by sector

- **WHEN** an authenticated user selects a sector and clicks filter
- **THEN** the page shows only patients who have a `PatientMovement`
  with that `sector` in the selected period

#### Scenario: Summary cards show correct metrics

- **WHEN** the occupation page renders with a selected sector and period
- **THEN** summary cards display:
  - total patients who passed through the sector
  - patients still in the sector (discharge_type empty)
  - patients who left (discharge_type non-empty)
  - average length of stay in the sector

#### Scenario: Patient table is ordered by entry date

- **WHEN** the occupation page renders the patient table
- **THEN** patients are listed in chronological order by their entry date
  to the selected sector

#### Scenario: Table shows destination for departed patients

- **WHEN** a patient has left the selected sector
- **THEN** the table row shows the next sector or discharge type as
  destination

#### Scenario: Empty state when no patients match

- **WHEN** a sector has no `PatientMovement` records in the selected period
- **THEN** the page shows an informative empty-state message

### Requirement: Sector occupation page requires authentication

The system SHALL require authentication to access the sector occupation
page.

#### Scenario: Anonymous user is redirected

- **WHEN** an anonymous user accesses `/setores/ocupacao/`
- **THEN** the user is redirected to login
