## ADDED Requirements

### Requirement: Catalog versions declare immutable occupancy algorithm context

Every newly published capacity catalog SHALL declare a supported occupancy
algorithm version, and materialization SHALL dispatch from the persisted
applicable catalog rather than from current date or deployed code defaults.

#### Scenario: Existing catalog omits explicit algorithm

- **WHEN** a catalog published before this schema has no explicit algorithm
- **THEN** it retains the existing deterministic structural dispatch to v1 or v2
- **AND** the catalog and its historical measurements are not edited

#### Scenario: New catalog omits explicit algorithm

- **WHEN** a new catalog document using the updated schema omits its algorithm
- **THEN** validation fails before persistence

#### Scenario: Unsupported algorithm is declared

- **WHEN** a catalog declares an unknown algorithm version
- **THEN** validation fails before persistence
- **AND** no catalog row is created

#### Scenario: Explicit algorithm is persisted

- **WHEN** a valid future catalog declares `occupancy-v3`
- **THEN** the version stores that exact value as immutable calculation context
- **AND** a future code change cannot reinterpret its algorithm selection

### Requirement: V3 catalog preserves current official policy and changes only calculation semantics

The v3 complete catalog SHALL preserve the corrected 43 official sectors, 48
memberships over 47 source codes, four unrated sectors, capacities 666/666 and
all CO and 3A definitions while declaring `occupancy-v3`.

#### Scenario: V3 document passes dry-run

- **WHEN** the operator validates the v3 document with a future effective date
  and `--dry-run`
- **THEN** the command reports algorithm `occupancy-v3`, 43 groups, 48
  memberships, 47 distinct codes and capacities 666/666
- **AND** persists no row

#### Scenario: Earlier catalog artifacts remain unchanged

- **WHEN** the v3 document is added
- **THEN** neither the initial nor corrected JSON artifact is edited
- **AND** the published 2026-08-19 and 2026-08-21 versions remain immutable

#### Scenario: Operator activates v3 separately from deploy

- **WHEN** the v3-capable release is already running and the operator supplies
  an approved future local date
- **THEN** the existing atomic activation command publishes the complete v3
  catalog for that date
- **AND** build, migration and container startup never publish it automatically

#### Scenario: Same local day uses one algorithm

- **WHEN** v3 becomes effective at midnight in `America/Bahia`
- **THEN** every accepted census for that local day uses v3
- **AND** no day mixes v2 and v3 measurements
