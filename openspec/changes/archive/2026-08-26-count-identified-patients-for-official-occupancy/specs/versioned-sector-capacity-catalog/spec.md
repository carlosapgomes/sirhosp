## MODIFIED Requirements

### Requirement: Catalog versions declare immutable occupancy algorithm context

Every newly published capacity catalog SHALL declare one supported occupancy
algorithm version, SHALL persist it exactly and SHALL dispatch materialization
from the applicable immutable catalog rather than date, filename or deployed
code defaults.

#### Scenario: V5 is explicitly declared

- **WHEN** a valid future catalog declares `occupancy-v5`
- **THEN** the catalog stores `occupancy-v5`
- **AND** identified-patient counting semantics are selected

#### Scenario: Unsupported algorithm remains rejected

- **WHEN** a catalog declares an algorithm outside the implementation allowlist
- **THEN** validation fails before persistence
- **AND** no version, group or membership is created

#### Scenario: Historical algorithms remain dispatchable

- **WHEN** an earlier catalog declares v3/v4 or structurally resolves v1/v2
- **THEN** its original algorithm remains selected for its historical date
- **AND** v5 support does not edit or reinterpret it

### Requirement: Published catalog versions remain immutable

The system SHALL preserve every published version and JSON artifact and SHALL
create a complete new future version for a change of occupancy algorithm.

#### Scenario: V5 publication does not edit v4

- **WHEN** the v5 document is added, validated or published
- **THEN** initial, corrected, v3 and v4 JSON documents remain byte-preserved
- **AND** all four published database catalogs retain dates, hashes, groups and
  memberships

## ADDED Requirements

### Requirement: V5 catalog preserves official policy and presentation aliases

The complete v5 catalog SHALL preserve 43 official groups, 48 memberships over
47 source codes, 39 standard groups, four unrated groups, known/calculable
capacity 666/666, CO policy, 3A capacities/selectors and aliases 48/48 while
declaring `occupancy-v5`.

#### Scenario: V5 document passes dry-run

- **WHEN** the operator validates the v5 JSON for a strictly future local date
  with `--dry-run`
- **THEN** output reports `occupancy-v5`, 43/48/47, 39 standard, four unrated,
  666/666 and aliases 48/48
- **AND** no catalog, group or membership row is persisted

#### Scenario: Only algorithm context changes from v4

- **WHEN** normalized v4 and v5 documents are compared
- **THEN** groups, capacities, policies, memberships, selectors, raw names and
  clean aliases are identical
- **AND** v5 has a distinct source reference and SHA-256

#### Scenario: CO remains outside the rate

- **WHEN** v5 catalog is validated
- **THEN** all five CO source codes remain under the unrated CO group
- **AND** CO declares no capacity

#### Scenario: 3A partition remains unchanged

- **WHEN** v5 catalog is validated
- **THEN** Adulto remains capacity 32 with `age_12_or_over`
- **AND** Infantil remains capacity 16 with `under_12`
- **AND** no combined 3A capacity is created

### Requirement: V5 activates separately and only for a future local day

V5 SHALL be published only after a v5-capable immutable release is deployed and
only through the existing atomic future-date command.

#### Scenario: Deploy does not publish v5

- **WHEN** v5 code, migration and image are deployed
- **THEN** v4 remains the applicable catalog
- **AND** startup/build/migration create zero v5 catalogs and measurements

#### Scenario: Operator dry-runs approved document

- **WHEN** an operator supplies the exact v5 document and approved future date
- **THEN** dry-run validates hash and totals without writing
- **AND** a deterministic aggregate database snapshot is unchanged

#### Scenario: Operator publishes v5 explicitly

- **WHEN** the release is healthy and the operator invokes activation without
  `--dry-run` for the approved future date
- **THEN** one complete v5 version is created atomically
- **AND** an exact retry is an idempotent no-op

#### Scenario: One local day uses one algorithm

- **WHEN** v5 becomes effective at midnight in `America/Bahia`
- **THEN** every accepted census on that date uses v5
- **AND** the preceding date remains entirely v4
- **AND** no backfill is performed
