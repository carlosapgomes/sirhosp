# release-image-hospital-deploy Specification

## Purpose

Define validated, immutable GitHub release publication and reproducible hospital
deployment from exact GHCR image tags using a standalone Docker Compose file.

## Requirements

### Requirement: Validated tags produce immutable releases and GHCR images

The system SHALL build and publish the Dockerfile `prod` target from an exact
existing Git tag only after the official quality gate succeeds. It SHALL attach
the hospital Compose to a draft and publish that release under GitHub immutable
release protection.

#### Scenario: Stable release is requested

- **WHEN** an operator dispatches the workflow for an exact tag as stable
- **THEN** the workflow resolves and validates the exact tag commit
- **AND** runs `./scripts/test-in-container.sh quality-gate`
- **AND** requires repository immutable releases to be enabled
- **AND** creates a draft containing `compose.hospital.yml`
- **AND** pushes `ghcr.io/carlosapgomes/sirhosp:<release-tag>`
- **AND** updates `ghcr.io/carlosapgomes/sirhosp:latest`
- **AND** does not update the `prerelease` channel
- **AND** publishes and verifies an immutable GitHub release

#### Scenario: Prerelease is requested

- **WHEN** an operator dispatches the workflow for an exact tag as prerelease
- **THEN** the workflow performs the same validation and draft-first sequence
- **AND** pushes `ghcr.io/carlosapgomes/sirhosp:<prerelease-tag>`
- **AND** updates `ghcr.io/carlosapgomes/sirhosp:prerelease`
- **AND** does not update `latest`
- **AND** publishes and verifies an immutable GitHub prerelease

#### Scenario: Validation fails

- **WHEN** the exact tag fails the official quality gate
- **THEN** no draft release is created
- **AND** no image tag is pushed
- **AND** no hospital Compose is attached by that workflow run

#### Scenario: Exact image tag already exists

- **WHEN** the requested exact GHCR image tag already resolves
- **THEN** the workflow stops before creating a draft
- **AND** it does not overwrite the exact image, release or Compose asset
- **AND** the operator must use a new release tag

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

The system SHALL attach `compose.hospital.yml` while the GitHub release or
prerelease is still a draft and SHALL make no asset mutation after publication.

#### Scenario: Operator installs without repository checkout

- **WHEN** the release workflow finishes successfully
- **THEN** the immutable release contains `compose.hospital.yml` as a
  downloadable asset
- **AND** the operator can deploy using that file, a host-local `.env` and Docker
  Compose
- **AND** no Git clone, source bind mount or Docker build is required
- **AND** the release tag and Compose asset cannot be changed after publication

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
