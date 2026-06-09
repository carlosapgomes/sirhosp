# sidebar-sectors-menu Specification

## ADDED Requirements

### Requirement: Sidebar includes Setores menu

The system SHALL display a "Setores" menu item in the sidebar navigation
for authenticated users, with sub-links to Ocupação and Indicadores pages.

#### Scenario: Setores menu appears in sidebar

- **WHEN** an authenticated user views any portal page with the sidebar
- **THEN** the sidebar shows a "Setores" menu item, visually grouped
  below the "Censo" item

#### Scenario: Setores menu expands to show sub-links

- **WHEN** an authenticated user clicks or hovers the "Setores" menu item
- **THEN** two sub-links are revealed: "Ocupação" and "Indicadores"

#### Scenario: Ocupação link navigates correctly

- **WHEN** an authenticated user clicks "Ocupação" under Setores
- **THEN** the browser navigates to `/setores/ocupacao/`

#### Scenario: Indicadores link navigates correctly

- **WHEN** an authenticated user clicks "Indicadores" under Setores
- **THEN** the browser navigates to `/setores/indicadores/`

#### Scenario: Active sub-link is highlighted

- **WHEN** an authenticated user is viewing `/setores/ocupacao/`
- **THEN** the "Ocupação" sub-link is visually highlighted
- **AND** the "Setores" parent menu is expanded

### Requirement: Setores menu respects authentication

The system SHALL only display the Setores menu to authenticated users.

#### Scenario: Anonymous user does not see Setores menu

- **WHEN** an anonymous user views the login page
- **THEN** the Setores menu is not visible in the sidebar
