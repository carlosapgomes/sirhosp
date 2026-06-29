# production-historical-recovery-runtime Specification

## Purpose
TBD - created by archiving change dedicated-historical-recovery-runtime. Update Purpose after archive.
## Requirements
### Requirement: Historical recovery has a dedicated batch runtime

The production Docker Compose configuration SHALL provide a dedicated
`historical_recovery` service/runtime for manual execution of historical
recovery batches instead of requiring operators to run those batches inside the
portal `web` service.

#### Scenario: Dedicated historical recovery service is defined

- **WHEN** the production Compose configuration is rendered
- **THEN** it includes a `historical_recovery` service
- **AND** that service uses the production application image
- **AND** that service is intended for manual batch execution

#### Scenario: Runtime is explicit and non-mutating by default

- **WHEN** an operator starts normal production services without the recovery
  profile
- **THEN** the `historical_recovery` service is not started
- **AND** the service has a safe default command that does not execute a real
  recovery batch without operator-provided date arguments

#### Scenario: Manual batch command preserves recovery CLI options

- **WHEN** an operator runs `recover_historical_data` through the dedicated
  runtime
- **THEN** the runtime accepts the same command arguments as the existing
  management command, including date ranges, repeatable `--extractor`,
  `--dry-run`, `--fail-fast` and `--max-retries`

### Requirement: Historical recovery uses volatile runtime storage

The production `historical_recovery` service SHALL place Python, Playwright and
Chromium temporary files, caches and runtime config in bounded volatile storage.

#### Scenario: Tmpfs mounts are configured

- **WHEN** the production Compose configuration is rendered
- **THEN** the `historical_recovery` service includes tmpfs mounts for `/tmp`,
  `/var/tmp`, `/home/10001/.cache` and `/home/10001/.config`
- **AND** each tmpfs mount has an explicit size limit

#### Scenario: Runtime environment targets volatile paths

- **WHEN** the production `historical_recovery` container starts
- **THEN** `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` point
  to volatile paths inside the container

### Requirement: Historical recovery volatile storage is parametrizable

The production `historical_recovery` service SHALL use bounded defaults sized
for manual batch scraping and SHALL allow operators to override those limits
without editing the Compose file.

#### Scenario: Default limits are bounded for batch recovery

- **WHEN** the production Compose configuration is rendered without override
  variables
- **THEN** the `historical_recovery` service uses bounded defaults for `/tmp`,
  `/var/tmp`, cache, config and `/dev/shm`
- **AND** the defaults are independent from worker and census orchestrator
  sizing variables

#### Scenario: Operator overrides historical recovery limits

- **WHEN** an operator sets documented `HISTORICAL_RECOVERY_*` sizing variables
- **THEN** the rendered `historical_recovery` service uses those values for
  tmpfs and shared-memory limits

### Requirement: Historical recovery configures browser shared memory

The production `historical_recovery` service SHALL define a parametrizable
`shm_size` suitable for Chromium-based historical extractors.

#### Scenario: Shared memory is configured

- **WHEN** the production Compose configuration is rendered
- **THEN** the `historical_recovery` service defines `shm_size`
- **AND** the value supports an operator override

### Requirement: Historical recovery limits Docker log growth

The production `historical_recovery` service SHALL configure Docker log
rotation to avoid unbounded log growth during long manual batches.

#### Scenario: Historical recovery has bounded logs

- **WHEN** the production Compose configuration is rendered
- **THEN** the `historical_recovery` service uses the `json-file` logging driver
  with bounded `max-size` and `max-file` options

### Requirement: Operator guidance covers manual execution, validation and rollback

The deployment documentation SHALL explain how to operate, validate, monitor and
roll back the dedicated historical recovery runtime without exposing secrets.

#### Scenario: Manual execution guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it includes commands to run `recover_historical_data` through the
  dedicated runtime for a single date and a date range
- **AND** it includes a command showing single-extractor execution with
  `--extractor`
- **AND** it includes a `--dry-run` example

#### Scenario: Validation guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it includes commands to inspect tmpfs, `/dev/shm`, Docker status,
  logs and host disk writes for the historical recovery runtime

#### Scenario: Sizing and troubleshooting guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it lists the `HISTORICAL_RECOVERY_*` sizing variables and defaults
- **AND** it explains what to do for tmpfs `ENOSPC` or Chromium shared-memory
  failures

#### Scenario: Rollback and safety guidance exists

- **WHEN** an operator reads deployment documentation
- **THEN** it explains how to stop using the dedicated runtime and fall back to
  the existing command path for emergency diagnosis
- **AND** it warns operators not to commit rendered Compose output or secrets
- **AND** it warns against running multiple heavy historical recovery batches in
  parallel without an explicit operational decision

