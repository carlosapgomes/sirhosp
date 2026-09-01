## ADDED Requirements

### Requirement: Persistent admissions fallback reads recent encounters safely

The persistent-session worker SHALL enrich an empty batch-bound
`admissions_only` capture through action navigation to `Atendimentos` in the
same authenticated Playwright session and SHALL preserve cleanup and lifecycle
safety.

#### Scenario: Real bridge reads encounter table after empty admissions

- **WHEN** action navigation captures an empty admissions snapshot
- **AND** the run is eligible for encounter fallback
- **THEN** the bridge clicks the visible exact `Atendimentos` menu item
- **AND** reads the body `tabela_resultados:resultList_data` inside `frame_pol`
- **AND** returns a minimal normalized flow snapshot to the adapter

#### Scenario: Encounter navigation does not leak job state

- **WHEN** encounter capture completes, fails, cleanup runs, a new job starts,
  the browser restarts, bootstrap runs or shutdown occurs
- **THEN** any in-memory encounter snapshot is discarded
- **AND** no later patient can receive an earlier patient's evidence

#### Scenario: Encounter fallback preserves session lifecycle

- **WHEN** encounter fallback completes successfully
- **THEN** the worker returns to a clean job boundary through the existing tab
  cleanup/controller contract
- **AND** records one processed job rather than an extra job/login

#### Scenario: Encounter action failure is sanitized

- **WHEN** the menu, iframe, table or valid date cannot be obtained within the
  bounded action budget
- **THEN** the worker follows typed failure/retry behavior
- **AND** logs/stages contain no patient, professional, row value, selector,
  URL, HTML, cookie or credential

#### Scenario: Fake sessions remain synthetic

- **WHEN** automated tests exercise the persistent fallback
- **THEN** they use fake DOM/session data
- **AND** no browser, network, subprocess or production record is accessed
