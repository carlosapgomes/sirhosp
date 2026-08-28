# patient-admission-mirror Delta Specification

## MODIFIED Requirements

### Requirement: Empty admission snapshot does not create extraction candidates

The mirror layer MUST preserve the invariant that evolutions require at least
one known admission and MUST distinguish a valid standalone no-admissions
outcome from an invalid empty capture for a census/recovery batch.

#### Scenario: Empty standalone snapshot on admissions sync

- **WHEN** a standalone source admissions snapshot is valid and empty for the
  requested registro
- **THEN** the system records an explicit no-admissions outcome
- **AND** no admission extraction candidate is produced for follow-up actions

#### Scenario: Empty batch-bound snapshot is not a successful sync

- **WHEN** a patient admissions snapshot is captured for a run linked to a
  census/recovery batch
- **AND** the normalized snapshot is empty
- **THEN** the system treats the capture as an invalid source outcome
- **AND** no Patient or Admission is persisted from that outcome
- **AND** no evolution extraction candidate is produced
- **AND** the run does not reach succeeded with `admissions_seen=0`

#### Scenario: Current and persistent workers apply the same invariant

- **WHEN** either ingestion worker processes an empty batch-bound admissions
  capture
- **THEN** status, attempts, stage failure, normalized reason and absence of
  clinical/follow-up effects are observably equivalent
