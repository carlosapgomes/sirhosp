## ADDED Requirements

### Requirement: Bed status patient lines display current flow findings

The authenticated `/beds/` page SHALL display current patient-flow findings on
identified patient lines without changing exact-run occupancy evidence,
capacity arithmetic or authority semantics.

#### Scenario: V5 identified patient has a finding

- **WHEN** a v5 unit lists an identified patient with a current finding
- **THEN** the patient item displays its accessible finding badge
- **AND** official numerator, capacity, balance and rate remain unchanged

#### Scenario: Historical physical patient has a finding

- **WHEN** a v1–v4 physical/source presentation lists an identified patient
  with a current finding
- **THEN** the applicable patient line displays the same shared label
- **AND** the finding does not select an authoritative conflict alternative

#### Scenario: Review finding is explicit

- **WHEN** the finding requires manual review
- **THEN** the badge text communicates review in the legacy record is needed
- **AND** it does not claim discharge or transfer as confirmed

#### Scenario: Finding lookup is bulk and ephemeral

- **WHEN** `/beds/` renders many units and patient alternatives
- **THEN** the view builds one bulk finding map before template rendering
- **AND** no finding is copied to occupancy measurement, daily summary,
  reconciliation JSON, log or report
- **AND** no template-loop database query is executed

#### Scenario: Anonymous access remains protected

- **WHEN** an anonymous user requests `/beds/`
- **THEN** existing login redirection remains
- **AND** no finding or patient detail is rendered
