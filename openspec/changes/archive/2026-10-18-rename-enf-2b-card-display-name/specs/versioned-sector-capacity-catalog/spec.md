## ADDED Requirements

### Requirement: V6 catalog renames the Cardio group display name

The complete v6 catalog SHALL preserve 43 official groups, 48 memberships over
47 source codes, 39 standard groups, four unrated groups, known/calculable
capacity 666/666, CO policy, 3A partition, all clean source aliases and the
`occupancy-v5` algorithm context while renaming only the `ENF-2B-CARD` group
display name to `Enfermaria 2B Cardio`.

#### Scenario: Only the Cardio display name changes from v5

- **WHEN** normalized v5 and v6 documents are compared
- **THEN** every group is identical except the `ENF-2B-CARD` `display_name`
- **AND** v5 keeps `Cardioclinica / Enfermaria 2B Cardio` while v6 declares
  `Enfermaria 2B Cardio`
- **AND** v6 declares a distinct source reference and its own SHA-256

#### Scenario: Clean source aliases remain untouched

- **WHEN** the v6 memberships are inspected
- **THEN** source code `719` keeps the clean alias `Cardioclínica`
- **AND** source code `2156` keeps the clean alias `Enfermaria 2B Cardio`
- **AND** complete clean-alias coverage remains 48/48

#### Scenario: V6 document passes dry-run

- **WHEN** the operator validates the v6 document for a strictly future local
  date in `America/Bahia` with `--dry-run`
- **THEN** output reports `occupancy-v5`, 43 groups, 48 memberships, 47 codes,
  39 standard groups, four unrated groups and capacities 666/666
- **AND** the clean-alias coverage 48/48 is enforced by the catalog contract
  (`aliased_membership_count`), not printed by the command
- **AND** no catalog, group or membership row is persisted

#### Scenario: Historical catalogs remain byte-preserved

- **WHEN** the v6 JSON is added
- **THEN** the initial, corrected, v3, v4 and v5 JSON files are not edited
- **AND** their existing contract tests keep passing unchanged

#### Scenario: V6 activates explicitly for a future local day

- **WHEN** the operator publishes v6 through the existing atomic future-date
  command for an approved date
- **THEN** one complete v6 version is created atomically
- **AND** an exact retry is an idempotent no-op
- **AND** no local day mixes v5 and v6 catalogs
