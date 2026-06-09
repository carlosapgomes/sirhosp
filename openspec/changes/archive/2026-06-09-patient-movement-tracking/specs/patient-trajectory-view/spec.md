# patient-trajectory-view Specification

## ADDED Requirements

### Requirement: Admission detail page shows patient trajectory

The system SHALL display the patient's sector trajectory on the admission
detail page when `PatientMovement` records exist for that patient during
the admission period.

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

### Requirement: Trajectory is ordered chronologically

The system SHALL order `PatientMovement` records by `sequence` field to
present the trajectory in chronological order.

#### Scenario: Movements appear in correct order

- **WHEN** a patient has three movements with sequences 0, 1, 2
  corresponding to PS, Enf, UTI
- **THEN** the timeline renders PS first, then Enf, then UTI
