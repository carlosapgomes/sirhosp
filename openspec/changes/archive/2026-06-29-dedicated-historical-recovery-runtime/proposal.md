# Proposal: dedicated-historical-recovery-runtime

## Why

The `recover_historical_data` command runs Playwright/Chromium-based historical
scraping for discharges, admissions, deaths and official census. Today operators
run it through the general application runtime, which can write browser caches,
downloads and temporary files to the Docker overlay/NVMe and can couple heavy
manual recovery work to the portal runtime.

This change gives operators a dedicated, batch-only production runtime with
bounded tmpfs and browser shared memory, preserving clinical persistence in
PostgreSQL while reducing avoidable disk writes during historical recovery.

## What Changes

- Add a dedicated production Compose service/runtime for manual historical
  recovery batches, named `historical_recovery`.
- Keep `recover_historical_data` command semantics unchanged, including
  `--date`, `--start-date`, `--end-date`, repeatable `--extractor`, `--dry-run`,
  `--fail-fast` and `--max-retries`.
- Configure the runtime with tmpfs-backed temporary/cache/config paths,
  parametrizable `/dev/shm`, source-system connectivity and bounded Docker logs.
- Document the operator workflow for one-off and range recovery using the
  dedicated runtime, including single-extractor execution, validation,
  monitoring, sizing, rollback and secret-safety guidance.
- Do not introduce Celery, Redis, new microservices or changes to the Python
  historical recovery orchestration logic.

## Capabilities

### New Capabilities

- `production-historical-recovery-runtime`: production batch runtime for manual
  historical recovery with bounded volatile storage and operator guidance.

### Modified Capabilities

- `historical-recovery-command`: clarify that production operation can run the
  existing command through a dedicated batch runtime without changing command
  behavior.

## Impact

- Affected files during implementation are expected to be limited to
  `compose.prod.yml`, deploy documentation, focused unit tests, and this
  OpenSpec change's task tracking.
- No database schema changes, no scraping selector changes and no changes to
  existing historical extraction service contracts are planned.
- Main operational risk is tmpfs sizing: insufficient RAM-backed storage can
  cause `ENOSPC` during large date ranges. The change mitigates this with
  conservative defaults, documented overrides and explicit validation commands.
