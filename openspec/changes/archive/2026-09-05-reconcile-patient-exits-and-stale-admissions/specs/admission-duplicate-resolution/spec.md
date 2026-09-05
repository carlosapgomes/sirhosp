## ADDED Requirements

### Requirement: Admission identity survives external key changes

The system SHALL preserve every observed external admission key as an alias of
one canonical admission and MUST treat the external key as one matching signal,
not as the clinical identity by itself.

#### Scenario: Existing episode receives a new source key

- **WHEN** an admissions snapshot contains a new source key for the same
  uniquely identified patient episode
- **THEN** the existing canonical admission is updated
- **AND** the new key is stored as an alias
- **AND** no second admission is created

#### Scenario: Alias is observed again

- **WHEN** a later snapshot uses a previously stored alias
- **THEN** the canonical admission is reused idempotently

### Requirement: Open-to-closed transition reuses the canonical episode

An incoming closed snapshot SHALL update a compatible open admission even when
the source key changed, provided the episode match is unique.

#### Scenario: Changed key closes one open episode

- **WHEN** one patient has exactly one compatible open admission
- **AND** the source returns the same episode with a different key and an end
  datetime
- **THEN** the system updates the existing admission with the end datetime
- **AND** stores the different key as an alias

#### Scenario: Same-day ambiguity prevents automatic transition

- **WHEN** multiple admissions could represent the incoming closed episode
- **THEN** none is closed or merged automatically
- **AND** the conflict is exposed for review

### Requirement: Automatic merge requires authoritative episode confirmation

The system MUST merge an open/closed pair automatically only after a fresh
source admissions snapshot confirms that exactly one source episode exists for
the relevant patient and local admission date.

#### Scenario: Source confirms one episode

- **WHEN** local data contains an open/closed candidate pair
- **AND** a fresh source snapshot confirms exactly one episode on that date
- **THEN** the pair is eligible for automatic merge

#### Scenario: Source confirms multiple episodes

- **WHEN** the source snapshot contains two or more episodes on the date
- **THEN** no automatic merge occurs
- **AND** the case requires manual review

#### Scenario: Source confirmation fails

- **WHEN** source synchronization times out, fails or returns an invalid empty
  snapshot
- **THEN** no automatic merge occurs
- **AND** existing retry semantics remain in force

### Requirement: Merge preserves the oldest canonical record and all relations

A confirmed merge SHALL keep the oldest Admission primary key, repoint every
supported relation, preserve all external keys as aliases and mark the other
record as merged rather than deleting it.

#### Scenario: Confirmed duplicate is merged

- **WHEN** an eligible open/closed pair is applied
- **THEN** the oldest Admission remains canonical
- **AND** its final period contains the authoritative start and exit values
- **AND** related clinical events, movements, summaries and other inventoried
  foreign keys refer to the canonical admission
- **AND** the other admission references the canonical row through `merged_into`

#### Scenario: Merged record is hidden clinically

- **WHEN** a normal clinical query or patient-facing view lists admissions
- **THEN** merged records are excluded
- **AND** the canonical admission appears only once

#### Scenario: Administrator inspects merge history

- **WHEN** an authorized administrator opens the merged record
- **THEN** the record remains visible as merged
- **AND** identifies its canonical `merged_into` target and audit operation

### Requirement: Admission merge is audited and reversible

Every merge MUST create an indefinite audit record sufficient to restore prior
field values and relation ownership without relying only on a database backup.

#### Scenario: Merge audit is recorded

- **WHEN** a merge succeeds
- **THEN** one operation identifier records canonical and merged admissions,
  prior field values, moved relation counts, source confirmation and timestamp
- **AND** no patient name, record number or clinical text enters logs

#### Scenario: Rollback is requested

- **WHEN** an authorized operator selects a reversible merge operation
- **THEN** the system validates that no incompatible later mutation blocks
  rollback
- **AND** restores the recorded admissions and relations atomically

#### Scenario: Later mutation makes rollback unsafe

- **WHEN** current state no longer matches the post-merge audit boundary
- **THEN** rollback fails before mutation
- **AND** reports an aggregate-safe conflict
