## ADDED Requirements

### Requirement: Census absence creates a conservative reconciliation case

The system SHALL observe patient absence only across complete, unambiguous
current-census runs and MUST NOT use absence itself to set a discharge time.

#### Scenario: Two complete censuses confirm absence

- **WHEN** a patient with a canonical open admission is absent from two
  consecutive accepted census runs
- **AND** at least 30 minutes elapsed between the first confirmed absence and
  evaluation
- **THEN** the system creates or advances one reconciliation case for the
  admission
- **AND** does not change `Admission.discharge_date`

#### Scenario: One census is insufficient

- **WHEN** the patient is absent from only one accepted census
- **THEN** the case does not become eligible for automatic source confirmation

#### Scenario: Incomplete or ambiguous census is ignored

- **WHEN** a census lacks minimum sector coverage or unique run provenance
- **THEN** it does not increment or reset an absence sequence
- **AND** creates no reconciliation work

#### Scenario: Patient reappears

- **WHEN** the patient reappears in an accepted census before a census-only
  suspicion is processed
- **THEN** that suspicion is resolved without source mutation
- **AND** explicit exit evidence for a previous episode remains valid

### Requirement: Explicit exit evidence bypasses census waiting

A uniquely matched `DischargeRecord.saida_em` SHALL be eligible for immediate
reconciliation without waiting for two absent censuses.

#### Scenario: Effective exit is available

- **WHEN** valid `saida_em` uniquely matches an admission
- **THEN** canonical exit reconciliation may run immediately
- **AND** census presence or absence does not replace the episode match

### Requirement: Official census is corroborative only

The official daily census SHALL be available to reviewers as additional
evidence but MUST NOT be required or treated as the primary source for closing
an admission.

#### Scenario: Censuses disagree

- **WHEN** the current census and official daily census disagree about one
  patient
- **THEN** the case remains subject to current-census timing and authoritative
  source confirmation
- **AND** no admission is closed from that disagreement alone

### Requirement: Confirmation queue is bounded and idempotent

Automatic stale-admission confirmation SHALL use PostgreSQL-backed
`admissions_only` runs, enqueue at most 100 patients per cycle and avoid active
or cooldown duplicates.

#### Scenario: Eligible case is enqueued

- **WHEN** a confirmed absence case has no active equivalent run
- **AND** its cooldown elapsed
- **THEN** one canonical `admissions_only` run is enqueued

#### Scenario: Active work already exists

- **WHEN** a queued or running admissions confirmation exists for the patient
- **THEN** no duplicate run is created

#### Scenario: Recent suspicion is cooling down

- **WHEN** fewer than 6 hours elapsed since a recent inconclusive attempt
- **THEN** the case is not enqueued again

#### Scenario: Conclusive no-discharge result is cooling down

- **WHEN** fewer than 24 hours elapsed since a conclusive source response that
  still contains no exit
- **THEN** the case is not enqueued again

#### Scenario: More than one hundred cases are eligible

- **WHEN** a cycle finds more than 100 eligible cases
- **THEN** at most 100 are enqueued in deterministic oldest-first order
- **AND** the remainder stay eligible for later cycles

### Requirement: Reconciliation review is permission-protected

The system SHALL define a dedicated reconciliation-review permission and show
patient names and record numbers only to authenticated users who hold it.

#### Scenario: Authorized reviewer opens the queue

- **WHEN** a user with the dedicated permission opens the review page
- **THEN** pending, ambiguous and conflicting cases include the patient name,
  record number and protected evidence needed for investigation

#### Scenario: Authenticated user lacks permission

- **WHEN** an authenticated user without the permission requests the review page
- **THEN** access is denied without disclosing case existence or identity

#### Scenario: Anonymous user requests the review page

- **WHEN** an anonymous user requests the review page
- **THEN** existing authentication behavior is preserved
- **AND** no patient information is disclosed

### Requirement: Authorized CSV export is ephemeral

The review queue SHALL support an authenticated, permission-checked CSV stream
that is generated on demand and is not persisted on the application server.

#### Scenario: Authorized user exports cases

- **WHEN** a reviewer with the dedicated permission requests CSV export
- **THEN** the response streams the filtered case data
- **AND** may include patient names and record numbers
- **AND** no residual export file is written to disk

#### Scenario: Export is logged safely

- **WHEN** an export succeeds or fails
- **THEN** logs contain only actor-independent aggregate outcome metadata
- **AND** contain no patient name, record number or CSV body

### Requirement: Daily integrity report is aggregate-safe

The system SHALL expose daily aggregate counts for open admissions outside the
census, unreconciled exits, ambiguities, duplicate candidates, missing coverage
and backlog age without logging patient identity.

#### Scenario: Integrity report runs

- **WHEN** the scheduled diagnostic evaluates reconciliation health
- **THEN** it reports each required aggregate and oldest backlog age
- **AND** does not print names, record numbers or clinical content
