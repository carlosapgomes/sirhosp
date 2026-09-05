# patient-admission-mirror Specification

## Purpose

Mirror source-system patients and admissions into canonical records keyed by external identity, tolerating repeated ingestion and metadata updates without duplication.

## Requirements

### Requirement: Patient mirror with external identity

The system SHALL maintain a read-only mirror of patient demographic data with an external source identifier and safe upsert behavior.

#### Scenario: Create patient from source data

- **WHEN** an ingestion run receives a patient that does not exist by `(source_system, patient_source_key)`
- **THEN** the system creates a new patient record with basic demographic fields and source identifiers

#### Scenario: Update patient from source data

- **WHEN** an ingestion run receives a patient that already exists by `(source_system, patient_source_key)`
- **THEN** the system updates mutable demographic fields without creating duplicate patient records

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

### Requirement: Empty admission snapshot does not create extraction candidates

The mirror layer MUST preserve the invariant that evolutions require at least
one known admission, MUST distinguish standalone absence from batch-bound
capture and MAY recognize an empty batch-bound `admissions_only` result only
when a valid latest-encounter fallback proves a recent unconsolidated flow.

#### Scenario: Empty standalone snapshot on admissions sync

- **WHEN** a standalone source admissions snapshot is valid and empty for the
  requested registro
- **THEN** the system records an explicit no-admissions outcome
- **AND** no admission extraction candidate is produced for follow-up actions
- **AND** no encounter fallback is required

#### Scenario: Recent encounter validates empty batch admissions

- **WHEN** a batch-bound `admissions_only` snapshot is valid and empty
- **AND** the latest structurally valid encounter date is today or yesterday in
  `America/Bahia`
- **THEN** the system records a successful operational finding with
  `admissions_seen=0`
- **AND** no Patient or Admission is persisted from the empty result
- **AND** no evolution extraction candidate is produced

#### Scenario: Unrecognized empty batch snapshot is not successful

- **WHEN** a patient admissions snapshot is captured for a run linked to a
  census/recovery batch
- **AND** the normalized snapshot is empty
- **AND** encounter evidence is boundary, stale, absent, invalid or unavailable
- **THEN** the system treats the capture as an invalid source outcome
- **AND** no Patient or Admission is persisted from that outcome
- **AND** no evolution extraction candidate is produced
- **AND** the run does not reach succeeded with an unrecognized
  `admissions_seen=0`

#### Scenario: Full-sync empty snapshot remains invalid

- **WHEN** a batch-bound full-sync intent captures an empty admissions list
- **THEN** the existing fail-closed behavior remains
- **AND** recent-encounter fallback does not authorize that target mismatch

#### Scenario: Current and persistent workers apply equivalent outcomes

- **WHEN** either ingestion worker processes equivalent synthetic empty
  batch-bound admissions and encounter evidence
- **THEN** status, attempts, stages, normalized reason or finding and absence of
  clinical/follow-up effects are observably equivalent
