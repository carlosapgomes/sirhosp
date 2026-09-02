# patient-flow-findings Delta — `clarify-patient-flow-labels`

## ADDED Requirements

### Requirement: Finding labels use hospital-accessible language

Visible finding labels SHALL use hospital-operational language and SHALL
NOT expose internal system terminology, with the residual and
mirror-stale labels pinned as closed texts.

#### Scenario: Residual suspicion label renders without system jargon

- **WHEN** the `suspected_legacy_residual` finding renders on any surface
  (census, beds, admissions or ingestion metrics)
- **THEN** the visible label is exactly "Suspeita de paciente residual"
- **AND** the label contains no system or IT terminology such as "legado"

#### Scenario: Mirror-stale label names the two possible causes

- **WHEN** the `mirror_stale_admission` finding renders on any surface
- **THEN** the visible label is exactly "Suspeita de internação antiga em
  aberto ou alta não detectada"
- **AND** the label contains no system or IT terminology such as "espelho"
  or "órfã"
- **AND** the label does not assert which of the two causes holds

#### Scenario: Label changes are presentational only

- **WHEN** any finding label renders
- **THEN** the finding code, severity and manual-review flag remain
  unchanged
- **AND** nothing is persisted or migrated by the label itself
