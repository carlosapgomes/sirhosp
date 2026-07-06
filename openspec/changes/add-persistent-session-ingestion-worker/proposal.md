# Persistent Session Ingestion Worker Proposal

## Why

The current ingestion worker starts Chrome/Playwright, logs into the legacy
system, opens a legacy tab, processes one `IngestionRun`, and tears everything
down for every job. This adds avoidable latency, CPU/RAM churn, temporary-file
churn, and login fragility during large census batches.

A second worker can eventually run side-by-side with the existing worker to
evaluate persistent browser/session reuse before replacing any current behavior.
After PSW-S5, this is still blocked for production until full-sync persistence
and the real-handle legacy container contract are resolved.

## What Changes

- Add an alternative ingestion worker command that consumes the same PostgreSQL
  `IngestionRun` queue as `process_ingestion_runs`.
- Keep the existing worker behavior unchanged so operators can run both groups
  concurrently, for example six legacy workers and six persistent workers.
- Add a reusable legacy session lifecycle component for login, health checks,
  renewal, relogin fallback, tab cleanup, and browser restart decisions.
- Extract evolution persistence into a shared service so current and persistent
  workers use the same clinical persistence path.
- Reuse the legacy sliding-window behavior that opening/rendering a new legacy
  tab consistently renews the 30-minute session.
- Treat closing the last non-root tab as cleanup only; do not depend on tab
  close events to renew or reset the session counter.
- Handle the 5-minute renewal popup as a defensive fallback, while proactive
  renewal depends on opening a safe legacy tab and verifying the counter reset.
- Resolve the real `PlaywrightSessionHandle` data contract before any
  production rollout, through a dedicated bridge/translation slice.
- Preserve worker identity and heartbeat metadata for operational comparison
  and stale-run recovery.
- Document side-by-side deployment and performance comparison guidance.
- Require all implementation slices to live in isolated Git branch
  `feature/add-persistent-session-ingestion-worker`.

Non-goals:

- Do not remove or rewrite the current worker.
- Do not introduce Celery, Redis, microservices, or a separate queue.
- Do not persist real patient data, screenshots, PDFs, debug HTML, or
  credentials in repository artifacts.
- Do not require production rollout in the first implementation.
- Do not mix this feature branch with unrelated fixes or other OpenSpec
  changes.

## Capabilities

### New Capabilities

- `persistent-session-ingestion-worker`: Alternative worker lifecycle for
  reusing a legacy browser, session, and tab root across multiple queued jobs.

### Modified Capabilities

- `ingestion-run-observability`: Persistent workers must preserve worker label
  and heartbeat guarantees, and support safe grouping for side-by-side metrics.
- `production-worker-runtime-io-control`: Operator guidance must cover volatile
  storage and browser-profile implications for the persistent worker.

## Impact

Affected code areas:

- `apps/ingestion/management/commands/` for the new worker entry point.
- Legacy Playwright connector/session code under `automation/source_system/` or
  a small ingestion automation service module.
- Unit tests for session lifecycle, tab cleanup, session-renewal parsing, queue
  claiming, and restart decisions.
- Integration/command tests for the new command using fakes or mocks.
- Deployment docs for running both worker groups concurrently.

Affected systems:

- Legacy A-GHU/PrimeFaces login and session behavior.
- PostgreSQL-backed ingestion queue and stale-run recovery semantics.
- Docker/runtime temporary storage for Chromium profile and cache files.

Main risks:

- Persistent browser profile/cache growth over long uptime.
- Renewal popup blocking actions if not handled at safe checkpoints.
- Closing the wrong legacy tab if selectors are not defensive.
- Faster persistent workers consuming a disproportionate share of jobs.
