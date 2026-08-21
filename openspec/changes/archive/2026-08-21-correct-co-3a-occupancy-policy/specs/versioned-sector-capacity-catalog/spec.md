## MODIFIED Requirements

### Requirement: Catalog validation prevents ambiguous mappings

The system MUST reject a catalog document that cannot produce one deterministic
capacity mapping for every configured source code and supported membership
partition.

#### Scenario: Duplicate unpartitioned source code is rejected

- **WHEN** the same source code belongs to more than one `all` membership in one
  catalog
- **THEN** validation fails before persistence

#### Scenario: Unpartitioned and age-partitioned memberships cannot mix

- **WHEN** one source code declares an `all` membership together with an age
  membership
- **THEN** validation fails before persistence

#### Scenario: Incomplete or duplicate age partition is rejected

- **WHEN** a multiply-associated source code does not declare exactly one
  `under_12` and one `age_12_or_over` membership
- **THEN** validation fails before persistence

#### Scenario: Complete age partition is accepted

- **WHEN** one source code declares exactly one `under_12` and one
  `age_12_or_over` membership in different official groups
- **THEN** the two memberships are accepted as mutually exclusive
- **AND** the code remains one distinct source code for diagnostic counts

#### Scenario: Duplicate stable group key is rejected

- **WHEN** two groups in one catalog use the same stable key
- **THEN** validation fails before persistence

#### Scenario: Standard group has invalid capacity

- **WHEN** a `standard` group has a missing, zero or negative capacity
- **THEN** validation fails before persistence

#### Scenario: Pending linked-slot group has invalid capacity

- **WHEN** a `linked_slots_pending` group has a missing, zero or negative
  capacity
- **THEN** validation fails before persistence

#### Scenario: Unrated group declares capacity

- **WHEN** an `unrated` group declares a non-null capacity
- **THEN** validation fails before persistence

## ADDED Requirements

### Requirement: Membership selectors are temporal catalog data

Every catalog membership SHALL persist one supported selector and every
measurement SHALL be able to snapshot the selector used, so a future partition
change cannot reinterpret history.

#### Scenario: Existing membership omits selector

- **WHEN** a legacy catalog membership has no explicit selector
- **THEN** migration and parsing treat it as `all`
- **AND** its existing source mapping remains unchanged

#### Scenario: Future catalog changes a partition

- **WHEN** a future complete catalog changes a membership selector
- **THEN** the earlier catalog retains its original selector
- **AND** existing measurements are not recalculated

### Requirement: Corrected catalog represents the approved CO and 3A policy

The corrected complete catalog SHALL contain 43 official sectors, 48
memberships over 47 distinct source codes, 39 standard capacity-bearing sectors,
four unrated sectors, known capacity 666 and calculable capacity 666.

#### Scenario: Centro Obstétrico is unrated

- **WHEN** the corrected catalog is validated
- **THEN** codes `20`, `1110`, `1112`, `1114` and `1116` remain together in
  group `CO`
- **AND** `CO` uses policy `unrated` with null capacity

#### Scenario: Obstetrícia 3A is split into two official sectors

- **WHEN** the corrected catalog is validated
- **THEN** `OBST-3A-ADULTO` has capacity 32 and membership
  `654/age_12_or_over`
- **AND** `OBST-3A-INFANTIL` has capacity 16 and membership `654/under_12`
- **AND** both groups use policy `standard`

#### Scenario: Corrected totals are reported by dry-run

- **WHEN** the operator validates the corrected document with `--dry-run`
- **THEN** the command reports 43 groups, 48 memberships and 47 distinct codes
- **AND** reports known capacity 666 and calculable capacity 666
- **AND** persists no row

#### Scenario: Initial catalog artifact remains unchanged

- **WHEN** the corrected catalog document is added
- **THEN** it uses a new versioned file rather than overwriting the initial JSON
- **AND** the published catalog effective `2026-08-19` remains immutable

### Requirement: Corrected catalog activates only after the corrective deploy

The corrected catalog SHALL be published only for a local date strictly after
the corrective release is deployed and SHALL take effect at that date's
midnight in `America/Bahia`.

#### Scenario: Operator activates corrected catalog

- **WHEN** the corrective release is running and the operator supplies the next
  approved future local date
- **THEN** the existing atomic future-activation command publishes the complete
  corrected catalog
- **AND** no deploy or migration activates it automatically

#### Scenario: Earlier v1 history remains applicable

- **WHEN** a census predates the corrected catalog effective date
- **THEN** it retains the previously applicable catalog and algorithm behavior
- **AND** no backfill or catalog substitution occurs
