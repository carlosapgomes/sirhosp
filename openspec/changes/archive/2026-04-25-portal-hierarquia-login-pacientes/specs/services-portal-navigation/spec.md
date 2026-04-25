# services-portal-navigation Specification

## ADDED Requirements

### Requirement: Public landing with explicit authentication entry

The system SHALL provide a public landing page with a clear login call-to-action for operational users.

#### Scenario: Anonymous user opens landing

- **WHEN** an anonymous user accesses `/`
- **THEN** the page is rendered without authentication
- **AND** a visible "Entrar" action points to the login route

### Requirement: Post-login default navigation to patient hub

The system SHALL redirect authenticated users to the patient list as default operational entry.

#### Scenario: Successful login

- **WHEN** user authenticates through the portal login route
- **THEN** the user is redirected to `/patients/`

### Requirement: Patient hub with search by name and registry

The system SHALL provide a patient list page with textual filtering by patient name and patient registry (`patient_source_key`).

#### Scenario: Filter by patient name

- **WHEN** the user searches with a fragment of `Patient.name`
- **THEN** matching patients are listed

#### Scenario: Filter by patient registry

- **WHEN** the user searches with a fragment of `Patient.patient_source_key`
- **THEN** matching patients are listed

### Requirement: Hierarchical navigation from patient to admissions and timeline

The system SHALL expose a simple hierarchy for navigation to extracted clinical data.

#### Scenario: Open patient admissions from list

- **WHEN** an authenticated user clicks a patient in `/patients/`
- **THEN** the system navigates to `/patients/<patient_id>/admissions/`

#### Scenario: Open admission timeline

- **WHEN** an authenticated user clicks an admission item
- **THEN** the system navigates to `/admissions/<admission_id>/timeline/`

### Requirement: Contextual operational actions in hierarchy pages

The system SHALL expose contextual actions to continue operation without returning to technical endpoints.

#### Scenario: Trigger new extraction from patient context

- **WHEN** user is on admissions or timeline pages
- **THEN** user can open `/ingestao/criar/` with patient record prefilled when available

#### Scenario: Access JSON search from patient context

- **WHEN** user is on admissions or timeline pages
- **THEN** user can open the existing JSON search endpoint (`/search/clinical-events/`) through contextual links
- **AND** no dedicated HTML search page is required in this capability

### Requirement: Authentication boundaries for operational pages

Operational portal pages MUST require authentication while health and landing remain public.

#### Scenario: Anonymous user accesses operational page

- **WHEN** an anonymous user accesses `/patients/`, admissions, timeline, ingestion pages, or `/search/clinical-events/`
- **THEN** the user is redirected to login

#### Scenario: Public health and landing remain open

- **WHEN** an anonymous user accesses `/` or `/health/`
- **THEN** the response is available without authentication
