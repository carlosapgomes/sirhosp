# services-portal-navigation Delta Specification

## ADDED Requirements

### Requirement: Navigation from dashboard discharge card to chart page

The system SHALL provide a navigation path from the dashboard discharge card
to the discharge chart page at `/painel/altas/`, requiring authentication.

#### Scenario: Authenticated user navigates to discharge chart from dashboard

- **WHEN** an authenticated user clicks the "Altas no dia" card on the
  dashboard
- **THEN** the system navigates to `/painel/altas/`

#### Scenario: Anonymous user cannot access discharge chart

- **WHEN** an anonymous user accesses `/painel/altas/`
- **THEN** the user is redirected to login
