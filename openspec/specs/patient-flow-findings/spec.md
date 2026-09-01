# patient-flow-findings Specification

## Purpose

TBD - created by archiving change recognize-patient-flow-findings. Update Purpose after archive.

## Requirements

### Requirement: Empty admissions can be enriched by the latest encounter

The system SHALL consult the legacy `Atendimentos` list only when a
batch-bound `admissions_only` capture returns a valid empty admissions list and
SHALL return a minimal structured flow snapshot without persisting the source
row.

#### Scenario: Empty batch admissions triggers one encounter fallback

- **WHEN** a batch-bound `admissions_only` run captures a valid empty admissions
  list
- **THEN** the same authenticated job navigates once to `Atendimentos`
- **AND** reads rows from the confirmed PrimeFaces table in `frame_pol`
- **AND** does not start another browser, login, subprocess or ingestion run

#### Scenario: Non-empty or unrelated flow does not trigger fallback

- **WHEN** admissions are non-empty, the run is standalone, or the intent is a
  full-sync intent
- **THEN** the system preserves the existing path
- **AND** does not navigate to `Atendimentos` for this capability

#### Scenario: Encounter parser is structural and fail-closed

- **WHEN** the table body contains synthetic rows with four cells and valid
  `DD/MM/AAAA` dates
- **THEN** the system identifies the latest valid date deterministically
- **AND** malformed, future or structurally incomplete rows do not become valid
  evidence
- **AND** no patient/professional name, row text, HTML or screenshot is stored
  or logged

### Requirement: Date-only encounter evidence uses conservative recency

The system MUST classify encounter dates relative to the local calendar in
`America/Bahia` without claiming unavailable time precision.

#### Scenario: Today or yesterday is recently confirmed

- **WHEN** the latest valid encounter date is today or yesterday locally
- **THEN** recency is `recent_confirmed`
- **AND** the system may recognize the patient as still in an unconsolidated
  recent flow

#### Scenario: Day before yesterday is boundary

- **WHEN** the latest valid date is the day before yesterday
- **THEN** recency is `boundary`
- **AND** the system does not automatically assert either side of 48 hours

#### Scenario: Older or absent evidence is not recent

- **WHEN** the latest valid date is at least three local dates old or no valid
  date exists
- **THEN** recency is `stale` or `none`
- **AND** the empty admissions result remains fail-closed

### Requirement: Recently confirmed empty admissions is an operational finding

A batch-bound `admissions_only` run with empty admissions SHALL succeed only
when the fallback proves `recent_confirmed`, and SHALL record a closed,
sanitized operational outcome without inventing clinical data.

#### Scenario: Recent encounter accepts empty admissions

- **WHEN** admissions are empty and the latest encounter is today or yesterday
- **THEN** the run succeeds with `admissions_seen=0` and all clinical counters
  zero
- **AND** no Patient or Admission is created or changed by that capture
- **AND** no full-sync follow-up is created
- **AND** the batch-owned demographics run remains unchanged
- **AND** a stage metric records only allowlisted outcome and recency codes

#### Scenario: Boundary, stale or absent encounter fails closed

- **WHEN** admissions are empty and encounter recency is `boundary`, `stale` or
  `none`
- **THEN** the existing empty-admissions failure/retry behavior applies
- **AND** no clinical or follow-up effect occurs

#### Scenario: Both workers expose equivalent outcomes

- **WHEN** current and persistent workers receive equivalent synthetic
  admissions and encounter snapshots
- **THEN** run status, counters, attempts, stages, follow-ups and batch drainage
  are equivalent

### Requirement: Patient flow findings are separate from technical outcomes

The system SHALL calculate current operational findings without suppressing a
technical failure and SHALL return closed presentation fields `code`, `label`,
`severity` and `requires_manual_review`.

#### Scenario: Recent attendance without admission is informational

- **WHEN** the latest recognized run proves a recent encounter and no admission
  has subsequently appeared
- **THEN** the patient receives `recent_encounter_without_admission`
- **AND** the finding does not require manual review

#### Scenario: Newborn waiting for registration is informational

- **WHEN** a current-census patient is zero through four local days old and has
  no admission
- **THEN** the patient receives `newborn_waiting_registration`
- **AND** the system does not create an admission or claim an error-free source
  document

#### Scenario: Possible newborn companion requires review

- **WHEN** a current-census patient is five through 28 local days old, has no
  admission and is in the configured Obstetrícia 3A source sector
- **THEN** the patient receives `possible_newborn_companion`
- **AND** the finding explicitly requires manual review

#### Scenario: Recent admission awaits first evolution

- **WHEN** the current admission began less than 48 hours ago and has no events
- **THEN** the patient receives `recent_admission_awaiting_first_evolution`
- **AND** observation-sector context may refine the label without becoming the
  sole evidence

#### Scenario: Older active admission can be suspected residual

- **WHEN** an active admission is at least 48 hours old, its patient remains in
  the current census and it has no event in the previous 48 hours
- **THEN** the patient receives `suspected_legacy_residual`
- **AND** the finding requires manual review
- **AND** the system does not claim that discharge is confirmed

#### Scenario: Timeout remains technical

- **WHEN** a patient satisfies an operational finding and the corresponding
  full-sync failed with timeout or another normalized reason
- **THEN** the finding and technical failure remain independently visible
- **AND** the technical run is not changed to succeeded

### Requirement: Findings are current, auto-resolving and query-bounded

The system SHALL derive findings from current census, demographics, admissions,
events and allowlisted stage outcomes without introducing a second mutable
workflow state.

#### Scenario: New evidence removes an obsolete finding

- **WHEN** a later capture creates an admission/evolution or the patient leaves
  the current census so that a rule no longer holds
- **THEN** subsequent page evaluation no longer returns the obsolete finding
- **AND** no manual cleanup row is required

#### Scenario: Bulk page classification avoids N plus one queries

- **WHEN** a current census page classifies many patients
- **THEN** the query count remains within a fixed allowance independent of the
  patient count
- **AND** templates perform no database query or business classification

### Requirement: Patient flow findings are visible on authorized pages

The system SHALL display the same current finding semantics on `/censo`,
`/beds` and the patient admissions page under existing authentication.

#### Scenario: Current census row shows a finding

- **WHEN** an authenticated user opens `/censo` for a patient with a current
  finding
- **THEN** the desktop row and mobile card display an accessible badge

#### Scenario: Bed detail shows a finding

- **WHEN** an authenticated user opens `/beds` and an identified patient has a
  current finding
- **THEN** every applicable patient presentation displays the same finding
- **AND** official occupancy values remain unchanged

#### Scenario: Admissions page shows a finding

- **WHEN** an authenticated user opens the admissions page for a patient with a
  current finding
- **THEN** the page displays its label and whether manual review is required

#### Scenario: Existing authorization is preserved

- **WHEN** an anonymous user requests any affected page
- **THEN** existing login redirection remains
- **AND** no finding or patient information is disclosed
