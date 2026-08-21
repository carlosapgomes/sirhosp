# versioned-sector-capacity-catalog Specification

## Purpose

TBD - created by archiving change add-versioned-sector-capacity-occupancy-history. Update Purpose after archive.

## Requirements

### Requirement: Capacity catalog versions are complete daily snapshots

The system SHALL persist each capacity catalog version as a complete set of
capacity groups and source-sector memberships effective from one local calendar
date in `America/Bahia`.

#### Scenario: Select catalog for a census date

- **WHEN** more than one catalog version has an effective date on or before the
  local date of a census
- **THEN** the system selects the version with the greatest applicable effective
  date
- **AND** it does not combine groups or members from different versions

#### Scenario: No catalog applies before activation

- **WHEN** a census local date is earlier than the first catalog effective date
- **THEN** the system reports that capacity statistics are pre-activation
- **AND** it does not apply the future catalog to that census

#### Scenario: One configuration governs an entire local day

- **WHEN** multiple censuses are captured on the same local date
- **THEN** every census uses the same applicable catalog version
- **AND** no catalog change takes effect in the middle of that date

### Requirement: Catalog activation is future-dated and controlled

The system SHALL provide an idempotent management command that validates a
complete JSON catalog and activates it only for a future local date.

#### Scenario: Dry-run validates without persistence

- **WHEN** an operator supplies a valid catalog, a future effective date and
  `--dry-run`
- **THEN** the command reports group, member, capacity and policy totals
- **AND** it persists no catalog, group or membership row

#### Scenario: Valid future catalog is activated atomically

- **WHEN** an operator supplies a valid complete catalog with an effective date
  after `timezone.localdate()`
- **THEN** the version, all groups and all memberships are persisted in one
  transaction
- **AND** the stored version includes the input document SHA-256 and source
  reference

#### Scenario: Current or past date is rejected

- **WHEN** the requested effective date is equal to or earlier than the current
  date in `America/Bahia`
- **THEN** the command fails without persisting any catalog data

#### Scenario: Identical activation is idempotent

- **WHEN** a version already exists for the requested date with the same input
  SHA-256
- **THEN** the command returns success without creating duplicates or editing
  the existing version

#### Scenario: Conflicting activation date is rejected

- **WHEN** a version already exists for the requested date with a different
  input SHA-256
- **THEN** the command fails without changing the stored version

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

### Requirement: Published catalog versions remain immutable

The system SHALL preserve every published catalog version and SHALL create a new
future version for changes in name, composition, capacity or identity.

#### Scenario: Future capacity change creates a version

- **WHEN** an official capacity must change
- **THEN** an operator publishes a complete catalog for a future date
- **AND** the previous catalog and its effective date remain unchanged

#### Scenario: Source code is reassigned in the future

- **WHEN** a source code changes to a different official sector identity
- **THEN** the new catalog associates that code with the new stable group key
- **AND** historical catalogs retain the earlier association

### Requirement: Initial catalog represents the approved capacity baseline

The initial catalog SHALL contain the approved 47 current source codes, with 39
capacity-bearing groups covering 44 codes, three unrated codes, known capacity
658 and calculable capacity 626.

#### Scenario: Shared Cardiologia capacity is loaded once

- **WHEN** the initial catalog is validated
- **THEN** codes `719` and `2156` belong to group `ENF-2B-CARD`
- **AND** that group has one capacity of 15

#### Scenario: Shared Centro Obstétrico capacity is loaded once

- **WHEN** the initial catalog is validated
- **THEN** codes `20`, `1110`, `1112`, `1114` and `1116` belong to group `CO`
- **AND** that group has one capacity of 8

#### Scenario: Obstetrícia 3A is capacity-covered but not calculable

- **WHEN** the initial catalog is validated
- **THEN** code `654` belongs to `OBST-3A` with capacity 32
- **AND** its policy is `linked_slots_pending`

#### Scenario: Three current codes remain unrated

- **WHEN** the initial catalog is validated
- **THEN** codes `733`, `1522` and `1002` use the `unrated` policy
- **AND** none declares an official capacity

#### Scenario: Leitos-dia do not enter the baseline

- **WHEN** the initial known capacity is totaled
- **THEN** the 8 CHD Colono and 12 Hospital do Homem leitos-dia are excluded
- **AND** the baseline known capacity remains 658

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
