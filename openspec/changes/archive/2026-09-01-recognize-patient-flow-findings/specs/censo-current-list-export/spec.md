## ADDED Requirements

### Requirement: Current census HTML displays patient flow findings

The authenticated `/censo/` HTML page SHALL display current patient-flow
findings from the shared bulk classifier while preserving the list and export
contracts.

#### Scenario: Desktop row displays finding badge

- **WHEN** a listed patient has a current finding
- **THEN** the desktop row displays its user-facing label
- **AND** review-required findings use a distinct accessible warning treatment

#### Scenario: Mobile card displays same finding

- **WHEN** the responsive mobile representation renders the same patient
- **THEN** it displays the same finding code/label and review semantics

#### Scenario: Patient has no finding

- **WHEN** the classifier returns no current finding for a patient
- **THEN** the existing row/card layout remains without a placeholder error

#### Scenario: Filters ordering and links are preserved

- **WHEN** findings are displayed
- **THEN** free-text, unit, specialty, ordering and patient-detail navigation
  behave as before

#### Scenario: XLSX contract remains unchanged

- **WHEN** an authenticated user exports the current census
- **THEN** the existing workbook columns and patient set remain unchanged
- **AND** this change does not add finding labels to the XLSX

#### Scenario: Classification queries are bounded

- **WHEN** `/censo/` lists different numbers of patients
- **THEN** finding classification uses bulk queries with a fixed allowance
- **AND** no query is performed from the template loop
