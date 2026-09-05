## ADDED Requirements

### Requirement: Hospital exit time has one authoritative meaning

The system SHALL use `saida_em` in `America/Bahia` as the effective end of a
hospital admission and MUST preserve `alta_em` only as the time when the medical
discharge summary was registered.

#### Scenario: Exit time closes an admission

- **WHEN** a discharge report contains a valid `saida_em` for one uniquely
  matched admission
- **THEN** the system sets `Admission.discharge_date` to that `saida_em`
- **AND** records exit type `hospital_discharge`

#### Scenario: Medical discharge alone does not close an admission

- **WHEN** a discharge report contains `alta_em` but no `saida_em`
- **THEN** the system preserves the medical-summary timestamp as evidence
- **AND** leaves `Admission.discharge_date` unchanged

#### Scenario: Naive exit time uses institutional timezone

- **WHEN** the source provides `saida_em` without an offset
- **THEN** the system interprets it in `America/Bahia`
- **AND** persists a timezone-aware value

#### Scenario: Exit before admission fails closed

- **WHEN** `saida_em` is earlier than the matched admission start
- **THEN** the system does not change the admission
- **AND** records `invalid_exit_datetime`

### Requirement: Exit reconciliation is evidence-linked and auditable

The system MUST retain an indefinite append-only audit of every attempted
reconciliation and SHALL expose the closed statuses `pending`, `reconciled`,
`already_reconciled`, `patient_not_found`, `admission_not_found`, `ambiguous`,
`conflict`, and `invalid_exit_datetime`.

#### Scenario: Discharge evidence is reconciled

- **WHEN** a `DischargeRecord` uniquely closes an admission
- **THEN** the reconciliation links that evidence to the admission
- **AND** records previous and new discharge values, exit type, source and time
  of reconciliation

#### Scenario: Repeated evidence is idempotent

- **WHEN** the same evidence is reconciled again against the same discharge time
- **THEN** no clinical field is changed
- **AND** the observable result is `already_reconciled`

#### Scenario: Logs remain free of patient identity

- **WHEN** reconciliation succeeds or fails
- **THEN** application and systemd logs contain no patient name or record number
- **AND** authorized database audit remains available indefinitely

### Requirement: Admission matching is deterministic and fail-closed

The system SHALL match exit evidence in this order: current external admission
key, known key alias, patient plus exact admission start, then patient plus a
unique admission on the same local date. It MUST NOT select an arbitrary
candidate.

#### Scenario: Current external key matches

- **WHEN** exactly one canonical admission has the supplied source key
- **THEN** the system selects that admission without evaluating weaker matches

#### Scenario: Historical alias matches

- **WHEN** the current key does not match and exactly one alias does
- **THEN** the system selects the aliased canonical admission

#### Scenario: Unique local date fallback matches

- **WHEN** no key or exact timestamp matches
- **AND** exactly one canonical admission belongs to the patient on that local
  admission date
- **THEN** the system may reconcile that admission

#### Scenario: Same-day candidates are ambiguous

- **WHEN** two or more canonical admissions for the patient share the candidate
  local date
- **THEN** no admission is changed
- **AND** the result is `ambiguous`

#### Scenario: Matched admission has no start datetime

- **WHEN** key or alias resolves one admission whose `admission_date` is null
- **THEN** the system cannot validate temporal ordering and changes no clinical
  field
- **AND** the result is `conflict` for source synchronization and review

### Requirement: Source adapters declare normalized evidence shape

Each source adapter SHALL provide only the identifiers and temporal precision
actually present in its payload, and the matcher MUST skip unavailable matching
levels instead of synthesizing a key, date or time.

#### Scenario: Discharge XLS has no admission key

- **WHEN** a `DischargeRecord` provides patient record number,
  `data_internacao` as `DD/MM/YYYY` and `saida_em` but no admission key
- **THEN** current-key, alias and exact-start levels are skipped
- **AND** `data_internacao` is treated only as an `America/Bahia` local-date
  candidate

#### Scenario: Discharge admission date cannot be parsed

- **WHEN** `data_internacao` is absent or invalid and no stronger identifier is
  available
- **THEN** the evidence does not fall back to the patient's latest admission
- **AND** the result is `admission_not_found`

#### Scenario: Death has complete datetime but no admission identifier

- **WHEN** death evidence resolves one patient and exactly one canonical
  admission whose known period contains the death datetime
- **THEN** that admission is the unique death candidate
- **AND** zero or multiple compatible periods remain unresolved

### Requirement: Missing mirror data is recovered without synthetic admissions

Exit evidence SHALL remain pending and trigger canonical source synchronization
when the patient or compatible admission is missing; the system MUST NOT create
a synthetic patient or admission from exit evidence alone.

#### Scenario: Patient is missing

- **WHEN** exit evidence does not resolve a mirrored patient
- **THEN** the system records `patient_not_found`
- **AND** enqueues bounded demographic and admissions synchronization
- **AND** creates no Patient or Admission from the evidence

#### Scenario: Admission is missing

- **WHEN** the patient exists but no compatible admission resolves
- **THEN** the system records `admission_not_found`
- **AND** enqueues `admissions_only`
- **AND** does not close the most recent admission by assumption

### Requirement: Corrections to an existing exit require unambiguous evidence

The system SHALL update an existing non-null `discharge_date` only when the
same admission is matched unambiguously and SHALL preserve the prior value in
the audit.

#### Scenario: Unambiguous source correction changes exit time

- **WHEN** the same uniquely matched admission receives a different valid
  `saida_em` from the authoritative source
- **THEN** the system updates `discharge_date`
- **AND** records both values in append-only audit

#### Scenario: Strong matching signals conflict

- **WHEN** a source key or alias resolves one admission but the resolved patient
  or episode period points to a different canonical admission
- **THEN** the system preserves every existing discharge time
- **AND** records `conflict` for manual review

#### Scenario: Multiple candidate admissions are not a conflict

- **WHEN** two or more admissions remain candidates without contradictory strong
  identifiers
- **THEN** the result is `ambiguous`, not `conflict`
- **AND** no admission is changed

### Requirement: Exit types are deliberately minimal

The normalized exit taxonomy SHALL initially contain only
`hospital_discharge`, `death`, and `unknown`; more specific source values MUST
be preserved as raw evidence without speculative normalization.

#### Scenario: Discharge report supplies effective exit

- **WHEN** a discharge report with `saida_em` closes an admission
- **THEN** normalized exit type is `hospital_discharge`

#### Scenario: Unsupported raw classification appears

- **WHEN** the source supplies a classification outside the initial taxonomy
- **THEN** normalized exit type is `unknown`
- **AND** the source value remains available in protected evidence

### Requirement: Date-only death evidence does not synthesize time

A `DeathRecord` with a complete source datetime and a unique admission SHALL
close that admission as `death`; date-only death evidence SHALL trigger
`admissions_only` and MUST NOT synthesize an hour.

#### Scenario: Death datetime uniquely matches

- **WHEN** death evidence contains a valid datetime and resolves exactly one
  admission
- **THEN** the admission is closed at that datetime with exit type `death`
- **AND** the event is excluded from hospital-discharge indicators

#### Scenario: Death has only a date

- **WHEN** death evidence has no source hour
- **THEN** the system keeps reconciliation pending
- **AND** enqueues `admissions_only`
- **AND** does not use midnight, noon or end of day

#### Scenario: Death admission is unresolved

- **WHEN** death evidence cannot uniquely resolve an admission
- **THEN** no synthetic admission is created
- **AND** source synchronization is enqueued for later reconciliation

### Requirement: Legacy PDF flow is inactive and deprecated

The system SHALL retain `process_discharge_pdf` temporarily as an inactive
compatibility command and MUST treat the command and its dedicated PDF helper as
candidates for removal after deprecation verification.

#### Scenario: Legacy PDF command is invoked

- **WHEN** an operator invokes `process_discharge_pdf` with any path or date
- **THEN** the command fails with a safe deprecation message before opening or
  parsing a PDF
- **AND** it does not print patient identity, persist evidence, enqueue work or
  change `Admission.discharge_date`

#### Scenario: Scheduled runtime is inspected

- **WHEN** systemd, cron and container runtime definitions are evaluated
- **THEN** none invokes `process_discharge_pdf`
- **AND** layered capture uses XLS discharge extraction, admissions snapshots,
  death extraction and census-triggered source confirmation instead

#### Scenario: Removal readiness is evaluated

- **WHEN** one release cycle has elapsed with the command inactive
- **AND** static and operational caller inspection finds no invocation
- **THEN** removal of the command, dedicated helper and obsolete tests may be
  proposed without changing canonical reconciliation
