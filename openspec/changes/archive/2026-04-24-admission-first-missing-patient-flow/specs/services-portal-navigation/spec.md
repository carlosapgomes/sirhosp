# services-portal-navigation Specification

## ADDED Requirements

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
