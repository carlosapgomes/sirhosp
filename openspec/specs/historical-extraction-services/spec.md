# historical-extraction-services Specification

## Purpose

Define service-oriented extraction requirements for historical admission, death,
official census, and discharge reports while preserving existing CLI wrappers.

## Requirements

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

### Requirement: Official census extraction exposes a service entry point

The system SHALL provide a Python-callable service entry point for official daily
census extraction without requiring callers to invoke Django management
commands.

#### Scenario: Official census extraction can be executed by service

- **WHEN** application code requests official census extraction for a valid
  target date
- **THEN** the system executes the same source-system official census extraction
  flow used by the existing command
- **AND** the call returns a structured result describing success, target date,
  metrics, and linked ingestion run information

#### Scenario: Official census command delegates to service

- **WHEN** an operator runs `python manage.py extract_official_census --date
  DD/MM/AAAA`
- **THEN** the command executes official census extraction for that date through
  the service layer
- **AND** command success and failure semantics remain compatible with the
  previous command behavior

#### Scenario: Official census re-run is deterministic

- **WHEN** official census extraction for date D succeeds more than once with the
  same extracted records
- **THEN** the stored official census records for D reflect the latest extracted
  output
- **AND** individual official census records for D are not duplicated

#### Scenario: Empty official census output succeeds as zero records

- **WHEN** the source-system automation completes successfully but produces no
  official census output or no records for the target date
- **THEN** the service records a successful zero-count result
- **AND** no stale official census records remain for the target date

### Requirement: Discharge extraction exposes a service entry point

The system SHALL provide a Python-callable service entry point for discharge
report extraction that persists report evidence and invokes canonical exit
reconciliation without requiring callers to invoke Django management commands.

#### Scenario: Discharge extraction can be executed by service

- **WHEN** application code requests discharge extraction for a valid target
  date
- **THEN** the system executes the same source-system discharge extraction flow
  used by the existing command
- **AND** the call returns a structured result describing extraction,
  persistence, reconciliation, target date and linked ingestion run information

#### Scenario: Discharge command delegates to service

- **WHEN** an operator runs `python manage.py extract_discharges --date
  DD/MM/AAAA`
- **THEN** the command executes discharge extraction for that date through the
  service layer
- **AND** command success and failure semantics remain compatible except for the
  new confirmed-zero requirement

#### Scenario: Discharge orchestration remains modular

- **WHEN** discharge extraction succeeds
- **THEN** extraction and report persistence remain outside the canonical domain
  reconciliation module
- **AND** the extraction service calls that shared reconciliation boundary
  instead of duplicating matching rules

#### Scenario: Discharge re-run is deterministic

- **WHEN** discharge extraction for date D succeeds more than once with the same
  extracted records
- **THEN** the stored daily discharge evidence reflects the latest report
- **AND** individual discharge records are not duplicated
- **AND** repeated reconciliation does not change an already equal admission

#### Scenario: Evidence persistence does not write operational counts

- **WHEN** discharge report rows are persisted
- **THEN** the persistence path does not create or update
  `DailyDischargeCount.count` or patient-bearing `raw_data`
- **AND** `DischargeRecord` remains persistable without using the aggregate as
  report-batch storage

#### Scenario: First empty discharge output is retried

- **WHEN** source automation completes but produces no XLS or no parseable rows
- **THEN** the service performs exactly one independent confirmation attempt
- **AND** does not overwrite prior evidence with zero before confirmation

#### Scenario: Two empty discharge outputs confirm zero

- **WHEN** both independent attempts complete successfully with zero rows
- **THEN** the service stores a semantically confirmed zero result and attempt
  count in durable ingestion-stage metadata
- **AND** the extraction result is successful
- **AND** later health and catch-up processes can distinguish that result from
  missing or unconfirmed coverage

#### Scenario: Empty confirmation fails or disagrees

- **WHEN** the confirmation attempt fails or returns a non-empty report
- **THEN** an unconfirmed zero is not persisted as success
- **AND** a non-empty confirmation is processed normally
- **AND** failure metadata remains structured and credential-safe

#### Scenario: Discharge extraction service remains separate from reconciliation

- **WHEN** discharge report extraction orchestration is refactored into a
  service
- **THEN** the extraction service is implemented outside
  `apps/discharges/services.py`
- **AND** the existing discharge reconciliation service behavior is not modified
  by this change

#### Scenario: Empty discharge output succeeds as zero records

- **WHEN** the source-system automation completes successfully but produces no
  XLS output or no parseable discharge rows for the target date
- **AND** the empty result is confirmed by a second successful empty attempt
  (`zero_confirmed=true` with `attempt_count >= 2`)
- **THEN** the service records the corresponding daily discharge count as zero
- **AND** the extraction result is successful

### Requirement: Census and discharge service failures are structured and safe

Official census and discharge service failures SHALL be represented as
structured service results without requiring callers to parse stdout or catch
`SystemExit` as the primary failure mechanism.

#### Scenario: Service failure returns normalized metadata

- **WHEN** official census or discharge extraction fails during credential
  validation, automation execution, timeout handling, output parsing, or
  persistence
- **THEN** the service call returns a structured failure with extraction type,
  normalized failure reason, and safe error message
- **AND** the service does not require callers to parse stdout or catch
  `SystemExit` as the primary failure mechanism

#### Scenario: Timeout failure does not expose credentials

- **WHEN** official census or discharge automation times out after a command has
  been built with source-system credentials
- **THEN** the structured failure message does not include source URL, username,
  password, or command-line credential flags
- **AND** persisted failure metadata does not include source URL, username,
  password, or command-line credential flags

### Requirement: Persisted discharge evidence reconciles by effective exit

Every persisted `DischargeRecord` SHALL be offered to canonical reconciliation
using `saida_em`; report extraction MUST NOT close an admission from `alta_em`
or the report reference date.

#### Scenario: Row has effective exit

- **WHEN** a persisted discharge row contains valid `saida_em`
- **THEN** the row is reconciled through the canonical service
- **AND** result metrics distinguish each closed reconciliation status

#### Scenario: Row lacks effective exit

- **WHEN** a persisted discharge row has no `saida_em`
- **THEN** it remains pending evidence
- **AND** `alta_em` does not set `Admission.discharge_date`

### Requirement: Persisted death evidence uses canonical reconciliation

Death extraction SHALL offer complete datetime evidence to canonical death
reconciliation and SHALL enqueue admissions synchronization for date-only or
unresolved evidence.

#### Scenario: Death has complete datetime and unique admission

- **WHEN** one persisted death row provides a complete datetime and unique
  episode match
- **THEN** canonical reconciliation closes it as `death`

#### Scenario: Death has date only

- **WHEN** a persisted death row lacks source time
- **THEN** no synthetic datetime is stored
- **AND** bounded `admissions_only` confirmation is enqueued

#### Scenario: Death report is extracted again

- **WHEN** the same death evidence is present in a repeated extraction
- **THEN** the existing `DeathRecord` primary key, Admission link and
  reconciliation status are preserved
- **AND** the persistence path does not delete and recreate report rows
- **AND** no duplicate confirmation run is enqueued

### Requirement: Historical extractor subprocess credentials are not argv values

Admission, discharge, death and official-census services MUST pass source
username and password to their automation subprocesses through a non-argv
channel such as a scoped child environment, and automation entry points SHALL
reject missing credentials without echoing them.

#### Scenario: Historical extractor starts automation

- **WHEN** any of the four historical services builds a subprocess invocation
- **THEN** username and password values are absent from the command argument list
- **AND** only the child process receives the scoped credential environment

#### Scenario: Credential is missing

- **WHEN** the automation entry point cannot resolve username or password
- **THEN** it exits with a fixed validation message
- **AND** neither the missing name nor any available credential value is printed

#### Scenario: Process inspection occurs

- **WHEN** an operator inspects process command lines during extraction
- **THEN** source username and password are not visible in argv
