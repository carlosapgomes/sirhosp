## MODIFIED Requirements

### Requirement: Catalog versions declare immutable occupancy algorithm context

Every newly published capacity catalog SHALL declare one supported occupancy
algorithm version, SHALL persist that exact value and SHALL dispatch
materialization from the applicable immutable catalog rather than date or code
defaults.

#### Scenario: V4 is explicitly declared

- **WHEN** a valid future catalog declares `occupancy-v4`
- **THEN** the catalog stores `occupancy-v4`
- **AND** v4 typed conflict and quality semantics are selected

#### Scenario: Unsupported algorithm is rejected

- **WHEN** a catalog declares an unknown algorithm version
- **THEN** validation fails before persistence
- **AND** no catalog, group or membership is created

#### Scenario: Historical algorithm fallback remains

- **WHEN** a published legacy catalog has no explicit algorithm
- **THEN** structural dispatch continues to reproduce v1 or v2
- **AND** the historical catalog is not edited

### Requirement: Published catalog versions remain immutable

The system SHALL preserve every published catalog version and SHALL create a new
future complete version for changes in name, clean source alias, composition,
capacity, identity or occupancy algorithm.

#### Scenario: Clean source alias changes

- **WHEN** a source-facing display alias must be corrected
- **THEN** an operator publishes a complete future catalog
- **AND** earlier memberships retain their stored aliases or historical fallback

#### Scenario: V4 publication does not edit v3

- **WHEN** a v4 document is added and later activated
- **THEN** the v3 JSON, catalog, groups and memberships remain unchanged
- **AND** v3 measurements retain their original presentation context

## ADDED Requirements

### Requirement: New catalog memberships declare clean source aliases

Every membership in the new catalog schema SHALL declare a non-empty curated
`source_display_name` for user-facing source presentation while preserving
`configured_source_name` as the raw expected source label.

#### Scenario: Alias and raw source name are distinct

- **WHEN** a source membership is parsed
- **THEN** `configured_source_name` preserves the technical source label
- **AND** `source_display_name` preserves the clean human-facing alias
- **AND** runtime does not strip prefixes by heuristic or regex

#### Scenario: Alias is missing or blank

- **WHEN** a new-schema membership omits `source_display_name` or provides only
  whitespace
- **THEN** validation fails before persistence

#### Scenario: Same code appears in age partition

- **WHEN** one code has `under_12` and `age_12_or_over` memberships
- **THEN** both memberships declare the same clean source alias
- **AND** divergent aliases for that code are rejected

#### Scenario: Legacy membership lacks alias

- **WHEN** an older published membership has no clean alias
- **THEN** it remains valid and immutable
- **AND** presentation uses a documented historical fallback without altering
  the row

#### Scenario: Alias length is bounded

- **WHEN** a new alias exceeds the persisted field limit
- **THEN** validation reports the field path safely
- **AND** persists no partial catalog

### Requirement: V4 catalog preserves official policy and adds presentation aliases

The complete v4 catalog SHALL preserve 43 official groups, 48 memberships over
47 source codes, 39 standard groups, four unrated groups, capacities 666/666,
CO policy and 3A partition while declaring v4 and clean aliases.

#### Scenario: V4 document passes dry-run

- **WHEN** the operator validates the v4 document for a future date with
  `--dry-run`
- **THEN** output reports `occupancy-v4`, 43 groups, 48 memberships, 47 codes,
  four unrated groups and capacities 666/666
- **AND** reports complete clean-alias coverage
- **AND** persists no row

#### Scenario: Complex mappings have clean aliases

- **WHEN** the v4 document is inspected
- **THEN** the 3A source code has one consistent physical alias across two
  official groups
- **AND** Cardio source codes have their own clean aliases under the shared
  group
- **AND** all CO source codes have curated aliases under the unrated group

#### Scenario: Existing artifacts remain byte-preserved

- **WHEN** the v4 JSON is added
- **THEN** initial, corrected and v3 JSON files are not edited
- **AND** the v4 file has its own SHA-256

#### Scenario: V4 activates separately from deployment

- **WHEN** a v4-capable release is already deployed and an approved future date
  is supplied
- **THEN** the atomic activation command publishes v4 explicitly
- **AND** build, migration and container startup do not activate it

#### Scenario: One local day uses one algorithm

- **WHEN** v4 becomes effective at midnight in `America/Bahia`
- **THEN** every accepted census measurement on that local day uses v4
- **AND** no local day mixes v3 and v4
