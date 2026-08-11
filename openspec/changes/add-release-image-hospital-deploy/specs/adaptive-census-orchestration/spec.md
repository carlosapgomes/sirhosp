# adaptive-census-orchestration Delta Specification

## MODIFIED Requirements

### Requirement: Orchestrator executes one safe census cycle

The orchestrator SHALL execute a safe census cycle by running census extraction
and then processing the snapshot produced by that extraction. The one-shot
management command SHALL return a nonzero process status when the cycle fails,
is ambiguous, or produces an unknown outcome.

#### Scenario: Successful single cycle

- **WHEN** the orchestrator is asked to run one cycle
- **AND** the queue is drained
- **AND** the cooldown interval has elapsed
- **THEN** it runs `extract_census`
- **AND** it identifies exactly one new successful `census_extraction` run
- **AND** it runs `process_census_snapshot` with that run id
- **AND** it reports the created batch id and enqueued counts when available
- **AND** the one-shot command returns process status zero

#### Scenario: Extraction fails

- **WHEN** the orchestrator runs one cycle
- **AND** `extract_census` fails
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** the one-shot command reports the failure and returns a nonzero process
  status without enqueuing a new census batch

#### Scenario: Extraction run is ambiguous

- **WHEN** `extract_census` returns successfully
- **AND** the orchestrator cannot identify exactly one new successful
  `census_extraction` run from the cycle
- **THEN** it MUST NOT run `process_census_snapshot`
- **AND** the one-shot command reports the ambiguity and returns a nonzero
  process status

#### Scenario: One-shot cycle is safely blocked

- **WHEN** the one-shot command is blocked by active work or observes that
  another orchestrator holds the coordination lock
- **THEN** it does not start extraction
- **AND** it reports the safe no-work condition
- **AND** it returns process status zero

#### Scenario: One-shot cycle returns an unknown outcome

- **WHEN** the one-shot command receives an outcome outside its known taxonomy
- **THEN** it reports the unexpected outcome
- **AND** it returns a nonzero process status

## ADDED Requirements

### Requirement: Census extractors share the proven authentication bootstrap

The official and current census Playwright extractors SHALL use the same
canonical source-system authentication bootstrap used by the persistent worker.

#### Scenario: Census extractor starts an authenticated session

- **WHEN** either census extractor starts a source-system session
- **THEN** it fills the configured username and password
- **AND** it submits the login by pressing Enter in the password field
- **AND** it waits for `#tempoSessao` to contain at least three numeric parts
  before continuing to census navigation
- **AND** it does not infer authentication failure from the completion status
  of the login button click

#### Scenario: Hospital host has a direct route to the source system

- **WHEN** the hospital host can reach the configured source-system URL directly
- **THEN** census authentication does not require a proxy
- **AND** optional existing proxy behavior remains available when explicitly
  configured

### Requirement: Current census consumes only fresh search results

The current-census extractor SHALL distinguish each newly rendered JSF search
result from the prior sector's result before classifying or exporting it.

#### Scenario: Previous sector displayed an explicit empty result

- **WHEN** the operator selects another sector and triggers `Pesquisar`
- **AND** the prior explicit empty row remains visible while the AJAX response
  is pending
- **THEN** the extractor ignores that stale row
- **AND** it waits for a structurally fresh, settled result table
- **AND** it exports the XLSX when the refreshed table contains patient rows

#### Scenario: Search result does not refresh

- **WHEN** the result table does not become fresh and stable before the timeout
- **THEN** the sector attempt fails
- **AND** the extractor does not classify the stale table as the new result
- **AND** the existing retry and completeness policies remain in force

#### Scenario: Result freshness is observed safely

- **WHEN** the extractor observes the result-table transition
- **THEN** it uses only structural counts, loading state and a non-reversible
  in-browser signature
- **AND** it does not return, log or persist table text, HTML, patient values,
  credentials or cookies as freshness evidence
