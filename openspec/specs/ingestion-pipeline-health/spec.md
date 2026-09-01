# ingestion-pipeline-health Specification

## Purpose

TBD - created by archiving change repair-persistent-admissions-pipeline. Update Purpose after archive.

## Requirements

### Requirement: Pipeline health is observable through aggregate diagnostics

The system SHALL expose a Django management command that evaluates the recent
census-to-evolution ingestion pipeline using only aggregate metrics.

#### Scenario: Healthy pipeline returns success

- **WHEN** no configured invariant or threshold is violated in the selected
  window
- **THEN** the command returns process status zero
- **AND** prints aggregate counts for admissions, demographics, full-sync,
  events and active queue state

#### Scenario: Output is sanitized

- **WHEN** health is evaluated in success or failure
- **THEN** stdout, stderr and `CommandError` contain no run/batch/patient/
  admission/event identifier, name, record, clinical text, URL, cookie,
  credential, HTML or PDF content

### Requirement: Empty-success and follow-up invariants fail closed

The health command SHALL report nonzero status when corrected batch invariants
are violated, SHALL exclude only an empty admissions success backed by the
closed recent-encounter outcome, and SHALL expose the recognized count
separately.

#### Scenario: Recognized recent encounter is not empty-success anomaly

- **WHEN** the window contains a batch-bound `admissions_only` run with status
  succeeded, `admissions_seen=0` and the allowlisted
  `recent_encounter_without_admission` stage outcome
- **THEN** health does not count that run as `empty_success`
- **AND** output increments only the aggregate recognized-encounter count

#### Scenario: Unrecognized batch admissions succeeded with zero

- **WHEN** the window contains a batch-bound `admissions_only` run with status
  succeeded and `admissions_seen=0`
- **AND** it lacks the exact allowlisted recent-encounter stage outcome
- **THEN** health is unhealthy
- **AND** output reports only the aggregate anomaly count

#### Scenario: Forged or partial stage details do not bypass invariant

- **WHEN** a zero-admissions success contains an unknown outcome, wrong stage,
  boundary/stale recency or malformed details
- **THEN** it remains an empty-success anomaly

#### Scenario: Valid batch admissions lacks full-sync

- **WHEN** a batch contains a succeeded non-empty admissions run without a
  corresponding full-sync run
- **THEN** health is unhealthy after the configured settling boundary
- **AND** output reports only aggregate missing-follow-up counts

#### Scenario: Recognized empty does not require full-sync

- **WHEN** a batch admissions run succeeded only through recent-encounter
  evidence and persisted no admission
- **THEN** health does not report missing full-sync for that run

#### Scenario: Demographics exceeds batch ownership

- **WHEN** a batch contains more demographics runs than its admissions owner
  count permits
- **THEN** health is unhealthy
- **AND** output reports an aggregate duplicate count

### Requirement: Queue and evolution failures are alertable

The health command SHALL evaluate active-work age and full-sync terminal failure
rate against explicit thresholds.

#### Scenario: Active work is too old

- **WHEN** the oldest queued/running supported ingestion work exceeds the
  configured maximum age
- **THEN** health is unhealthy
- **AND** no identity of that work is printed

#### Scenario: Full-sync failure rate exceeds threshold

- **WHEN** the minimum terminal sample is reached
- **AND** the full-sync failure percentage exceeds the configured threshold
- **THEN** health is unhealthy
- **AND** output includes aggregate failures grouped by normalized
  `failure_reason`

#### Scenario: Small sample does not trigger percentage alarm

- **WHEN** terminal full-sync count is below the configured minimum sample
- **THEN** failure percentage is reported as informational
- **AND** does not independently make health unhealthy

### Requirement: Domain freshness checks are explicit and optional

The health command SHALL report aggregate age for the latest movement,
admission update and clinical event and SHALL enforce freshness only when the
corresponding operator threshold is supplied.

#### Scenario: Freshness threshold is omitted

- **WHEN** no maximum age is supplied for a domain timestamp
- **THEN** the age is informational and does not alter exit status

#### Scenario: Freshness threshold is exceeded

- **WHEN** an operator supplies a domain maximum age
- **AND** the corresponding latest aggregate timestamp is absent or older
- **THEN** health is unhealthy without printing any domain record identity

### Requirement: Health command is suitable for external scheduling

The command SHALL remain a one-shot read-only diagnostic suitable for systemd
or another existing scheduler.

#### Scenario: Health evaluation does not mutate state

- **WHEN** health runs in healthy or unhealthy conditions
- **THEN** no model row, status, counter, attempt, batch or clinical record is
  created, updated or deleted
- **AND** no Playwright action or source-system request occurs
