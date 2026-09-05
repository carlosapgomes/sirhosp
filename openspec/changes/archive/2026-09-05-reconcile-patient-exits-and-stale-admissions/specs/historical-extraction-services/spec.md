## MODIFIED Requirements

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

## ADDED Requirements

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
