# production-exit-reconciliation-runtime Specification

## Purpose

Define the production runtime for exit reconciliation: benchmark-gated hourly current-day discharge extraction, the 05:00 America/Bahia D-1 recovery timer with explicit extractors, bounded catch-up, PostgreSQL coordination locks and identity-safe output.

## Requirements

### Requirement: Current-day discharge extraction is hourly and benchmark-gated

Production SHALL provide a systemd schedule for hourly current-day discharge
extraction, but activation MUST remain blocked until a bounded benchmark shows
that the source and local runtime tolerate the load.

#### Scenario: Benchmark is not approved

- **WHEN** the new runtime is deployed before benchmark approval
- **THEN** hourly extraction is not enabled automatically
- **AND** existing extraction remains available for controlled operation

#### Scenario: Benchmark is approved

- **WHEN** documented source latency, error rate, database duration and queue
  thresholds pass
- **THEN** the operator may enable hourly extraction

#### Scenario: Historical catch-up benchmark is not approved

- **WHEN** D-1 smoke testing passed but the bounded multi-date benchmark did not
  validate up to seven dates across four extractors
- **THEN** automatic scheduling is limited to D-1 only
- **AND** multi-date catch-up requires explicit operator execution

#### Scenario: Hourly extraction succeeds

- **WHEN** the enabled timer fires
- **THEN** it runs the current-day discharge service through the production
  container runtime
- **AND** reconciliation eligible from the report can complete within one hour
  of the record becoming available in the legacy report

### Requirement: Previous-day recovery runs daily at 05:00 local time

Production SHALL use a dedicated systemd timer to execute
`recover_historical_data` for D-1 at 05:00 in `America/Bahia`, explicitly
selecting `discharges`, `admissions`, `deaths` and `official_census`.

#### Scenario: Daily timer fires

- **WHEN** the systemd calendar reaches `05:00:00 America/Bahia` regardless of
  the host default timezone
- **THEN** the runtime requests recovery for the previous local calendar date
- **AND** selects exactly `discharges`, `admissions`, `deaths` and
  `official_census` in canonical order
- **AND** does not expose credentials in arguments, output or logs

#### Scenario: One extractor fails

- **WHEN** one selected extractor remains failed after configured command retries
- **THEN** the systemd service exits nonzero
- **AND** successful extractor steps remain recorded
- **AND** health coverage exposes the failed date and extractor

#### Scenario: PDF command is not scheduled

- **WHEN** the D-1 timer or catch-up runtime executes
- **THEN** it never invokes `process_discharge_pdf`

### Requirement: Missing-date catch-up is limited

The scheduled recovery SHALL identify missing or failed extraction dates and
MUST recover at most seven dates automatically; a larger gap requires explicit
operator approval.

#### Scenario: Seven or fewer dates are missing after benchmark approval

- **WHEN** coverage detects between one and seven eligible missing dates
- **AND** the bounded four-extractor catch-up benchmark is approved
- **THEN** catch-up plans those dates deterministically

#### Scenario: More than seven dates are missing

- **WHEN** coverage detects more than seven missing dates
- **THEN** automatic catch-up stops before extraction
- **AND** reports only aggregate gap count and bounds

### Requirement: Hospital Compose provides an isolated recovery runner

`compose.hospital.yml` SHALL provide a profile-gated, one-shot
`historical_recovery` service that inherits the Playwright runtime, tmpfs,
shared-memory, environment and network contracts without starting during normal
`up`.

#### Scenario: Recovery service is resolved

- **WHEN** the operator runs the profile-gated service with `run --rm`
- **THEN** it uses the exact release image and healthy PostgreSQL dependency
- **AND** provides the same Playwright tmpfs and shared-memory safeguards as the
  active source-automation services

#### Scenario: Normal hospital stack starts

- **WHEN** the operator runs normal Compose `up` without the recovery profile
- **THEN** no historical recovery container starts

#### Scenario: Hourly discharge uses isolated runner

- **WHEN** the scheduled current-day discharge wrapper executes
- **THEN** it uses the same one-shot Playwright-capable runner
- **AND** it does not execute source automation through `web`

### Requirement: Scheduler matches the hospital runtime

Production SHALL use systemd rather than cron for exit-reconciliation schedules
and SHALL execute commands through the deployed hospital Compose contract at
`/srv/apps/prisma` with `.env` and `compose.hospital.yml`, or through an explicit
environment file resolving to those values.

#### Scenario: Units are installed on the hospital server

- **WHEN** an operator validates the versioned service definitions
- **THEN** every Docker Compose command resolves against the hospital runtime
- **AND** no unit assumes that legacy `/opt/sirhosp` files are deployed

#### Scenario: Scheduling mechanisms are inspected

- **WHEN** systemd units, root cron and container commands are inspected
- **THEN** one canonical scheduler owns each periodic responsibility
- **AND** cron contains no duplicate historical recovery or discharge schedule

### Requirement: Scheduled runtimes coordinate through PostgreSQL

Exit extraction, historical recovery and stale-admission safety sweeps MUST use
distinct PostgreSQL advisory locks and SHALL avoid concurrent equivalent work.
Source-running modes SHALL also verify that the ingestion queue is drained and
no census batch is open before launching Playwright.

#### Scenario: Equivalent runtime is active

- **WHEN** a scheduled invocation cannot acquire its coordination lock
- **THEN** it exits safely without starting Playwright or creating duplicate
  reconciliation work

#### Scenario: Ingestion or census work is active

- **WHEN** a source-running timer finds queued/running ingestion work or an open
  census batch
- **THEN** it exits with fixed temporary-busy code `75` before Playwright
- **AND** systemd retries only that outcome every 10 minutes for at most six
  attempts
- **AND** extractor failures retain their normal non-retrying service outcome

#### Scenario: Multiple timers are due

- **WHEN** D-1 recovery, current-day discharge and stale safety are due near the
  same hour
- **THEN** timer offsets and queue/lock guards prevent simultaneous scheduled
  Playwright launches

#### Scenario: Runtime exits unexpectedly

- **WHEN** a process fails or is stopped
- **THEN** PostgreSQL session lock release semantics prevent a permanent lock
- **AND** later timer invocations remain possible

### Requirement: Safety sweep runs hourly

Production SHALL run an hourly bounded stale-admission safety sweep in addition
to post-census detection.

#### Scenario: Safety timer fires

- **WHEN** the hourly safety timer executes
- **THEN** it evaluates eligible cases with the configured cooldowns
- **AND** enqueues no more than 100 confirmations

### Requirement: Runtime output is bounded and identity-safe

Systemd and Docker output SHALL contain aggregate counters, status and safe
failure reasons only; names, record numbers, clinical text, CSV bodies and
credentials MUST NOT be logged.

#### Scenario: Scheduled run reports outcome

- **WHEN** any scheduled runtime succeeds, skips or fails
- **THEN** journal output remains aggregate-safe
- **AND** the administrative dashboard retains protected row-level detail

### Requirement: Runtime artifacts are delivered with the release

The release workflow SHALL attach the versioned scheduler script and systemd
service/timer files with the same immutable release that provides
`compose.hospital.yml` and the upgrade runbook.

#### Scenario: Release is published

- **WHEN** the image and immutable release assets are produced
- **THEN** Compose, runbook, scheduler script and required units are downloadable
  from the exact same tag
- **AND** deployment does not require a repository clone

### Requirement: Operational guidance covers activation and rollback

Deployment documentation SHALL cover the currently unscheduled baseline,
benchmark, systemd installation, manual D-1 smoke test, timer activation, D-1
and catch-up validation, backup, canary batches, monitoring, disabling timers
and rollback without executing production backfill as part of deployment.

#### Scenario: Operator prepares deployment

- **WHEN** the runbook is followed
- **THEN** code deployment, manual service validation and timer activation are
  separate checkpoints
- **AND** the 05:00 historical timer is enabled only after all four extractors
  pass a controlled D-1 smoke test
- **AND** production backfill requires a separate explicit authorization
