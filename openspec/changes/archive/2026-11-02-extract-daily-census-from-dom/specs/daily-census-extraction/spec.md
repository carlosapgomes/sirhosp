# daily-census-extraction Delta

## Purpose

Define direct extraction of the daily hospital census with the existing row
contract, source temporal precision and verifiable sector/page completion,
without changing downstream clinical interpretation.

## ADDED Requirements

### Requirement: Census rows are obtained without spreadsheet export

The operational census collector SHALL obtain its row data directly from the
source table and associated source tooltips. It MUST NOT depend on spreadsheet
export or silently fall back to spreadsheet data after a DOM extraction error.

#### Scenario: Normal extraction does not invoke export

- **WHEN** a complete census extraction runs
- **THEN** no spreadsheet export or spreadsheet parse is required
- **AND** the existing downstream census ingestion entry point receives rows

#### Scenario: DOM extraction fails

- **WHEN** a required source element cannot be read
- **THEN** the extraction reports failure with aggregate-safe diagnostics
- **AND** it does not replace missing DOM data with spreadsheet data

### Requirement: Extracted rows preserve the established field contract

The collector SHALL provide exactly the established eleven table fields
`qrt_leito`, `prontuario`, `nome`, `esp`, `dt_int`, `tempo`, `idade`,
`convenio`, `dt_mvt`, `alta` and `origem`, plus `setor_codigo` and
`setor`. Existing value normalization and row eligibility MUST be preserved,
except for the explicitly added temporal precision.

#### Scenario: Source contains additional clinical columns

- **WHEN** the table also contains physician, birth date or transfer columns
- **THEN** those values are not added to the extracted row contract
- **AND** the established eleven fields and sector metadata remain available

#### Scenario: A bed has no patient record

- **WHEN** a source row has empty `prontuario` and a non-empty `nome` status
  such as vacancy or reservation
- **THEN** the row and its original status label are preserved
- **AND** it is not converted into an identified patient

#### Scenario: Both record and name or status are empty

- **WHEN** both `prontuario` and `nome` are empty
- **THEN** the row is omitted under the existing spreadsheet-parser eligibility
  rule
- **AND** its omission is accounted for separately from extracted logical rows
- **AND** no identifier, name or status is invented

#### Scenario: Source contains conflicting physical-position data

- **WHEN** distinct source rows share a bed or patient identity
- **THEN** the collector does not silently deduplicate or merge those rows
- **AND** existing downstream occupancy quality rules retain responsibility for
  interpreting physical-position conflicts

### Requirement: Selected sector identity is confirmed

The collector SHALL associate rows with the sector actually selected in the
source, using its native identity and description. It MUST reject ambiguous
or mismatched selection rather than use the first unrelated suggestion.

#### Scenario: Sector names contain accents

- **WHEN** discovery returns an accented native sector label
- **THEN** selection uses that native label
- **AND** the selected identity is confirmed before accepting its rows

#### Scenario: Multiple sectors share a source code

- **WHEN** two discovered sector labels share a code
- **THEN** their distinct source descriptions are not collapsed by code alone

#### Scenario: Autocomplete selects another sector

- **WHEN** the selected source sector differs from the requested native sector
- **THEN** that sector extraction fails
- **AND** its rows are not published under the requested identity

### Requirement: Export-field variants are mapped without relying on visibility

The collector SHALL map semantic fields to the source variants that reproduce
the established export contract. Visibility alone MUST NOT choose between
repeated headers. Missing or structurally ambiguous mappings MUST fail
explicitly.

#### Scenario: Hidden and visible discharge variants differ

- **WHEN** hidden and visible `Alta` columns have different content
- **THEN** the export-contract variant supplies `alta`
- **AND** presentation text does not silently replace the existing value

#### Scenario: Header order or visibility changes

- **WHEN** unrelated columns move or an export-contract column becomes hidden
- **THEN** the same established fields and meanings are extracted

#### Scenario: Required field mapping is unavailable

- **WHEN** a required field is missing or cannot be mapped unambiguously
- **THEN** the sector fails instead of emitting a row with a guessed value

### Requirement: Source date and time precision is captured faithfully

For `Dt Int` and `Dt Mvt`, the collector SHALL capture the full
`DD/MM/AAAA HH:MM` source tooltip associated with that cell when a date is
displayed. It SHALL preserve genuinely empty dates and MUST NOT substitute
collection time, another cell's tooltip, or an invented midnight.

#### Scenario: Both dates have tooltips

- **WHEN** both date cells display a date with an associated full timestamp
- **THEN** both full timestamps are extracted for that row
- **AND** their calendar dates agree with the displayed dates

#### Scenario: An admission date is empty

- **WHEN** `Dt Int` is genuinely empty in a source row
- **THEN** its extracted value remains empty
- **AND** no admission date or hour is inferred from bed status or `Dt Mvt`

#### Scenario: Movement exists on a bed without a patient

- **WHEN** a source row has no patient record but has a movement timestamp
- **THEN** that source value remains associated with the bed snapshot row
- **AND** no patient identity is invented for it

#### Scenario: Date and tooltip are inconsistent

- **WHEN** a tooltip is invalid, ambiguous or disagrees with its displayed date
- **THEN** the sector is rejected without exposing the raw value in diagnostics

### Requirement: Tooltip readiness is verified before temporal extraction

The collector SHALL allow a bounded initialization interval for date tooltips
after each result refresh or page-size change. A displayed date whose
timestamp remains unavailable after that interval MUST cause explicit sector
failure rather than an apparently successful loss of precision.

#### Scenario: Rows arrive before tooltips

- **WHEN** rows are ready but the associated date tooltips initialize later
- **THEN** extraction waits within its bounded readiness interval
- **AND** accepts the rows only after their required timestamps are available

#### Scenario: Required tooltip never initializes

- **WHEN** the bounded interval expires with a displayed date lacking a usable
  associated timestamp
- **THEN** extraction fails for that sector
- **AND** no partial sector data is published as complete

### Requirement: Long pagination never truncates sector data

The collector SHALL select and verify a native page size of at least 100
rows, start at the first page, and traverse any remaining pages until an
explicit terminal state. The assumption of at most 100 patients per sector
MUST NOT truncate bed rows. Available source totals SHALL be checked.

#### Scenario: A sector fits in one long page

- **WHEN** a sector has 45 logical source rows and page size 100 is applied
- **AND** the next-page control is disabled
- **THEN** all 45 eligible rows are considered before completion is declared

#### Scenario: More rows exist than patients

- **WHEN** at most 100 patients plus additional bed rows require another page
- **THEN** extraction continues to that page
- **AND** every eligible row is emitted without a 100-row cutoff

#### Scenario: Pagination repeats or stops prematurely

- **WHEN** navigation repeats a page, exceeds its safety bound, has no
  identifiable terminal state or contradicts an available source total
- **THEN** the sector fails as incomplete
- **AND** repeated-page data is not appended as additional source rows

#### Scenario: Long page size cannot be applied

- **WHEN** no native page-size option of at least 100 can be confirmed
- **THEN** the sector fails with a sanitized structural reason
- **AND** it does not claim that its first small page is the complete sector

### Requirement: Operational data transport does not become development evidence

The collector SHALL pass patient-bearing rows only through the existing
controlled temporary ingestion transport. Logs, metrics and verification
evidence MUST contain no raw patient rows, identifiers, credentials or source
HTML. Normal failures MUST NOT create clinical screenshots or HTML dumps.

#### Scenario: Extraction succeeds or fails

- **WHEN** the operational collector emits diagnostic output
- **THEN** it contains only safe counters and categorized structural errors
- **AND** it contains no patient-bearing tooltip values or raw browser errors

#### Scenario: Verification evidence is produced

- **WHEN** parity or completeness evidence is recorded
- **THEN** it uses synthetic data or aggregate non-identifying results
- **AND** raw source rows are not copied into fixtures, reports or repository
  artifacts
