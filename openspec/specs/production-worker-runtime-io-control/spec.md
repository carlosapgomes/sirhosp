# production-worker-runtime-io-control Specification

## Purpose

Define production Docker Compose runtime requirements that reduce physical disk
writes from Playwright ingestion workers by moving temporary scraping artifacts,
caches and browser shared-memory behavior to bounded volatile storage.

## Requirements

### Requirement: Worker uses volatile temporary storage

The production ingestion `worker` service SHALL place Python, Playwright and
Chromium temporary files, caches and runtime config in volatile container
storage instead of the Docker overlay whenever Docker Compose supports it.

#### Scenario: Production worker defines tmpfs mounts

- **WHEN** the production Compose configuration is rendered
- **THEN** the `worker` service includes tmpfs mounts for `/tmp`, `/var/tmp`,
  `/home/10001/.cache` and `/home/10001/.config`

#### Scenario: Runtime temp variables point to volatile storage

- **WHEN** the production `worker` container starts
- **THEN** `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` point
  to paths under volatile storage

### Requirement: Worker volatile storage is conservatively bounded

The production ingestion `worker` service SHALL use conservative default limits
for volatile storage and SHALL allow operators to override those limits with
environment variables.

#### Scenario: Default limits support scaled workers

- **WHEN** the production Compose configuration is rendered without override
  variables
- **THEN** the `worker` service uses bounded defaults suitable for up to 15
  workers on a 62 GiB RAM host

#### Scenario: Operator overrides tmpfs limits

- **WHEN** an operator sets documented `WORKER_TMPFS_*` variables
- **THEN** the rendered `worker` service uses those values without editing the
  Compose file

### Requirement: Worker configures browser shared memory

The production ingestion `worker` service SHALL define a parametrizable
`shm_size` for Chromium-based scraping.

#### Scenario: Default shared memory is configured

- **WHEN** the production Compose configuration is rendered without overrides
- **THEN** the `worker` service defines a non-default `shm_size` for browser
  runtime use

#### Scenario: Operator overrides shared memory

- **WHEN** an operator sets `WORKER_SHM_SIZE`
- **THEN** the rendered `worker` service uses that value for `shm_size`

### Requirement: Worker limits Docker log growth

The production ingestion `worker` service SHALL configure Docker log rotation to
avoid unbounded log growth during continuous scraping operation.

#### Scenario: Production worker has log rotation

- **WHEN** the production Compose configuration is rendered
- **THEN** the `worker` service uses the `json-file` logging driver with bounded
  `max-size` and `max-file` options

### Requirement: Operator can validate volatile runtime behavior

The change SHALL provide concise operator guidance for checking tmpfs, shared
memory, block IO, RAM and swap after deploying scaled workers.

#### Scenario: Validation guidance exists

- **WHEN** an implementer finishes the change
- **THEN** the repository includes concise guidance or task output describing
  commands to verify `/tmp`, `/dev/shm`, `docker stats`, RAM and swap

### Requirement: Persistent worker storage is bounded

Production runtime guidance SHALL account for the persistent-session worker's
longer-lived Chromium browser profile, temporary files, and cache behavior. It
MUST also distinguish current non-rollout-ready status from future production
rollout guidance.

#### Scenario: Production rollout prerequisites are documented

- **WHEN** runtime guidance references persistent-session production workers
- **THEN** it states that production rollout is blocked until full-sync
  persistence and the real-handle container contract are resolved
- **AND** current examples are clearly marked as future rollout or lab/staging
  experiment guidance

#### Scenario: Persistent worker uses isolated volatile paths

- **WHEN** an operator deploys persistent-session workers after prerequisites
  are met
- **THEN** each worker process or container uses isolated temp/profile paths
- **AND** those paths are on bounded volatile storage when supported
- **AND** no mutable browser profile is shared by multiple worker processes

#### Scenario: Operator can tune browser lifecycle

- **WHEN** the persistent-session worker is deployed
- **THEN** operators can configure conservative browser/session lifecycle limits
- **AND** documented defaults favor stability over maximum reuse

#### Scenario: Operator can compare IO and memory impact

- **WHEN** current and persistent workers run side-by-side
- **THEN** guidance includes commands or queries to compare temporary storage,
  shared memory, RAM, swap, and Docker log growth for both groups
