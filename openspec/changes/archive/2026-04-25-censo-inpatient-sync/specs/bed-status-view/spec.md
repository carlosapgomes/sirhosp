<!-- markdownlint-disable MD013 -->
# bed-status-view Specification

## Purpose

Define the web view that displays bed occupancy status derived from the most recent census snapshot, grouped by sector.

## Requirements

### Requirement: Bed status page is authenticated

The system SHALL require authentication to access the bed status view.

#### Scenario: Anonymous user redirected

- **WHEN** an unauthenticated user navigates to `/beds/`
- **THEN** the user is redirected to the login page

#### Scenario: Authenticated user can access

- **WHEN** an authenticated user navigates to `/beds/`
- **THEN** the page loads with bed status data

### Requirement: Bed status page shows occupancy by sector

The system SHALL display a table of sectors with bed counts grouped by status, using data from the most recent `CensusSnapshot`.

#### Scenario: Page renders with census data

- **WHEN** the most recent census snapshot has data for multiple sectors
- **THEN** the page displays one row per sector with columns: Setor, Ocupados, Vagas, Reservas, Manutenção, Isolamento, Total

#### Scenario: Sector row is expandable

- **WHEN** a user clicks on a sector row
- **THEN** individual beds with their status and patient name (if occupied) are displayed

#### Scenario: Empty state when no census data exists

- **WHEN** no `CensusSnapshot` rows exist in the database
- **THEN** the page displays a message "Nenhum dado de censo disponível"

### Requirement: Bed status view uses most recent snapshot only

The system SHALL aggregate from the single most recent `captured_at` timestamp in `CensusSnapshot`.

#### Scenario: Only latest census is used

- **WHEN** `CensusSnapshot` has rows from `captured_at=2025-04-25 08:00` and `captured_at=2025-04-25 16:00`
- **THEN** only rows from `captured_at=2025-04-25 16:00` are used for the aggregation
