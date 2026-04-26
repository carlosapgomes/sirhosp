# ingestion-run-metrics-portal Specification

## ADDED Requirements

### Requirement: Dashboard shows ingestion operational metric cards

The portal SHALL display ingestion operational metrics in dashboard cards for a configurable recent window.

#### Scenario: Show aggregated metrics on dashboard

- **WHEN** an authenticated user opens the dashboard
- **THEN** the dashboard shows cards with aggregated ingestion metrics for the default time window
- **AND** cards include at least total runs, success rate, timeout rate, and average execution time

#### Scenario: Empty window still renders cards

- **WHEN** an authenticated user opens the dashboard and no runs exist in the selected window
- **THEN** the dashboard renders the same metric cards with zero/default values
- **AND** the page shows no application error

### Requirement: Dashboard provides drill-down to ingestion metrics page

The dashboard MUST provide a direct navigation action from ingestion metric cards to a dedicated metrics page.

#### Scenario: Navigate from dashboard card to metrics page

- **WHEN** an authenticated user clicks the ingestion metrics card (or CTA) on dashboard
- **THEN** the system navigates to the ingestion metrics page
- **AND** the default filter window is pre-applied

### Requirement: Ingestion metrics page supports operational filtering

The portal SHALL provide filtering and tabular visualization of ingestion runs for operational analysis.

#### Scenario: Filter runs by status and intent

- **WHEN** user applies filters by period, status, and intent on the metrics page
- **THEN** the run list updates to include only matching runs
- **AND** aggregated summary values reflect the filtered dataset

#### Scenario: Filter runs by failure category

- **WHEN** user filters by failure category
- **THEN** only failed runs with the selected category are listed
- **AND** timeout-related metrics reflect the filtered set

### Requirement: Ingestion metrics page is authentication-protected

Operational metrics pages MUST require authenticated access.

#### Scenario: Anonymous access to metrics page

- **WHEN** an anonymous user accesses the ingestion metrics page route
- **THEN** the user is redirected to login
