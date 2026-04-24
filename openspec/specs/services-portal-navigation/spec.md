# services-portal-navigation Specification

## Purpose

Define the operational navigation flow in the portal from login to patient context pages.
## Requirements
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

#### Scenario: Display admissions coverage summary per patient

- **WHEN** authenticated user views `/patients/`
- **THEN** each listed patient includes coverage summary with:
  - known admissions count,
  - admissions with extracted events count,
  - admissions without extracted events count

### Requirement: Hierarchical navigation from patient to admissions and timeline

The system SHALL expose a simple hierarchy for navigation to extracted clinical data.

#### Scenario: Open patient admissions from list

- **WHEN** an authenticated user clicks a patient in `/patients/`
- **THEN** the system navigates to `/patients/<patient_id>/admissions/`

#### Scenario: Open admission timeline

- **WHEN** an authenticated user clicks an admission item
- **THEN** the system navigates to `/admissions/<admission_id>/timeline/`

#### Scenario: Show known admissions even without extracted events

- **WHEN** authenticated user opens `/patients/<patient_id>/admissions/`
- **THEN** all known admissions for the patient are listed
- **AND** admissions with zero extracted events are explicitly marked as `Sem eventos extraídos`

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

### Requirement: Admission-first recovery when patient search has no local match

The portal SHALL provide an immediate admission-first recovery flow when `/patients/` search returns no local patient.

#### Scenario: Show primary and secondary actions on empty search result

- **WHEN** an authenticated user searches by registro in `/patients/` and no patient is found in local mirror
- **THEN** the page shows a primary action `Buscar/sincronizar internações` for the searched registro
- **AND** the page shows a secondary action for period extraction as contextual/advanced option

#### Scenario: Primary action starts admissions synchronization workflow

- **WHEN** the user clicks `Buscar/sincronizar internações`
- **THEN** the system starts an admissions synchronization run for the searched registro
- **AND** the user can follow run status until admissions are available for selection

### Requirement: Admission selection is required before evolution synchronization

The portal MUST guide users to choose a specific admission before running evolution synchronization.

#### Scenario: Redirect to admission selection after successful admissions sync

- **WHEN** admissions synchronization succeeds and admissions exist for the registro
- **THEN** the user is redirected to patient admission listing
- **AND** each admission exposes a primary action to synchronize the full admission period

#### Scenario: No-admission case blocks extraction actions

- **WHEN** admissions synchronization succeeds with zero admissions found
- **THEN** the portal displays an explicit `Nenhuma internação encontrada` message
- **AND** the portal does not offer extraction actions for evolutions

### Requirement: `/ingestao/criar/` is a contextual secondary route

The manual period extraction page MUST behave as a contextual secondary route in the admission-first flow.

#### Scenario: Contextual access pre-fills patient and period boundaries

- **WHEN** user opens `/ingestao/criar/` from a selected admission
- **THEN** patient registro is prefilled
- **AND** start/end dates are prefilled from the selected admission boundaries

#### Scenario: Direct access without admission context is redirected

- **WHEN** user accesses `/ingestao/criar/` without valid patient/admission context
- **THEN** the system redirects to `/patients/`
- **AND** the user receives guidance to start from patient search and admission synchronization

