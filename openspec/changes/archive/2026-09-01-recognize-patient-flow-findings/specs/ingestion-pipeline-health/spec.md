## MODIFIED Requirements

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
