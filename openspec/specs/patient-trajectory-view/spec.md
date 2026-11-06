# patient-trajectory-view Specification

## Purpose

Defines the chronological patient trajectory section on the admission detail page.

## Requirements

### Requirement: Admission detail page shows patient trajectory

The system SHALL display the patient's sector trajectory on the admission
detail page when `PatientMovement` records exist for that patient during
the admission period, showing the movement time whenever the source census
provided it.

#### Scenario: Trajectory timeline is rendered with movements

- **WHEN** an authenticated user views an admission detail page
- **AND** `PatientMovement` records exist for the patient within the
  admission date range
- **THEN** a visual timeline shows each sector transition with dates

#### Scenario: Trajectory shows days per sector

- **WHEN** the trajectory timeline is rendered
- **THEN** each sector card shows the number of days the patient spent
  in that sector

#### Scenario: Trajectory shows origin for each movement

- **WHEN** a `PatientMovement` has a non-empty `origin` field
- **THEN** the timeline displays the origin sector for that movement

#### Scenario: Trajectory shows discharge as final status

- **WHEN** the last `PatientMovement` has a non-empty `discharge_type`
- **THEN** the timeline displays the discharge type as the final status
  instead of "(ativa)"

#### Scenario: Empty trajectory shows informative message

- **WHEN** an authenticated user views an admission detail page
- **AND** no `PatientMovement` records exist for that patient
- **THEN** an informative message is displayed indicating no trajectory
  data is available yet

#### Scenario: Movement time is shown when available

- **WHEN** the trajectory timeline is rendered
- **AND** a `PatientMovement` has a non-null `source_movement_at`
- **THEN** that entry displays date and time in `DD/MM/AAAA HH:MM` in the
  configured timezone

#### Scenario: Date-only entries degrade gracefully in the same trajectory

- **WHEN** the trajectory timeline is rendered for a patient whose
  movements mix entries with and without `source_movement_at`
- **THEN** entries without a source time display only `DD/MM/AAAA`
- **AND** no placeholder time (such as `00:00`) is displayed for them

#### Scenario: Durations remain date-based despite visible times

- **WHEN** consecutive movements have source times on their shared
  boundary dates
- **THEN** the days-per-sector calculation still uses only movement dates
- **AND** displayed durations are identical to the date-only behavior

### Requirement: Trajectory is ordered chronologically

The system SHALL order `PatientMovement` records by `sequence` field to
present the trajectory in chronological order.

#### Scenario: Movements appear in correct order

- **WHEN** a patient has three movements with sequences 0, 1, 2
  corresponding to PS, Enf, UTI
- **THEN** the timeline renders PS first, then Enf, then UTI
