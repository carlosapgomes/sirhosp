# Proposal: Extract Census and Discharge Services

## Why

Daily and historical recovery needs the official census and discharge extraction
flows to be callable from Python without relying on Django management command
control flow. Change 1 established this pattern for admissions and deaths; this
change applies it to the two remaining historical operational reports while
preserving the current operator CLI.

This improves deterministic recovery for quality, operations, and medical record
management by making all four core historical report extractors reusable by the
future `recover_historical_data` orchestrator.

## What Changes

- Introduce Python-callable service entry points for official census extraction
  and discharge report extraction.
- Keep `extract_official_census` and `extract_discharges` as management-command
  wrappers with compatible CLI behavior.
- Reuse the shared historical extraction contract and helpers introduced in
  Change 1 where appropriate.
- Preserve Playwright automation scripts as subprocess boundaries.
- Preserve official census and discharge persistence semantics while adding
  focused tests for deterministic re-execution and empty-output behavior.
- Add `IngestionRun` and stage metric observability coverage for census and
  discharge service executions.
- Create discharge report extraction code outside `apps/discharges/services.py`
  to avoid interfering with the existing discharge reconciliation service.
- Non-goals:
  - Do not create `recover_historical_data` in this change.
  - Do not refactor admissions or deaths beyond using their established pattern
    for reference.
  - Do not introduce Celery, Redis, or new orchestration infrastructure.
  - Do not change the Playwright automation scripts unless a tiny compatibility
    fix is unavoidable and covered by tests.

## Capabilities

### New Capabilities

- `historical-extraction-services`: Extends Python-callable historical report
  extraction services to official census and discharge report extraction.

### Modified Capabilities

- `ingestion-run-observability`: Extends historical extraction run lifecycle and
  stage metric observability requirements to official census and discharge
  service executions.

## Impact

- Affected Django commands:
  - `apps/census/management/commands/extract_official_census.py`
  - `apps/discharges/management/commands/extract_discharges.py`
- Affected service modules:
  - likely new or updated census extraction service code;
  - new discharge extraction service module that is separate from
    `apps/discharges/services.py`.
- Affected models and persistence paths:
  - `OfficialCensusRecord`
  - `DailyDischargeCount`
  - `DischargeRecord`
  - `IngestionRun`
  - `IngestionRunStageMetric`
- No new production dependencies are expected.
- Main risks:
  - accidental drift in CLI behavior;
  - accidental coupling with `apps/discharges/services.py`;
  - credential leakage in persisted failure metadata;
  - differences between official census JSON and discharge XLS output handling.
