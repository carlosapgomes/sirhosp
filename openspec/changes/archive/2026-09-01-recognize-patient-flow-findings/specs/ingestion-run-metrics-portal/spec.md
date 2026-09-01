## ADDED Requirements

### Requirement: Batch metrics separate findings from technical failures

The authenticated ingestion metrics portal SHALL aggregate allowlisted patient
flow outcomes separately from terminal technical failures without changing the
persisted batch status.

#### Scenario: Succeeded batch contains recognized findings

- **WHEN** the selected/latest batch is persisted as succeeded and contains one
  or more recognized patient-flow outcomes
- **THEN** the portal displays `Concluído com achados`
- **AND** shows aggregate finding counts by allowlisted label
- **AND** does not call those outcomes technical failures

#### Scenario: Failed batch contains findings and failures

- **WHEN** a failed batch contains recognized outcomes and terminal failed runs
- **THEN** the portal displays `Falha parcial`
- **AND** shows separate totals for operational findings and technical failures

#### Scenario: Batch has no findings

- **WHEN** a batch contains no recognized patient-flow outcome
- **THEN** existing success/failure presentation remains
- **AND** no empty finding card or misleading derived status is required

#### Scenario: Metrics remain aggregate and authorized

- **WHEN** metrics render findings in summary/history/detail
- **THEN** they expose only counts, codes/labels and batch-level status
- **AND** do not add patient record, name, encounter date, professional,
  clinical text or source row values
- **AND** anonymous access remains redirected to login

### Requirement: Technical full-sync failures remain visible beside findings

The portal MUST preserve normalized technical failure reasons even when the
same patient currently qualifies for an operational finding.

#### Scenario: Suspected residual also has timeout

- **WHEN** a patient qualifies as suspected residual and its full-sync failed
  with timeout
- **THEN** aggregate technical metrics continue counting that timeout
- **AND** the finding does not rewrite the run or batch history
