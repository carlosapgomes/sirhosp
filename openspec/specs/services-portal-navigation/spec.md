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

### Requirement: Admission summary CTA opens a configuration step

The system SHALL route admission summary actions through a configuration page
before enqueuing processing.

#### Scenario: Open summary configuration from admission page

- **WHEN** user clicks `Gerar resumo`, `Atualizar resumo`, or `Regenerar resumo`
  on admission context
- **THEN** user is redirected to a summary configuration page for that admission

### Requirement: Configuration page supports phase-2 model and prompt mode

The configuration step SHALL expose phase-2 model choice and prompt mode
(standard/custom).

#### Scenario: Submit standard configuration

- **WHEN** user submits with standard prompt mode
- **THEN** a queued summary run is created with selected phase-2 option

#### Scenario: Submit custom prompt configuration

- **WHEN** user submits with custom prompt mode and valid text
- **THEN** a queued summary run is created with custom prompt snapshot

#### Scenario: Prompt selector includes default and custom options

- **WHEN** user opens configuration page
- **THEN** user sees prompt padrão (origem: arquivo versionado)
- **AND** sees prompts customizados disponíveis para reutilização
- **AND** can choose one custom prompt as execution input

### Requirement: Prompt library CRUD is available to authenticated users

The system SHALL provide a dedicated prompt management page with CRUD
operations and visibility rules.

#### Scenario: Owner manages own prompts

- **WHEN** authenticated user opens prompt library page
- **THEN** user can create, edit, and delete own prompts
- **AND** title is required when creating or updating prompt

#### Scenario: Non-owner cannot modify third-party prompt

- **WHEN** authenticated user tries to edit or delete prompt owned by another
  user
- **THEN** operation is denied by access control

### Requirement: Summarization logs are visible in two permission levels

The system SHALL provide public operational logs for authenticated users and a
restricted sensitive log view for administrators.

#### Scenario: Public logs list operational usage

- **WHEN** authenticated non-admin user opens summary logs page
- **THEN** user sees run-level and phase-level operational metadata
- **AND** user does not see prompt or payload/response content

#### Scenario: Admin logs include sensitive call details

- **WHEN** admin opens summary logs admin page
- **THEN** admin sees all public metadata
- **AND** sees prompt snapshot and full request/response payloads per call
