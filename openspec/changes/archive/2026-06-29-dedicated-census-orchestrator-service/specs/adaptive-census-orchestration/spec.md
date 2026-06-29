# adaptive-census-orchestration Specification Delta

## ADDED Requirements

### Requirement: Production loop runtime is isolated from the web service

The production deployment guidance for the orchestrator loop SHALL prefer a
dedicated runtime service for continuous execution, while preserving manual
`--dry-run` and `--once` execution for diagnostics.

#### Scenario: Continuous loop uses dedicated runtime

- **WHEN** an operator deploys the adaptive census orchestrator in production
  continuous mode
- **THEN** the recommended runtime is the dedicated `census_orchestrator`
  service
- **AND** the loop is not run as a long-lived `docker compose exec -T web`
  process

#### Scenario: Manual diagnostics remain available

- **WHEN** an operator needs to inspect eligibility or run a single controlled
  cycle
- **THEN** the documented commands preserve `run_adaptive_census_cycles
  --dry-run` and `run_adaptive_census_cycles --once`
- **AND** the commands use the dedicated runtime when volatile storage behavior
  is being validated
