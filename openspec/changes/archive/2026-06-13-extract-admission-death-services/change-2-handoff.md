# Change 2 Handoff: `extract-census-discharge-services`

## Context

Change 1 (`extract-admission-death-services`) successfully established the
service-entry-point pattern for admissions and deaths historical extraction.
This handoff documents implementation details that differ from the original
design roadmap and provides guidance for applying the same pattern to official
census and discharges.

## What was proven in Change 1

### Working pattern

1. **Service entry point** (`run_admission_extraction` / `run_death_extraction`)
   owns the full orchestration: credential resolution, date validation,
   `IngestionRun` creation, subprocess execution, JSON parsing, persistence,
   stage metrics, and structured result return.

2. **Thin CLI wrapper**: management commands handle only argument parsing,
   user-facing messages, and `sys.exit(1)` on failure. All logic is delegated
   to the service.

3. **Structured result**: `ExtractionResult` dataclass provides success/failure
   metadata with normalized failure reasons (`validation_error`, `timeout`,
   `source_unavailable`, `unexpected_exception`).

4. **Shared helpers** in `apps/ingestion/historical_extraction.py`:
   - `resolve_source_credentials()` — credential resolution
   - `create_stage_metric()` — `IngestionRunStageMetric` creation
   - `mark_run_succeeded()` / `mark_run_failed()` — run lifecycle
   - `safe_error_message()` — safe error truncation

5. **Idempotent persistence**: admissions and deaths both use
   `update_or_create` for daily counts with
   `daily_count.records.all().delete()` and recreate, all wrapped in
   `transaction.atomic()`.

6. **Argument compatibility**: `--date`, `--start-date`, `--end-date` arguments
   preserved via the thin CLI wrapper.

## Deviations from original design

- The persistence hardening (idempotent delete/recreate) was done in dedicated
  slices S4 (admissions) and S6 (deaths), not as one combined slice.
- The shared helpers in `historical_extraction.py` grew incrementally across
  S1 and S2, with no need for further extraction-specific abstractions.

## Recommendations for Change 2

### 1. Official census (`extract_official_census`)

- Follow the same pattern as admissions/deaths.
- The census persistence uses delete/recreate (see
  `apps/census/management/commands/extract_official_census.py` for current
  behavior).
- Wrap the delete/recreate in `transaction.atomic()` as done for admissions
  and deaths.
- Handle empty/or-missing source file: the service should return success with
  metrics indicating zero records, not fail.

### 2. Discharges (`extract_discharges`)

- **Critical constraint**: Do NOT modify `apps/discharges/services.py`. It
  belongs to the existing discharge reconciliation flow.
- Extract XLS parsing, `DailyDischargeCount` persistence, and `DischargeRecord`
  persistence into a **new module** (e.g. `apps/discharges/extraction.py` or
  `apps/discharges/historical_extraction.py`).
- The management command in
  `apps/discharges/management/commands/extract_discharges.py` should become a
  thin wrapper delegating to the new service.
- Handle empty/missing XLS files gracefully (return success with zero count).

### 3. Service contract

- Both new services should return `ExtractionResult` and use the same shared
  helpers from `apps/ingestion/historical_extraction.py`.
- Test structure to replicate:
  - Characterization tests with mocked subprocess/file I/O
  - Persistence hardening tests (idempotency, empty output, transaction safety)
  - Command argument compatibility tests
  - IngestionRun observability tests (stage metrics, failure metadata)

### 4. Non-goals (still)

- `recover_historical_data` is NOT in scope for Change 2.
- Do not introduce Celery or Redis.
- Do not replace subprocess-based Playwright scripts.

## Files to touch (estimated)

- `apps/census/management/commands/extract_official_census.py` → thin wrapper
- `apps/census/services.py` or new census extraction service
- `apps/discharges/management/commands/extract_discharges.py` → thin wrapper
- `apps/discharges/<new_module>.py` — extraction service (not services.py)
- `tests/unit/test_census_extraction_service.py`
- `tests/unit/test_discharge_extraction_service.py`
- `tests/unit/test_census_persistence_hardening.py`
- `tests/unit/test_discharge_persistence_hardening.py`
- `tests/unit/test_command_argument_compatibility.py` — extend
  with census/discharge args
