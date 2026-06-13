# Proposal: Extract Admission and Death Services

## Why

Daily and historical recovery of operational hospital data needs deterministic,
testable extraction entry points. Today the admission and death extraction flows
are embedded in management commands, which makes reuse by a future recovery
orchestrator fragile because failures are represented through CLI exit behavior
rather than structured Python results.

This change starts the multi-change refactor with the two lowest-risk extractors
so the project can establish a safe pattern before touching official census and
discharges. It improves operational reliability for routine data recovery
without changing the external CLI used by operators.

## What Changes

- Introduce a small shared extraction service contract for historical report
  extractors.
- Add reusable helpers for source-system credentials, `IngestionRun` lifecycle
  updates, stage metrics, subprocess execution, and normalized failure reporting
  where appropriate.
- Refactor `extract_admissions` so its business execution path is available as a
  Python service while preserving the existing management command behavior.
- Refactor `extract_deaths` using the same service pattern while preserving the
  existing management command behavior.
- Make admission/death persistence safer and explicitly tested for idempotent
  re-execution.
- Document the intended follow-up changes:
  - Change 2: apply the service pattern to official census and discharges.
  - Change 3: add `recover_historical_data` for daily and period-based recovery
    orchestration.
  - Possible Change 4: persist historical recovery jobs/attempts if the
    command-level retry state is insufficient for production operations.
- Non-goals:
  - Do not create `recover_historical_data` in this change.
  - Do not refactor official census or discharges in this change.
  - Do not modify `apps/discharges/services.py`; it belongs to an existing
    discharge reconciliation flow and is outside this change.
  - Do not rewrite the Playwright automation scripts.
  - Do not introduce Celery, Redis, or a new worker technology.

## Capabilities

### New Capabilities

- `historical-extraction-services`: Defines structured Python service entry
  points for historical operational extractions, starting with admissions and
  deaths, while keeping CLI commands compatible.

### Modified Capabilities

- `ingestion-run-observability`: Admission/death service executions must
  continue to persist `IngestionRun` lifecycle status, normalized failure
  metadata, and per-stage metrics equivalent to the current command behavior.

## Impact

- Affected code:
  - `apps/admissions/management/commands/extract_admissions.py`
  - `apps/admissions/services.py` or a new admissions extraction service module
  - `apps/deaths/management/commands/extract_deaths.py`
  - `apps/deaths/services.py` or a new deaths extraction service module
  - shared ingestion/extraction helper module under `apps/ingestion/` if needed
  - focused unit/integration tests for service behavior and command
    compatibility
- External CLI compatibility:
  - `python manage.py extract_admissions --date DD/MM/AAAA` must remain valid.
  - `python manage.py extract_deaths --date DD/MM/AAAA` must remain valid.
  - Existing `--start-date` and `--end-date` options for those commands must
    remain valid.
- Operational impact:
  - Operators should see the same command-level behavior, but future
    orchestration can call services directly and inspect structured results.
- Risks:
  - Regression in extraction command behavior if CLI wrappers diverge from
    current semantics.
  - Over-generalizing shared helpers before all four extractors are migrated.
  - Accidental logging of credentials if subprocess command/context is exposed
    incorrectly.
