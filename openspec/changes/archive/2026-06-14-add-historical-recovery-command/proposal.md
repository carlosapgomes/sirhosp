# Proposal: Add Historical Recovery Command

## Why

Operators need a deterministic way to recover historical daily operational data
for a date or period without relying on a shell script that invokes management
commands one by one. Changes 1 and 2 exposed admissions, deaths, official
census, and discharges as Python-callable services, so the project can now add a
single recovery command that orchestrates those services directly.

This improves recovery reliability for hospital operations, quality, and medical
record management by producing structured per-day/per-extractor results and a
clear final exit status.

## What Changes

- Add a `recover_historical_data` management command that runs the four
  historical extractors for a single date or inclusive date range.
- Call Python service entry points directly instead of using `call_command` or
  subprocessing Django commands.
- Support operator controls such as extractor selection, execution order,
  headless mode, fail-fast mode, and dry-run planning.
- Emit deterministic console output summarizing each day and extractor result.
- Return a non-zero process exit only when at least one selected extraction
  fails, unless dry-run mode is used.
- Keep existing extractor management commands unchanged as supported CLI
  wrappers.
- Keep `scripts/recover-historical-data.sh` as a legacy helper unless an
  implementation slice explicitly replaces or documents it.
- Non-goals:
  - Do not persist historical recovery jobs or attempts in this change.
  - Do not add Celery, Redis, or background orchestration infrastructure.
  - Do not modify Playwright automation scripts.
  - Do not modify `apps/discharges/services.py`.
  - Do not archive prior changes as part of this implementation.

## Capabilities

### New Capabilities

- `historical-recovery-command`: Provides deterministic command-level
  orchestration of historical admissions, deaths, official census, and discharge
  extraction services across a date or date range.

### Modified Capabilities

- `ingestion-run-observability`: Clarifies how a command-level recovery run uses
  the existing per-extractor `IngestionRun` records and failure metadata without
  adding a persistent recovery-job model.

## Impact

- New Django management command, likely under `apps/ingestion/management/commands/`.
- New recovery orchestration service/module, likely under `apps/ingestion/`.
- Direct imports of service entry points from:
  - `apps.admissions.services.run_admission_extraction`
  - `apps.deaths.services.run_death_extraction`
  - `apps.census.services.run_official_census_extraction`
  - `apps.discharges.extraction_service.run_discharge_extraction`
- New unit tests for date planning, extractor selection, result aggregation, dry
  run behavior, failure handling, and CLI compatibility.
- No database migration is expected.
- Main risks:
  - accidental reintroduction of management-command coupling;
  - ambiguous exit semantics when some extractors fail;
  - long-running synchronous execution for wide date ranges;
  - operator confusion if legacy shell script behavior differs from the new
    command.
