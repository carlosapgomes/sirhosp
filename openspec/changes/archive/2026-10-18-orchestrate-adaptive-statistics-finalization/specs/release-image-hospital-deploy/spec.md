## MODIFIED Requirements

### Requirement: Hospital deployment uses one standalone Compose

The system SHALL provide one Compose file that runs the hospital production
stack from an exact GHCR release image without repository source files or local
image builds. The Compose contract MUST pass the explicitly declared statistics
activation boundary and bounded finalization window to the adaptive census
orchestrator without making them required for inert deployments.

#### Scenario: Operator selects an exact version

- **WHEN** an operator sets `SIRHOSP_VERSION` to a release or prerelease tag
- **AND** runs `docker compose pull`
- **THEN** every Django service resolves to that same GHCR image tag
- **AND** no service has a `build` section

#### Scenario: Required configuration is absent

- **WHEN** a required production secret or `SIRHOSP_VERSION` is absent
- **THEN** Compose interpolation fails before application containers are created
- **AND** the versioned Compose file contains no credential value

#### Scenario: Statistics activation is undeclared

- **WHEN** `STATISTICS_ACTIVATION_DATE` is absent from the host environment
- **THEN** the Compose configuration remains valid
- **AND** the adaptive orchestrator receives an empty fail-closed boundary
- **AND** no statistical date is materialized

#### Scenario: Statistics activation is declared

- **WHEN** a validated activation boundary and bounded lookback are declared
- **THEN** a newly created `census_orchestrator` receives both values explicitly
- **AND** other credentials remain scoped by the existing Compose environment
  contract

#### Scenario: Hospital topology starts

- **WHEN** the operator starts the hospital Compose
- **THEN** PostgreSQL uses a persistent named volume
- **AND** only the web service publishes an application port on the host
- **AND** web, persistent ingestion, census orchestration and summary processing
  use the selected application image
- **AND** every Django service joins the pre-existing external
  `hospital_edge` network
- **AND** web is reachable there through the `prisma` alias while PostgreSQL
  remains restricted to the internal network
- **AND** the topology does not bundle Tailscale or Cloudflared containers

### Requirement: Deployment procedure preserves controlled schema changes

The system SHALL document an operator-controlled sequence for backup, image
pull, migration, preflight, human acceptance, isolated adaptive activation,
verification and rollback.

#### Scenario: Operator deploys a new release

- **WHEN** a new exact release tag is selected
- **THEN** the documented sequence validates Compose configuration
- **AND** creates a PostgreSQL backup before migration
- **AND** runs migration as a one-shot container from the selected image
- **AND** recreates application services without activating statistics
- **AND** preserves the running orchestrator hourly and D-1 cadence evidence
  until the read-only preflight is collected
- **AND** verifies container and HTTP health

#### Scenario: Operator activates adaptive statistics

- **WHEN** the immutable assets are installed, the preflight passes and a human
  explicitly accepts activation
- **THEN** the documented sequence recreates only `census_orchestrator`
- **AND** verifies the configured activation boundary without printing secrets
- **AND** leaves the hourly, D-1 and daily-statistics timers disabled and
  inactive

#### Scenario: Operator returns to an earlier application release

- **WHEN** the operator selects the previous exact tag
- **THEN** the documented sequence pulls and recreates that exact image
- **AND** warns that an incompatible schema downgrade requires coordinated
  database restoration rather than an automatic reverse migration
- **AND** preserves already materialized statistics unless a separately
  authorized database restore is required
