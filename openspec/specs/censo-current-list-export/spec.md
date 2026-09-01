# censo-current-list-export Specification

## Purpose

Defines the authenticated `/censo/` current-census HTML list — filters, ordering and specialty labels — and the equivalent XLSX export contract.

## Requirements

### Requirement: Censo specialty labels

The system SHALL display full specialty names in the `/censo/` specialty filter
and patient list when a matching `Specialty` catalog entry exists.

#### Scenario: Specialty dropdown displays full names

- **WHEN** an authenticated user opens `/censo/` and the latest occupied census
  snapshot contains specialty code `NEF` with a matching `Specialty` named
  `NEFROLOGIA`
- **THEN** the specialty dropdown displays `NEFROLOGIA` as the user-visible
  label
- **AND** the option value remains compatible with filtering the current census
  rows by the stored specialty value

#### Scenario: Specialty table column displays full names

- **WHEN** an authenticated user opens `/censo/` and a listed patient has
  specialty code `CIV` with a matching `Specialty` named `CIRURGIA VASCULAR`
- **THEN** the `Especialidade` column displays `CIRURGIA VASCULAR` as the main
  user-visible text

#### Scenario: Specialty mobile card displays full names

- **WHEN** an authenticated user views `/censo/` on the mobile card layout and a
  listed patient has a specialty with a matching catalog entry
- **THEN** the specialty badge or text in the mobile card displays the full
  specialty name

#### Scenario: Unknown specialty falls back safely

- **WHEN** a census row has a specialty value without a matching `Specialty`
  catalog entry
- **THEN** the page displays the original specialty value instead of failing or
  hiding the row

### Requirement: Censo filters remain stable

The system SHALL preserve existing `/censo/` filtering and ordering semantics
while improving specialty display labels.

#### Scenario: Filtering by specialty still works

- **WHEN** an authenticated user filters `/censo/` by a specialty option whose
  label is a full name and whose value is the stored census specialty code
- **THEN** only patients from the selected specialty appear in the result

#### Scenario: Existing filters continue to combine

- **WHEN** an authenticated user combines free-text search, sector filter,
  specialty filter and ordering on `/censo/`
- **THEN** the result applies all selected criteria consistently

### Requirement: Censo XLSX export

The system SHALL allow authenticated users to download an XLSX file containing
the current `/censo/` result set.

#### Scenario: Export downloads XLSX file

- **WHEN** an authenticated user requests the censo export endpoint
- **THEN** the response downloads an `.xlsx` file with the official XLSX content
  type
- **AND** the workbook can be opened by standard Excel-compatible readers

#### Scenario: Export respects current filters

- **WHEN** an authenticated user exports the censo with query parameters for
  search, sector, specialty or ordering
- **THEN** the workbook contains the same patients that the filtered `/censo/`
  page would show for those query parameters

#### Scenario: Export includes expected columns

- **WHEN** an authenticated user downloads the XLSX export
- **THEN** the workbook includes at least `Registro`, `Nome`, `Setor / Unidade`,
  `Leito`, `Especialidade`, `Data Internação`, `Tempo Internação` and
  `Capturado em` columns

#### Scenario: Export uses full specialty names

- **WHEN** an exported patient row has a specialty with a matching `Specialty`
  catalog entry
- **THEN** the `Especialidade` cell contains the full specialty name

#### Scenario: Anonymous export request is rejected

- **WHEN** an anonymous user requests the censo export endpoint
- **THEN** the system redirects the user to login instead of returning patient
  data

#### Scenario: Empty census export remains valid

- **WHEN** an authenticated user exports the censo and there is no latest census
  snapshot or no matching patient after filters
- **THEN** the system returns a valid XLSX workbook with headers and no patient
  rows

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
