# release-image-hospital-deploy Specification

## ADDED Requirements

### Requirement: Published releases produce validated GHCR images

The system SHALL build and publish the Dockerfile `prod` target from the exact
release tag only after the official quality gate succeeds.

#### Scenario: Stable release is published

- **WHEN** a non-prerelease GitHub release is published
- **THEN** the workflow checks out the release tag
- **AND** runs `./scripts/test-in-container.sh quality-gate`
- **AND** pushes `ghcr.io/carlosapgomes/sirhosp:<release-tag>`
- **AND** updates `ghcr.io/carlosapgomes/sirhosp:latest`
- **AND** does not update the `prerelease` channel

#### Scenario: Prerelease is published

- **WHEN** a GitHub prerelease is published
- **THEN** the workflow checks out the prerelease tag
- **AND** runs the same official quality gate
- **AND** pushes `ghcr.io/carlosapgomes/sirhosp:<prerelease-tag>`
- **AND** updates `ghcr.io/carlosapgomes/sirhosp:prerelease`
- **AND** does not update `latest`

#### Scenario: Validation fails

- **WHEN** the release tag fails the official quality gate
- **THEN** no image tag is pushed
- **AND** no hospital Compose is attached by that workflow run

### Requirement: Hospital deployment uses one standalone Compose

The system SHALL provide one Compose file that runs the hospital production
stack from an exact GHCR release image without repository source files or local
image builds.

#### Scenario: Operator selects an exact version

- **WHEN** the operator sets `SIRHOSP_VERSION` to a release or prerelease tag
- **AND** runs `docker compose pull`
- **THEN** every Django service resolves to that same GHCR image tag
- **AND** no service has a `build` section

#### Scenario: Required configuration is absent

- **WHEN** a required production secret or `SIRHOSP_VERSION` is absent
- **THEN** Compose interpolation fails before application containers are created
- **AND** the versioned Compose file contains no credential value

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

### Requirement: Each release distributes its matching Compose

The system SHALL attach `compose.hospital.yml` to each successfully built GitHub
release or prerelease.

#### Scenario: Operator installs without repository checkout

- **WHEN** the release workflow finishes successfully
- **THEN** the release contains `compose.hospital.yml` as a downloadable asset
- **AND** the operator can deploy using that file, a host-local `.env` and Docker
  Compose
- **AND** no Git clone, source bind mount or Docker build is required

### Requirement: Deployment procedure preserves controlled schema changes

The system SHALL document an operator-controlled sequence for backup, image
pull, migration, activation, verification and rollback.

#### Scenario: Operator deploys a new release

- **WHEN** a new exact release tag is selected
- **THEN** the documented sequence validates Compose configuration
- **AND** creates a PostgreSQL backup before migration
- **AND** runs migration as a one-shot container from the selected image
- **AND** recreates services from the selected image
- **AND** verifies container and HTTP health

#### Scenario: Operator returns to an earlier application release

- **WHEN** the operator selects the previous exact tag
- **THEN** the documented sequence pulls and recreates that exact image
- **AND** warns that an incompatible schema downgrade requires coordinated
  database restoration rather than an automatic reverse migration
