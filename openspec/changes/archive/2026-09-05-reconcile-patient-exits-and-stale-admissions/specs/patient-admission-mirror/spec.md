## MODIFIED Requirements

### Requirement: Admission mirror linked to patient

The system SHALL maintain canonical admissions linked to patients using layered
identity composed of source key, historical key aliases, patient identity and
admission period; a source admission key alone MUST NOT create a duplicate of a
uniquely matched episode.

#### Scenario: Create admission with previously unseen episode

- **WHEN** an ingestion run receives an admission that matches no current key,
  alias, exact patient/start or unique patient/local-date episode
- **THEN** the system creates a new canonical admission linked to the resolved
  patient
- **AND** stores the supplied source key as an alias

#### Scenario: Reconcile admission by current external key

- **WHEN** an ingestion run receives an admission that already exists by
  `(source_system, source_admission_key)`
- **THEN** the system reuses the existing canonical admission and updates known
  mutable metadata without duplication

#### Scenario: Reconcile admission by historical alias

- **WHEN** an ingestion run receives a source key previously observed for one
  canonical admission
- **THEN** the system reuses that admission without creating a duplicate

#### Scenario: Reconcile changed key by unique period

- **WHEN** the source key is new but patient and admission start resolve exactly
  one canonical episode
- **THEN** the system reuses that admission
- **AND** persists the new source key as an alias

#### Scenario: Ambiguous period fails closed

- **WHEN** a new source key could match multiple same-day admissions
- **THEN** the system changes none of them
- **AND** records an ambiguity for authorized review

#### Scenario: Persist known admissions independently from extracted evolutions

- **WHEN** the source connector provides the patient admissions snapshot for a
  run
- **THEN** the system upserts known admissions even if no evolutions were
  extracted in the requested window
- **AND** canonical admissions without extracted events remain visible in
  patient admission listings

#### Scenario: Do not overwrite ward and bed with empty values

- **WHEN** an admission snapshot omits `ward` or `bed` for past admissions
- **THEN** existing non-empty `ward` and `bed` values are preserved
- **AND** empty snapshot values do not overwrite persisted data

#### Scenario: Create admission with external key

- **WHEN** an ingestion run receives an admission that does not exist by `(source_system, source_admission_key)`
- **THEN** the system creates a new admission linked to the resolved patient

#### Scenario: Reconcile admission for repeated ingestion

- **WHEN** an ingestion run receives an admission that already exists by `(source_system, source_admission_key)`
- **THEN** the system reuses the existing admission and updates known mutable metadata without duplication

### Requirement: Defensive reconciliation metadata

The system MUST persist current and historical source keys, admission period,
source patient reference, canonical/merged state and append-only reconciliation
metadata required for controlled identity resolution.

#### Scenario: Persist reconciliation support data

- **WHEN** patient and admission data are ingested
- **THEN** the system stores the source aliases and period metadata required for
  layered reconciliation

#### Scenario: Merged admission is preserved but not clinically listed

- **WHEN** an admission has been merged into an older canonical row
- **THEN** it retains its identity and `merged_into` reference for audit
- **AND** normal clinical listings exclude it

### Requirement: Admissions catalog sync is a first-class operation

The system SHALL support admissions catalog synchronization as a standalone
operation before evolution extraction and SHALL apply the same layered identity
and ambiguity rules used by all admission writers.

#### Scenario: Synchronize admissions for missing local patient

- **WHEN** admissions sync is triggered for a record absent in the local mirror
- **THEN** the system upserts the patient through the canonical patient flow
- **AND** upserts all source admissions without inventing an admission from an
  exit report
- **AND** canonical admissions become immediately available in patient listings

#### Scenario: Reconcile admissions for existing local patient

- **WHEN** admissions sync is triggered for a record already present locally
- **THEN** existing admissions are reconciled by current key, alias and unique
  period in that order
- **AND** no duplicate admission is created for a uniquely matched episode

#### Scenario: Closed snapshot updates compatible open episode

- **WHEN** a changed source key returns a uniquely matched open episode with an
  end datetime
- **THEN** the existing admission is closed
- **AND** the changed key is retained as an alias
