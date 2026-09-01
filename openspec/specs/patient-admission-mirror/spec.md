# patient-admission-mirror Specification

## Purpose

TBD - created by archiving change fundacao-modelo-eventos-e-ingestao-evolucoes. Update Purpose after archive.

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

The system SHALL maintain admissions linked to patients using a stable external admission identifier.

#### Scenario: Create admission with external key

- **WHEN** an ingestion run receives an admission that does not exist by `(source_system, source_admission_key)`
- **THEN** the system creates a new admission linked to the resolved patient

#### Scenario: Reconcile admission for repeated ingestion

- **WHEN** an ingestion run receives an admission that already exists by `(source_system, source_admission_key)`
- **THEN** the system reuses the existing admission and updates known mutable metadata without duplication

#### Scenario: Persist known admissions independently from extracted evolutions

- **WHEN** the source connector provides the patient admissions snapshot for a run
- **THEN** the system upserts known admissions even if no evolutions were extracted in the requested window
- **AND** admissions without extracted events remain visible in patient admission listings

#### Scenario: Do not overwrite ward and bed with empty values

- **WHEN** an admission snapshot omits `ward`/`bed` for past admissions
- **THEN** existing non-empty `ward`/`bed` values are preserved
- **AND** empty snapshot values do not overwrite persisted data

### Requirement: Defensive reconciliation metadata

The system MUST persist reconciliation-support fields for admissions and patients to tolerate future source key instability.

#### Scenario: Persist reconciliation support data

- **WHEN** patient and admission data are ingested
- **THEN** the system stores additional reference metadata (such as admission period and source patient reference) required for controlled reconciliation

### Requirement: Admissions catalog sync is a first-class operation

The system SHALL support admissions catalog synchronization as a standalone operation before evolution extraction.

#### Scenario: Synchronize admissions for missing local patient

- **WHEN** admissions sync is triggered for a registro absent in local mirror
- **THEN** the system upserts all admissions returned by source snapshot
- **AND** admissions become immediately available in patient admission listing

#### Scenario: Reconcile admissions for existing local patient

- **WHEN** admissions sync is triggered for a registro already present in local mirror
- **THEN** existing admissions are reconciled by `(source_system, source_admission_key)`
- **AND** no duplicate admissions are created

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
