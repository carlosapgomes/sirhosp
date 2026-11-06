# census-snapshot-processing Delta

## ADDED Requirements

### Requirement: Census snapshots retain optional source temporal precision

For each newly captured census row, the system SHALL retain admission and
movement timestamps when supplied by the source, separately from the existing
date-only values. Timestamps without a source offset SHALL use the configured
hospital local timezone. Absent source precision MUST remain absent.

#### Scenario: Source provides both timestamps

- **WHEN** a new row supplies valid admission and movement timestamps
- **THEN** the snapshot retains both as source timestamps
- **AND** the existing date fields receive their local calendar-date
  projections in the established date-only formats
- **AND** the timestamps are not replaced by capture or processing time

#### Scenario: Historical or legacy data has dates only

- **WHEN** a historical snapshot or legacy CSV contains a date without an hour
- **THEN** its existing date-only processing remains supported
- **AND** its optional source timestamp remains null
- **AND** no historical hour is inferred or backfilled

#### Scenario: Admission is absent on a row without a patient

- **WHEN** a row has no patient record and its admission date is empty
- **THEN** its admission source timestamp remains null
- **AND** any movement timestamp remains a property of that snapshot row
- **AND** no identified patient or admission is created for the bed label

#### Scenario: A supplied full timestamp is invalid

- **WHEN** a newly delivered full timestamp has an invalid date or time
- **THEN** the extraction is rejected before partial snapshot persistence
- **AND** the diagnostic does not include the raw timestamp or patient data

### Requirement: Added precision does not redefine clinical state

The system SHALL preserve existing bed classification, age normalization,
admission identity, movement date and deduplication, occupancy, absence
tracking and run-scoped processing when consuming timestamp-enriched census
rows. This change MUST NOT introduce hour-based trajectory rendering or
duration calculations.

#### Scenario: Equivalent date-only and timestamp-enriched rows are processed

- **WHEN** otherwise equivalent rows supply either a date or that date with
  a source hour
- **THEN** their existing clinical and occupancy effects remain equivalent
- **AND** only the optional snapshot precision differs

#### Scenario: Existing movement already exists for the same calendar day

- **WHEN** a timestamp-enriched observation has the same patient, local
  movement date and sector as an existing movement
- **THEN** the existing movement identity and update behavior are preserved
- **AND** a new identity is not inferred solely from the added source hour

#### Scenario: Operational UI consumes the new snapshot

- **WHEN** existing census or trajectory screens display newly captured data
- **THEN** their existing date-only presentation and day-count semantics remain
  unchanged
- **AND** this change does not claim to deliver hours in the Trajetória UI

#### Scenario: Incomplete extraction is rejected

- **WHEN** the extraction completeness contract rejects timestamp-enriched
  input
- **THEN** no new snapshot precision or downstream clinical effect is persisted
- **AND** existing rejection and provenance guarantees remain in force
