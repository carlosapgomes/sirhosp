# adaptive-census-orchestration Specification

## MODIFIED Requirements

### Requirement: Orchestrator reports stale active runs without mutating them

The orchestrator SHALL report stale active runs in dry-run and disabled-recovery
modes, and SHALL delegate automatic stale-run mutation to the configured stale
recovery service before deciding whether the queue is drained in loop mode.

#### Scenario: Stale running run exists and recovery is disabled

- **WHEN** at least one `IngestionRun` has status `running`
- **AND** its processing start or queue time is older than the configured stale
  threshold
- **AND** stale recovery is disabled for the orchestrator execution
- **THEN** the orchestrator reports a stale active run warning
- **AND** it does not mark the run as failed
- **AND** it does not start a new census cycle

#### Scenario: Active run is slow but not stale

- **WHEN** a run is still active but newer than the stale threshold
- **THEN** the orchestrator reports normal waiting state
- **AND** it does not classify the run as stale

#### Scenario: Loop invokes stale recovery before eligibility check

- **WHEN** the orchestrator runs in continuous loop mode
- **AND** stale recovery is enabled
- **THEN** it invokes stale-run recovery before computing whether a new census
  cycle can start
- **AND** it uses the updated run and batch state for the eligibility decision

#### Scenario: Recovery frees the queue for a new cycle

- **WHEN** stale recovery marks abandoned runs as failed
- **AND** affected batches are closed because no queued or running runs remain
- **AND** cooldown and other eligibility criteria are satisfied
- **THEN** the orchestrator may start the next census cycle in the same loop
  execution flow

#### Scenario: Recovery circuit breaker blocks automatic mutation

- **WHEN** stale recovery reports that its circuit breaker prevented mutation
- **THEN** the orchestrator does not start a new census cycle
- **AND** it logs the recovery blocker as the reason for waiting
