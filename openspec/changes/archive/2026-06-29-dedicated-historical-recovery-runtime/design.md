# Design: dedicated-historical-recovery-runtime

## Context

Historical recovery is an operator-triggered batch workflow implemented by the
existing `recover_historical_data` Django management command. The command plans
single-date or inclusive date-range recovery and can run one or more extractors:
`discharges`, `admissions`, `deaths` and `official_census`. Each extractor uses
Playwright/Chromium-based source-system automation and persists durable results
through the existing Django/PostgreSQL domain models.

Production already has tmpfs-backed runtimes for continuous ingestion workers
and the adaptive census orchestrator. Historical recovery still needs an
operator-friendly runtime that isolates browser temporary files and caches from
the portal `web` service without changing the command's behavior.

## Goals / Non-Goals

**Goals:**

- Provide a dedicated production Docker Compose service/runtime named
  `historical_recovery` for manual batch execution.
- Keep the runtime behind an explicit Compose profile so it is not started by
  normal `up -d` operations.
- Use bounded tmpfs mounts for `/tmp`, `/var/tmp`, browser cache and browser
  config, plus parametrizable `/dev/shm` for Chromium.
- Preserve all existing `recover_historical_data` CLI options, including
  single-extractor and multiple-extractor selection.
- Document operator workflows, validation, sizing, monitoring, rollback and
  secret-safety guidance.
- Keep the implementation small enough for vertical slices with TDD and focused
  text/Compose characterization tests.

**Non-Goals:**

- Do not modify historical recovery Python orchestration, extraction services,
  scraping selectors, parsers or persistence logic.
- Do not introduce Celery, Redis, queues, schedulers or microservices.
- Do not create a long-running daemon or timer for historical recovery.
- Do not change database schema or clinical domain semantics.
- Do not add new runtime dependencies or YAML abstraction layers.

## Decisions

### Decision 1: Batch-only Compose service, not a daemon

`historical_recovery` will be a Compose service used with `docker compose run
--rm`. It will not be managed by a new long-running systemd service and will not
loop.

Rationale: historical recovery is parameterized by date range and extractor
selection. A daemon would need a job queue or scheduler, which is outside phase
1 and unnecessary for manual recovery.

Alternative considered: systemd oneshot wrapper. Deferred because Compose `run
--rm` is enough for the current operator workflow and avoids another unit file.

### Decision 2: Explicit profile and safe default command

The service will use a dedicated profile, for example `profiles: ["recovery"]`,
so routine production startup does not launch it. The default command should be
safe and non-mutating, such as printing `recover_historical_data --help`; actual
recoveries will pass the full command through `docker compose run --rm`.

Rationale: this prevents accidental mutation if someone starts the profile with
`up`, while preserving an explicit runtime for manual batches.

Alternative considered: make the service command a hard-coded date. Rejected
because it would be unsafe and would not preserve the command's flexible CLI.

### Decision 3: Larger, independent tmpfs defaults than the census orchestrator

Historical recovery can execute multiple extractors and date ranges in one
batch, so it should use its own sizing variables and slightly larger defaults:

- `HISTORICAL_RECOVERY_SHM_SIZE`, default `1g`;
- `HISTORICAL_RECOVERY_TMPFS_TMP_SIZE`, default `2g`;
- `HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE`, default `256m`;
- `HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE`, default `512m`;
- `HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE`, default `128m`.

Rationale: this avoids coupling recovery sizing to `WORKER_*` or
`CENSUS_ORCHESTRATOR_*` and reflects heavier batch workloads.

Alternative considered: reuse worker variables. Rejected because recovery and
continuous workers have different operational profiles and should be tuned
independently.

### Decision 4: Preserve source-system access equivalent to scraping runtimes

The service will use the production image target, source-system credentials,
PostgreSQL environment, `PLAYWRIGHT_PROXY_SERVER`, `depends_on: db` and the
`hospital_edge` network, matching existing scraping-capable services.

Rationale: historical extractors need the same database and source-system
connectivity as the portal/worker/orchestrator, but should not run inside those
containers.

### Decision 5: No Python changes unless tests prove an existing bug

Implementation should be limited to runtime wiring, documentation and focused
tests. The existing command already supports `--extractor`, `--dry-run`, retries
and date ranges.

Rationale: changing Python would increase risk without improving the runtime
isolation goal.

## Risks / Trade-offs

- **tmpfs too small for large batches** -> document `ENOSPC` symptoms,
  recommend smaller date windows or raising `HISTORICAL_RECOVERY_TMPFS_*`
  overrides.
- **tmpfs consumes host RAM** -> keep defaults bounded, document `free -h`,
  `docker stats` and avoiding concurrent recovery runs.
- **operator leaks secrets via `docker compose config`** -> document synthetic
  environment usage and prohibit committing rendered config output.
- **parallel recoveries overload the source system or contend on tmpfs** ->
  document that recovery should be run one batch at a time unless an explicit
  operational decision is made.
- **Compose service accidentally started with `up`** -> use an explicit profile
  and a non-mutating default help command.

## Migration Plan

1. Add focused tests that characterize the expected `historical_recovery`
   Compose service and verify it is batch/profile based.
2. Add the service to `compose.prod.yml` with runtime isolation, bounded tmpfs,
   `/dev/shm`, logs and source-system connectivity.
3. Validate Compose rendering with synthetic secrets and inspect only the
   `historical_recovery` section.
4. Add deploy documentation and documentation tests covering usage, extractor
   selection, validation, monitoring, sizing and rollback.
5. Operators can start using the dedicated runtime for future manual batches;
   no data migration is required.

Rollback is operational: stop using the dedicated runtime and run the existing
command through `web` for emergency fallback while the runtime configuration is
fixed. Since durable data remains in PostgreSQL and the command semantics do
not change, no database rollback is needed.

## Open Questions

- None for the initial implementation. Future work may decide whether a
  higher-level wrapper script is useful, but this change intentionally avoids it
  until operator pain justifies the extra surface area.
