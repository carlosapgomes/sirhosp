# Historical Extraction Services Specification

## ADDED Requirements

### Requirement: Historical report extractions expose structured service entry points

The system SHALL provide Python-callable service entry points for admission and
death historical report extraction without requiring callers to invoke Django
management commands.

#### Scenario: Admission extraction can be executed by service

- **WHEN** application code requests admission extraction for a valid target
  date or date range
- **THEN** the system executes the same source-system admission extraction flow
  used by the existing command
- **AND** the call returns a structured result describing success, target dates,
  metrics, and linked ingestion run information

#### Scenario: Death extraction can be executed by service

- **WHEN** application code requests death extraction for a valid target date or
  date range
- **THEN** the system executes the same source-system death extraction flow used
  by the existing command
- **AND** the call returns a structured result describing success, target dates,
  metrics, and linked ingestion run information

#### Scenario: Service failure is represented without command exit control flow

- **WHEN** an admission or death extraction fails during credential validation,
  automation execution, timeout handling, output parsing, or persistence
- **THEN** the service call returns or raises a structured failure that includes
  the extraction type, normalized failure reason, and safe error message
- **AND** the service does not require callers to parse stdout or catch
  `SystemExit` as the primary failure mechanism

### Requirement: Existing admission and death extraction commands remain compatible

The system SHALL preserve the current operator-facing CLI behavior for
`extract_admissions` and `extract_deaths` while delegating execution to the new
service entry points.

#### Scenario: Existing date argument remains supported for admissions

- **WHEN** an operator runs `python manage.py extract_admissions --date
  DD/MM/AAAA`
- **THEN** the command executes admission extraction for that date through the
  service layer
- **AND** command success and failure semantics remain compatible with the
  previous command behavior

#### Scenario: Existing date argument remains supported for deaths

- **WHEN** an operator runs `python manage.py extract_deaths --date DD/MM/AAAA`
- **THEN** the command executes death extraction for that date through the
  service layer
- **AND** command success and failure semantics remain compatible with the
  previous command behavior

#### Scenario: Existing period arguments remain supported

- **WHEN** an operator runs `extract_admissions` or `extract_deaths` with
  `--start-date DD/MM/AAAA --end-date DD/MM/AAAA`
- **THEN** the command passes the requested period to the corresponding service
- **AND** the command preserves the existing interpretation of the reference
  date for persistence

### Requirement: Admission and death persistence is safe for repeated execution

The system SHALL persist admission and death extraction output so that
re-running the same extraction target produces deterministic stored daily counts
and records.

#### Scenario: Admission extraction can be re-run for the same date

- **WHEN** admission extraction for date D succeeds more than once with the same
  extracted records
- **THEN** the stored daily admission count for D reflects the latest extracted
  record count
- **AND** individual admission records for D are not duplicated

#### Scenario: Death extraction can be re-run for the same date

- **WHEN** death extraction for date D succeeds more than once with the same
  extracted records
- **THEN** the stored daily death count for D reflects the latest extracted
  record count
- **AND** individual death records for D are not duplicated

#### Scenario: Empty output persists a successful zero-count result

- **WHEN** the source-system automation completes successfully but produces no
  admission or death records for the target date
- **THEN** the system records the corresponding daily count as zero
- **AND** the extraction result is successful
