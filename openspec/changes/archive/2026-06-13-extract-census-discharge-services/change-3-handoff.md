# Change 3 Handoff — `add-historical-recovery-command`

## Service entry points

### `run_official_census_extraction`

```python
from apps.census.services import run_official_census_extraction

result: ExtractionResult = run_official_census_extraction(
    date="DD/MM/AAAA",
    headless=True,  # or False for headed Playwright
)
```

- **Module:** `apps/census/services.py`
- **Intent value used:** `"official_census_extraction"`
- **Persistence:** Replaces all `OfficialCensusRecord` rows for the target date
  with the latest extraction output. Zero records is a valid successful outcome
  (deletes stale rows).
- **Output format:** JSON from Playwright subprocess (`censo-oficial-<safe-date>-*.json`);
  parsed and stored as `OfficialCensusRecord` rows.
- **Idempotent:** Yes — repeated calls for the same date produce the same
  persisted state.
- **Run lifecycle:** Creates an `IngestionRun` with stages `extract_official_census`
  and `persist_official_census`.

### `run_discharge_extraction`

```python
from apps.discharges.extraction_service import run_discharge_extraction

result: ExtractionResult = run_discharge_extraction(
    date="DD/MM/AAAA",
    headless=True,
)
```

- **Module:** `apps/discharges/extraction_service.py`
- **Intent value used:** `"discharge_extraction"`
- **Persistence:** Upserts `DischargeRecord` rows by business key and
  updates/creates `DailyDischargeCount` for the reference date. Zero parseable
  rows persists a zero-count result.
- **Output format:** XLSX from Playwright subprocess (`altas-<safe-date>-*.xlsx`);
  parsed into `DischargeRecord` and `DailyDischargeCount`.
- **Idempotent:** Yes — repeated calls for the same date produce the same
  persisted state (same business keys overwrite).
- **Run lifecycle:** Creates an `IngestionRun` with stages `extract_discharges`
  and `persist_discharges`.
- **Boundary:** This module is separate from `apps/discharges/services.py` (the
  discharge reconciliation flow). Do not import from that module here.

## Shared contract

Both services use [`ExtractionResult`](../../apps/ingestion/historical_extraction.py)
from `apps.ingestion.historical_extraction`:

```python
@dataclass
class ExtractionResult:
    extraction_type: str
    target_start: date
    target_end: date
    success: bool
    metrics: dict[str, Any]       # e.g. {"total_records": 42}
    failure_reason: str           # normalized: "timeout", "validation_error", etc.
    error_message: str            # safe, no credentials
    ingestion_run_id: int | None  # PK of the IngestionRun if one was created
```

Both services also reuse:
- `resolve_source_credentials()` — validates env vars before subprocess
- `safe_error_message()` — strips credentials from metadata
- `create_stage_metric()` — records per-stage observability
- `mark_run_succeeded()` / `mark_run_failed()` — finalizes run lifecycle

## Common failure paths

- **`validation_error`** (invalid date / missing credentials):
  returns immediately, no run created
- **`timeout`**: `IngestionRun.timed_out=True`, safe message
- **`source_unavailable`**: bounded stderr, safe metadata
- **`unexpected_error`**: run marked failed, structured result

## Known validation caveats

### Pre-existing unrelated test failure

```text
tests/unit/test_report_suspected_stale_inpatients_command.py
  ::test_reports_only_active_admissions_without_events_in_last_72h
```

This test was already failing before Change 2 and is unrelated to census or
discharge extraction services. Likely a pre-existing logic issue in the stale
inpatient detection command.

### Pre-existing unrelated lint errors

- `apps/services_portal/urls.py:23` — line length (101 > 100)
- `[...]test_services_portal_ingestion_metrics_failures_tab.py:112`
  — unused variable
- `[...]test_report_suspected_stale_inpatients_command.py:153`
  — unused variable

All pre-existing, none in code modified by Change 2.

### Pre-existing type-check error

```text
tests/unit/test_services_portal_sectors.py:
  Source file found twice under different module names
```

Pre-existing mypy module resolution issue, not related to Change 2.

### Known design constraint

The current `scripts/test-in-container.sh unit` runs the **entire** unit suite
(1195+ tests) and does not accept narrowed paths. The design explicitly notes
that focused container validation may require running all unit tests or using
a host-only diagnostic command.

## Files to consider for Change 3

### Import directly

- `apps/census/services.py` — provides `run_official_census_extraction`
- `apps/discharges/extraction_service.py` — provides `run_discharge_extraction`
- `apps/ingestion/historical_extraction.py` — provides `ExtractionResult` and
  shared helpers

### Invoke as Python-callable (do not call management commands)

Both services are designed to be called directly from Python — no need to
parse stdout or catch `sys.exit(1)`:

```python
census_result = run_official_census_extraction(date="01/01/2026")
if not census_result.success:
    handle_failure(census_result)

discharge_result = run_discharge_extraction(date="01/01/2026")
```

### Reference for patterns

- `apps/admissions/services.py` — `run_admission_extraction`
  (established in Change 1)
- `apps/deaths/services.py` — `run_death_extraction`
  (established in Change 1)
- All four service entry points follow the same `ExtractionResult` contract.

## Out of scope for Change 3

- Do not modify `apps/discharges/services.py` (discharge reconciliation).
- Do not change Playwright automation scripts.
- Do not introduce Celery, Redis, or new orchestration infrastructure.
- Do not persist or log real credentials or real patient data.
