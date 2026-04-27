# discharge-extraction Specification

## Purpose

Define the extraction and processing contract for daily discharge data from the
source system's "Altas do Dia" page.

## Requirements

### Requirement: Discharge extraction produces a structured patient list

The system SHALL execute a Playwright-based scraper that logs into the source
system, navigates to the "Altas do Dia" page, clicks "Visualizar Impressão",
downloads the generated PDF, and extracts the patient table via PyMuPDF.

#### Scenario: Successful discharge extraction

- **WHEN** the discharge extraction command is invoked with valid credentials
- **THEN** the system produces a JSON file with keys `data`, `total`, `pacientes`
- **AND** each patient entry contains `prontuario`, `nome`, `leito`,
  `especialidade`, `data_internacao`
- **AND** prontuario values are cleaned (digits only, no `/` separator)
- **AND** data_internacao values are normalized to DD/MM/YYYY format

#### Scenario: No patients discharged today

- **WHEN** the "Altas do Dia" page returns an empty list (zero discharges)
- **THEN** the JSON output has `total: 0` and an empty `pacientes` list
- **AND** the command exits with code 0

#### Scenario: Login failure

- **WHEN** source system credentials are invalid or the system is unreachable
- **THEN** the command exits with a non-zero code and descriptive error message

### Requirement: Discharge data is processed into existing Admission records

The system SHALL read the extracted patient list and update `discharge_date`
on the corresponding `Admission` record for each patient.

#### Scenario: Patient found and admission matched by data_internacao

- **WHEN** a patient in the discharge list has a matching `Patient` by
  `patient_source_key`
- **AND** the patient has an `Admission` with `admission_date` matching
  `data_internacao` and `discharge_date IS NULL`
- **THEN** the system sets `discharge_date = timezone.now()` on that admission

#### Scenario: Admission matched by fallback (most recent without discharge_date)

- **WHEN** no admission matches `data_internacao` exactly
- **AND** the patient has at least one admission with `discharge_date IS NULL`
- **THEN** the system sets `discharge_date = timezone.now()` on the most recent
  such admission

#### Scenario: Patient not found in local mirror

- **WHEN** a patient in the discharge list has a `prontuario` not present in
  the `Patient` table
- **THEN** the system skips that patient and records a `patient_not_found` metric
- **AND** no new `Patient` is created

#### Scenario: No matching admission found

- **WHEN** a patient exists but has no admission with `discharge_date IS NULL`
  and no admission matches `data_internacao`
- **THEN** the system skips that patient and records an `admission_not_found` metric

#### Scenario: Admission already has discharge_date

- **WHEN** the matched admission already has a non-null `discharge_date`
- **THEN** the system skips that patient and records an `already_discharged` metric
- **AND** the existing `discharge_date` is not modified

### Requirement: Discharge extraction is tracked as an IngestionRun

The system SHALL create an `IngestionRun` with `intent="discharge_extraction"`
for each execution of the discharge command, with stage metrics for extraction
and processing phases.

#### Scenario: Successful run

- **WHEN** the discharge command completes successfully
- **THEN** an `IngestionRun` with `status="succeeded"` is recorded
- **AND** `IngestionRunStageMetric` entries exist for `discharge_extraction`
  and `discharge_persistence`
- **AND** the persistence stage metric includes `total_pdf`, `discharge_set`,
  `patient_not_found`, `admission_not_found`, `already_discharged` in
  `details_json`

#### Scenario: Failed extraction

- **WHEN** the subprocess fails (non-zero exit code or timeout)
- **THEN** the `IngestionRun` is marked `status="failed"` with
  `failure_reason` set appropriately

### Requirement: Discharge processing is idempotent

The system SHALL be safe to run multiple times per day without creating
duplicate data or incorrect discharge dates.

#### Scenario: Re-running on same day

- **WHEN** the discharge command runs multiple times on the same day
- **THEN** patients whose admissions already have `discharge_date` set
  are skipped
- **AND** new discharges since the last run are processed normally
- **AND** the `altas_24h` dashboard query produces the correct count

### Requirement: Discharge extraction is scheduled 3 times per day

The system SHALL support automated execution via systemd timer at 11:00,
19:00, and 23:55 daily.

#### Scenario: Timer triggers execution

- **WHEN** the systemd timer fires at the scheduled time
- **THEN** the discharge scheduler script executes the management command
  inside the web container
- **AND** the command runs to completion or fails with logged error
