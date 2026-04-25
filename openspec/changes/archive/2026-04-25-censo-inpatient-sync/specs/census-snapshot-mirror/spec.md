<!-- markdownlint-disable MD013 -->
# census-snapshot-mirror Specification

## Purpose

Define the extraction, storage, and processing contract for the daily inpatient census from the source system (AGHU/TASY Censo Diário).

## Requirements

### Requirement: Census extraction produces a structured snapshot

The system SHALL execute a Playwright-based scraper that logs into the source system, opens the Censo Diário, iterates all sectors, extracts patient rows with pagination, and writes CSV + JSON output files.

#### Scenario: Successful census extraction

- **WHEN** the census extraction command is invoked with valid credentials
- **THEN** the system produces a CSV file with columns `setor`, `qrt_leito`, `prontuario`, `nome`, `esp`
- **AND** the system produces a JSON file with array of `{setor, pacientes: [{prontuario, nome, qrt_leito, esp}]}`
- **AND** the extraction time is logged

#### Scenario: Empty sector

- **WHEN** a sector has no patients (all beds empty or reserved)
- **THEN** rows with empty `prontuario` and descriptive `nome` are still captured
- **AND** the sector is present in the output

#### Scenario: Login failure

- **WHEN** source system credentials are invalid or the system is unreachable
- **THEN** the command exits with a non-zero code and descriptive error message

### Requirement: Census snapshot persistence

The system SHALL store each census execution as a set of `CensusSnapshot` rows with classification of bed status.

#### Scenario: Persist census run

- **WHEN** a census CSV is parsed
- **THEN** each row is persisted as a `CensusSnapshot` with `captured_at` timestamp of the run
- **AND** an `IngestionRun` with `intent="census_extraction"` is recorded

#### Scenario: Classify occupied bed

- **WHEN** a census row has a non-empty numeric `prontuario`
- **THEN** the `bed_status` is set to `occupied`

#### Scenario: Classify empty bed

- **WHEN** a census row has empty `prontuario` and `nome` matches `DESOCUPADO` or `VAZIO`
- **THEN** the `bed_status` is set to `empty`

#### Scenario: Classify maintenance bed

- **WHEN** a census row has empty `prontuario` and `nome` matches `LIMPEZA`
- **THEN** the `bed_status` is set to `maintenance`

#### Scenario: Classify reserved bed

- **WHEN** a census row has empty `prontuario` and `nome` contains `RESERVA`
- **THEN** the `bed_status` is set to `reserved`

#### Scenario: Classify isolation bed

- **WHEN** a census row has empty `prontuario` and `nome` contains `ISOLAMENTO`
- **THEN** the `bed_status` is set to `isolation`

#### Scenario: Unknown pattern defaults to occupied if has prontuario

- **WHEN** a census row has a non-empty `prontuario` but the `nome` does not match any known special pattern
- **THEN** the `bed_status` is set to `occupied`

### Requirement: Census processing discovers new and existing patients

The system SHALL read the most recent census snapshot, identify patients not yet in the local `Patient` mirror, create them, and enqueue admission sync runs.

#### Scenario: New patient discovered

- **WHEN** a census snapshot contains a `prontuario` not present in `Patient` table
- **THEN** a `Patient` is created with `patient_source_key=prontuario` and `name=nome`
- **AND** an `IngestionRun` with `intent="admissions_only"` and `status="queued"` is created for that patient

#### Scenario: Existing patient name update

- **WHEN** a census snapshot contains a `prontuario` already in `Patient` table with a different `nome`
- **THEN** the patient's `name` is updated
- **AND** an `IngestionRun` with `intent="admissions_only"` is enqueued for re-sync

#### Scenario: Existing patient with same name

- **WHEN** a census snapshot contains a `prontuario` already in `Patient` table with the same `nome`
- **THEN** an `IngestionRun` with `intent="admissions_only"` is enqueued (re-sync admissions)

#### Scenario: Non-occupied beds are skipped

- **WHEN** a census snapshot row has `bed_status` other than `occupied`
- **THEN** no `Patient` is created and no `IngestionRun` is enqueued

#### Scenario: Deduplication within the same census run

- **WHEN** the same `prontuario` appears multiple times in the same census run (e.g., mother + RN in same bed)
- **THEN** only one `IngestionRun` is created for that prontuario
- **AND** the last occurrence (by row order) is used for name

### Requirement: Worker auto-enqueues full sync for most recent admission

The system SHALL, after completing an `admissions_only` run, automatically detect the most recent admission and enqueue a full sync for that admission.

#### Scenario: Most recent admission triggers full sync

- **WHEN** an `admissions_only` run completes successfully and the patient has at least one admission
- **THEN** a new `IngestionRun` is created with `intent="full_sync"` targeting the admission with the latest `admission_date`
- **AND** the full sync run has `patient_record`, `admission_id`, `admission_source_key`, `start_date`, and `end_date` in `parameters_json`

#### Scenario: No admissions — no full sync

- **WHEN** an `admissions_only` run completes successfully but the patient has zero admissions
- **THEN** no `full_sync` `IngestionRun` is created

#### Scenario: Multiple admissions — pick most recent

- **WHEN** a patient has admissions on `2025-01-10`, `2025-03-15`, and `2025-04-20`
- **THEN** the full sync targets the admission with `admission_date=2025-04-20`

### Requirement: Merge patients administrative action

The system SHALL provide a function to merge two `Patient` records, re-pointing all related objects and preserving audit history.

#### Scenario: Merge two patients

- **WHEN** `merge_patients(keep=A, merge=B)` is called
- **THEN** all `Admission` records from B are re-pointed to A
- **AND** all `ClinicalEvent` records from B are re-pointed to A
- **AND** `PatientIdentifierHistory` entries are created recording the merge
- **AND** patient B is deleted

#### Scenario: Merge is idempotent via admin action

- **WHEN** two patients are selected in the Django Admin and "Merge selected patients" is executed
- **THEN** the patient with the lower ID is kept and the other is merged
- **AND** a success message is displayed
