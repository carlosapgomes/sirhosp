# Spec Delta

## ADDED Requirements

### Requirement: Bed lists inside each sector follow natural bed order

The system SHALL order every bed-bearing list inside the sector
collapsibles of `/beds/` by the natural order of the bed identifier, so
numeric segments compare numerically (`2` before `10`, `UTI02` before
`UTI10`) instead of lexicographically. In the occupancy-v5 presentation
each identified patient SHALL be positioned by the first of their beds
in that order, and patients without a reported bed SHALL come last.
Ties SHALL be broken deterministically by normalized name and record.
This ordering SHALL NOT change any count, measurement or official
value, and SHALL be the same natural bed ordering used by the daily
statistics report.

#### Scenario: Beds with unpadded numbers sort naturally

- **WHEN** a sector lists beds `10`, `2`, `UTI10` and `UTI02`
- **THEN** they are presented in the order `2`, `10`, `UTI02`, `UTI10`

#### Scenario: Patient without a bed comes last

- **WHEN** a sector lists identified patients with beds and one patient
  without a reported bed
- **THEN** the patient without a bed is presented after every patient
  with a bed

#### Scenario: Ordering does not change totals

- **WHEN** the bed lists of a sector are presented in natural bed order
- **THEN** every count, capacity and occupancy value of the sector is
  identical to the value presented before the ordering
