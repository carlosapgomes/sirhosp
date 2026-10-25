## ADDED Requirements

### Requirement: Cardio unit is titled by its official group display name

The bed status page SHALL render capacity units with the exact `display_name`
of the applicable catalog version and SHALL order units by that title without
ad-hoc renaming, so a renamed group is listed under its new official name in
alphabetical position.

#### Scenario: Renamed Cardio group renders its clean title

- **WHEN** the applicable measurement uses the v6 catalog
- **THEN** the Cardio unit header shows `Enfermaria 2B Cardio`
- **AND** the legacy combined label is not used as a unit title

#### Scenario: Renamed unit sorts with second-floor peers

- **WHEN** the page lists units in ascending title order
- **THEN** `Enfermaria 2B Cardio` appears among the other `Enfermaria 2…`
  unit titles according to the title ordering

#### Scenario: Historical measurements keep their labels

- **WHEN** an exact measurement materialized under v5 or earlier is presented
- **THEN** it keeps the label captured at materialization time
- **AND** no backfill renames historical presentations
