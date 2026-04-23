# services-portal-navigation Specification

## MODIFIED Requirements

### Requirement: Patient hub with search by name and registry

The system SHALL provide a patient list page with textual filtering by patient name and patient registry (`patient_source_key`).

#### Scenario: Display admissions coverage summary per patient

- **WHEN** authenticated user views `/patients/`
- **THEN** each listed patient includes coverage summary with:
  - known admissions count,
  - admissions with extracted events count,
  - admissions without extracted events count

### Requirement: Hierarchical navigation from patient to admissions and timeline

The system SHALL expose a simple hierarchy for navigation to extracted clinical data.

#### Scenario: Show known admissions even without extracted events

- **WHEN** authenticated user opens `/patients/<patient_id>/admissions/`
- **THEN** all known admissions for the patient are listed
- **AND** admissions with zero extracted events are explicitly marked as `Sem eventos extraídos`
