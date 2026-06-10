## ADDED Requirements

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
