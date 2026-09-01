## ADDED Requirements

### Requirement: Patients failure tab shows current flow findings

The ingestion metrics patients tab SHALL display, for each patient in the
"final failure" list, the patient's current patient-flow finding label when
one exists, using the shared bulk classifier without new patient data.

#### Scenario: Failure row displays current finding label

- **WHEN** the latest finished census batch has a final failure for a patient
  who currently has a patient-flow finding
- **THEN** the patients tab row displays that finding's label with the same
  accessible badge treatment used by the census surfaces
- **AND** review-required findings keep the manual-review warning treatment

#### Scenario: No finding renders no placeholder

- **WHEN** a listed failure patient has no current finding — including when the
  patient is no longer in the current census
- **THEN** the row renders an empty situation cell without error or placeholder
  text

#### Scenario: Classification is bulk and bounded

- **WHEN** the patients tab renders with many failure patients
- **THEN** current findings are resolved with the shared bulk classifier in a
  bounded number of queries independent of the row count
- **AND** no query is performed from the template loop

#### Scenario: Authorization and data minimization are preserved

- **WHEN** an anonymous user requests the ingestion metrics page
- **THEN** the existing login redirection is preserved
- **AND** the tab exposes only the closed finding label — no new identifier,
  date, clinical text or stage detail beyond what the table already shows
