## MODIFIED Requirements

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
