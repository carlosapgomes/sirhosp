# production-census-orchestrator-runtime Specification

## ADDED Requirements

### Requirement: Production orchestrator has a dedicated service

The production Docker Compose configuration SHALL provide a dedicated service
for the adaptive census orchestrator loop instead of requiring the loop to run
inside the `web` service.

#### Scenario: Dedicated service is defined

- **WHEN** the production Compose configuration is rendered
- **THEN** it includes a `census_orchestrator` service
- **AND** that service runs `run_adaptive_census_cycles --loop`
- **AND** the service uses the production application image

#### Scenario: Web service remains portal-focused

- **WHEN** an operator inspects the production Compose configuration
- **THEN** the long-running census orchestrator command is not configured as the
  `web` service command
- **AND** the recommended continuous runtime is the dedicated orchestrator
  service

### Requirement: Orchestrator uses volatile runtime storage

The production `census_orchestrator` service SHALL place Python, Playwright and
Chromium temporary files, caches and runtime config in bounded volatile storage.

#### Scenario: Tmpfs mounts are configured

- **WHEN** the production Compose configuration is rendered
- **THEN** the `census_orchestrator` service includes tmpfs mounts for `/tmp`,
  `/var/tmp`, `/home/10001/.cache` and `/home/10001/.config`
- **AND** each tmpfs mount has an explicit size limit

#### Scenario: Runtime environment targets volatile paths

- **WHEN** the production `census_orchestrator` container starts
- **THEN** `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` point
  to volatile paths inside the container

### Requirement: Orchestrator volatile storage is parametrizable

The production `census_orchestrator` service SHALL use conservative default
limits and SHALL allow operators to override those limits without editing the
Compose file.

#### Scenario: Default limits are conservative

- **WHEN** the production Compose configuration is rendered without override
  variables
- **THEN** the `census_orchestrator` service uses bounded defaults for `/tmp`,
  `/var/tmp`, cache, config and `/dev/shm`

#### Scenario: Operator overrides orchestrator limits

- **WHEN** an operator sets documented `CENSUS_ORCHESTRATOR_*` sizing variables
- **THEN** the rendered `census_orchestrator` service uses those values for
  tmpfs and shared-memory limits

### Requirement: Orchestrator configures browser shared memory

The production `census_orchestrator` service SHALL define a parametrizable
`shm_size` suitable for Chromium-based census extraction.

#### Scenario: Shared memory is configured

- **WHEN** the production Compose configuration is rendered
- **THEN** the `census_orchestrator` service defines `shm_size`
- **AND** the value supports an operator override

### Requirement: Orchestrator limits Docker log growth

The production `census_orchestrator` service SHALL configure Docker log
rotation to avoid unbounded log growth during continuous operation.

#### Scenario: Orchestrator has bounded logs

- **WHEN** the production Compose configuration is rendered
- **THEN** the `census_orchestrator` service uses the `json-file` logging driver
  with bounded `max-size` and `max-file` options

### Requirement: Systemd targets the dedicated service

The production systemd unit for the census orchestrator SHALL manage the
dedicated Compose service and SHALL NOT execute the loop inside the `web`
container.

#### Scenario: Unit starts dedicated service

- **WHEN** an operator installs `sirhosp-census-orchestrator.service`
- **THEN** `ExecStart` starts the `census_orchestrator` Compose service
- **AND** it does not call `docker compose exec -T web`

#### Scenario: Unit stops dedicated service

- **WHEN** systemd stops `sirhosp-census-orchestrator.service`
- **THEN** the unit stops the `census_orchestrator` Compose service

### Requirement: Operator guidance covers validation and rollback

The deployment documentation SHALL explain how to operate, validate and roll
back the dedicated orchestrator runtime without exposing secrets.

#### Scenario: Validation guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it includes commands to inspect tmpfs, `/dev/shm`, Docker status,
  logs and host disk writes for the orchestrator

#### Scenario: Rollback guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it explains how to stop or disable the dedicated orchestrator service
- **AND** it warns against running the old `web` loop and the dedicated service
  at the same time
