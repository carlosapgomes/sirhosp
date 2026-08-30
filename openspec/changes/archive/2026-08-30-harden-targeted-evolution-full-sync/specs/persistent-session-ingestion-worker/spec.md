## ADDED Requirements

### Requirement: Persistent full-sync honors the selected local admission

The persistent-session worker SHALL restrict `full_sync` and
`full_admission_sync` evolution extraction to the local admission identified by
`admission_id`, using stable period and active/closed facts to resolve its
current legacy row.

#### Scenario: Active target is selected among overlapping admissions

- **WHEN** a targeted run requests a period overlapped by an active local
  admission and an older closed admission
- **THEN** only the legacy row compatible with the target start and active state
  is selected
- **AND** evolutions from the other overlapping admission are not extracted

#### Scenario: Changed legacy key does not defeat stable match

- **WHEN** the local admission's stored source key differs from the current
  legacy row key
- **AND** exactly one row matches the local period and active/closed state
- **THEN** that row is selected
- **AND** the stale key is treated only as a hint, not as canonical identity

#### Scenario: Compatible source key resolves a tie

- **WHEN** more than one legacy row is compatible by period and state
- **AND** exactly one compatible row matches the source-key hint
- **THEN** the hinted compatible row is selected

#### Scenario: Ambiguous or missing target fails closed

- **WHEN** no legacy row or more than one unresolved row matches the target
  period and state
- **THEN** the targeted chunk fails with a sanitized source failure
- **AND** the worker does not fall back to the first row or another admission
- **AND** it does not record coverage for the chunk

#### Scenario: Missing admission id preserves overlapping mode

- **WHEN** a full-sync run has no `admission_id`
- **THEN** the bridge preserves selection of all admissions overlapping the
  requested interval

### Requirement: Evolution action activation is resilient and bounded

The real persistent handle SHALL activate the legacy `Evolução` action through
a bounded primary click and controlled DOM fallback and MUST verify the required
modal postcondition before continuing.

#### Scenario: Normal click opens evolution modal

- **WHEN** the evolution button is visible and the normal Playwright click
  opens the modal within its short action budget
- **THEN** the flow verifies both required date inputs are visible
- **AND** it does not execute the DOM fallback

#### Scenario: Actionability timeout uses controlled fallback

- **WHEN** the visible evolution button does not complete a normal Playwright
  click within its short action budget
- **AND** the evolution modal is not already open
- **THEN** the flow invokes `element.click()` on that validated button
- **AND** it verifies both required date inputs within the remaining shared
  deadline

#### Scenario: Fallback without postcondition fails

- **WHEN** neither click strategy exposes both required date inputs before the
  deadline
- **THEN** the flow raises a typed sanitized navigation failure
- **AND** it does not fill dates, generate a report or treat the chunk as empty

### Requirement: Targeted navigation failures are not empty extraction results

The real persistent handle SHALL distinguish an explicitly empty report from a
failure to navigate or act on the selected admission.

#### Scenario: Source explicitly reports no evolutions

- **WHEN** the selected target and chunk reach the report action
- **AND** the legacy UI explicitly reports no evolutions
- **THEN** the connector returns a successful empty chunk result

#### Scenario: Required target action fails

- **WHEN** target detail opening, evolution activation, date filling, report
  generation, download or parsing fails
- **THEN** the connector propagates a typed sanitized failure
- **AND** it does not return an empty successful result for that chunk

### Requirement: Automatic full-sync follow-up is deferred without being lost

The admissions follow-up path SHALL always enqueue its target `full_sync` in the
current batch and SHALL set its existing `next_retry_at` when the bounded
cross-run guard applies.

#### Scenario: Deferred follow-up remains linked to the batch

- **WHEN** the bounded cross-run guard applies to the most recent admission
- **THEN** admissions processing creates the `full_sync` row with the same batch
- **AND** the row remains queued but ineligible until `next_retry_at`
- **AND** batch closure continues to wait for that follow-up
