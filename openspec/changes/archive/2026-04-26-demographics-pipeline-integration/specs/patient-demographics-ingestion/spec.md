# patient-demographics-ingestion Specification

## Purpose

Define the contract for extracting and persisting complete patient demographic
data from the source system, triggered automatically by the census pipeline.

## Requirements

### Requirement: Demographics extraction produces structured JSON

The system SHALL execute a Playwright-based scraper that logs into the source
system, opens the patient demographics page, extracts all visible demographic
fields, and writes a JSON output file.

#### Scenario: Successful demographics extraction

- **WHEN** the demographics extraction command is invoked with a valid
  `--patient-record`
- **THEN** the system produces a JSON file containing at minimum the fields:
  `prontuario`, `nome`, `nome_social`, `sexo`, `genero`, `data_nascimento`,
  `nome_mae`, `nome_pai`, `raca_cor`, `naturalidade`, `nacionalidade`,
  `estado_civil`, `profissao`, `grau_instrucao`, `cns`, `cpf`, and
  address/phone fields
- **AND** the JSON includes a `_meta` object with `patient_record` and
  `extracted_at`

#### Scenario: Demographics extraction failure

- **WHEN** the source system is unreachable or credentials are invalid
- **THEN** the subprocess exits with a non-zero code
- **AND** the worker records the failure with `failure_reason="source_unavailable"`

### Requirement: Demographics upsert creates or updates Patient

The system SHALL persist extracted demographic data to the Patient model
with safe upsert semantics.

#### Scenario: Create patient from demographics

- **WHEN** `upsert_patient_demographics` is called for a patient that does not
  exist by `(source_system, patient_source_key)`
- **THEN** the system creates a new patient record with all provided
  demographic fields

#### Scenario: Update patient from demographics

- **WHEN** `upsert_patient_demographics` is called for a patient that already
  exists
- **THEN** non-empty demographic values overwrite existing data
- **AND** empty/None values do NOT overwrite existing non-empty data

#### Scenario: Record identifier changes

- **WHEN** demographics upsert changes `cns`, `cpf`, or `patient_source_key`
- **THEN** the change is recorded in `PatientIdentifierHistory`

### Requirement: Census pipeline enqueues demographics runs

The system SHALL automatically enqueue a `demographics_only` ingestion run
for each patient processed by the census snapshot processor.

#### Scenario: New patient from census gets demographics run

- **WHEN** `process_census_snapshot()` discovers a new patient
- **THEN** an `IngestionRun` with `intent="demographics_only"` and
  `status="queued"` is created for that patient
- **AND** an `IngestionRun` with `intent="admissions_only"` is also created
  (existing behavior preserved)

#### Scenario: Existing patient from census also gets demographics run

- **WHEN** `process_census_snapshot()` encounters a patient that already
  exists in the database
- **THEN** a `demographics_only` run is still enqueued (to refresh/update
  demographic data)

#### Scenario: Demographics runs counted in metrics

- **WHEN** `process_census_snapshot()` completes
- **THEN** the returned metrics dict includes a `demographics_runs_enqueued`
  key equal to the number of unique occupied patients processed

### Requirement: Worker processes demographics_only runs

The system SHALL process `demographics_only` ingestion runs through the
existing worker infrastructure.

#### Scenario: Worker picks up demographics_only run

- **WHEN** the worker finds a queued run with `intent="demographics_only"`
- **THEN** the run is transitioned to `status="running"`
- **AND** the demographics Playwright script is executed as a subprocess

#### Scenario: Successful demographics run

- **WHEN** the demographics extraction subprocess completes successfully
- **THEN** the extracted JSON is read and passed to
  `upsert_patient_demographics()`
- **AND** the run is transitioned to `status="succeeded"` with metrics:
  `demographics_fields_extracted`, `patient_created`, `patient_updated`

#### Scenario: Failed demographics run

- **WHEN** the demographics extraction subprocess fails (timeout, exit code ≠ 0,
  or invalid JSON)
- **THEN** the run is transitioned to `status="failed"` with appropriate
  `failure_reason`
- **AND** an `IngestionRunStageMetric` records the `demographics_extraction`
  stage failure
- **AND** the patient record is NOT deleted or rolled back
