# Design: Extract Census and Discharge Services

## Context

Change 1 extracted admissions and deaths into Python-callable services while
keeping existing management commands as CLI wrappers. Official census and
discharges still keep orchestration inside management commands:

- credential resolution;
- date parsing;
- `IngestionRun` creation and finalization;
- Playwright subprocess invocation;
- output discovery;
- persistence;
- stage metrics;
- CLI exit behavior.

This makes a future deterministic `recover_historical_data` command fragile
because it would need to call management commands or duplicate command logic.
The remaining extraction flows are more complex than admissions/deaths because
official census persists snapshot rows and discharges parse XLS files and upsert
records.

A hard constraint for this change is that `apps/discharges/services.py` must not
be modified. That module owns the existing discharge reconciliation flow and is
not the correct boundary for report extraction persistence.

## Goals / Non-Goals

**Goals:**

- Provide Python-callable service entry points for official census and discharge
  report extraction.
- Preserve existing management command names, options, output semantics, and
  failure exit behavior as much as practical.
- Reuse `ExtractionResult`, `resolve_source_credentials`, `safe_error_message`,
  `create_stage_metric`, `mark_run_succeeded`, and `mark_run_failed` from
  `apps.ingestion.historical_extraction`.
- Preserve subprocess boundaries to existing Playwright automation scripts.
- Persist `IngestionRun` lifecycle and stage metrics for success, failure, and
  timeout cases.
- Keep persistence deterministic for repeated execution of the same target date.
- Keep discharge extraction code separate from the discharge reconciliation
  service module.
- Produce slice prompts small enough for a context-zero executor.

**Non-Goals:**

- Do not implement `recover_historical_data` in this change.
- Do not modify admission or death services unless a small shared helper fix is
  required and covered by tests.
- Do not modify `apps/discharges/services.py`.
- Do not introduce Celery, Redis, message queues, or new orchestration
  infrastructure.
- Do not change the Playwright automation architecture.
- Do not archive Change 1 or this change as part of implementation.

## Decisions

### Service boundaries

Official census should expose a service function with an interface similar to:

```python
run_official_census_extraction(date: str, headless: bool = True) -> ExtractionResult
```

The service should use `target_start == target_end == parsed date` because the
current command extracts a single daily official census report.

Discharge extraction should expose a service function in a new module, for
example:

```python
apps/discharges/extraction_service.py
run_discharge_extraction(date: str, headless: bool = True) -> ExtractionResult
```

The new module may move helper functions currently embedded in
`extract_discharges.py`, such as XLS row parsing and report persistence. It must
not use or modify `apps/discharges/services.py`.

### Management command wrappers

The management commands remain operator-facing entry points:

- `extract_official_census --date DD/MM/AAAA --headless/--no-headless`
- `extract_discharges --date DD/MM/AAAA --headless/--no-headless`

Commands should resolve default dates and delegate execution to the service. They
should translate `ExtractionResult` to stdout/stderr messages and `sys.exit(1)`
on failure, matching the pattern established by admissions/deaths.

### Persistence behavior

Official census persistence should remain date-replace semantics:

- delete existing `OfficialCensusRecord` rows for the target date;
- bulk-create rows from the latest successful extraction output;
- persist zero records successfully when no output file or no records are found.

Discharge report persistence should preserve existing upsert semantics:

- parse the newest matching `altas-<safe-date>-*.xlsx` file;
- upsert `DischargeRecord` by the current business key used by the command;
- persist `DailyDischargeCount` for the reference date with JSON-serializable raw
  data;
- persist zero records successfully when no XLS or no parseable rows are found.

If implementation discovers the current discharge persistence is not fully
idempotent, harden only the report extraction persistence path and cover it with
regression tests. Do not change the reconciliation behavior in
`apps/discharges/services.py`.

### Failure metadata safety

Timeout and unexpected failure paths must never persist source credentials. In
particular, do not use `str(SubprocessTimeoutError)` as a user-facing or
persisted error message because it can include the command arguments. Use a
stable safe message such as:

```text
Source-system automation timed out.
```

Subprocess non-zero failures may use bounded stderr, but stage details should not
include full command lines or credential values.

### Observability

Each service execution that reaches subprocess orchestration should create an
`IngestionRun` with an intent matching existing command behavior:

- `official_census_extraction`
- `discharge_extraction`

Each successful service run should record two stages:

- extraction stage;
- persistence stage.

Failures should mark the run as `failed` with normalized failure reason where
possible. Timeout failures should set `timed_out=True`.

### Slice strategy

The change should be implemented in small vertical slices:

1. official census service and command wrapper;
2. official census persistence hardening;
3. discharge extraction service in a new module;
4. discharge persistence hardening;
5. observability and CLI compatibility validation;
6. final validation and Change 3 handoff.

Each slice should produce the required `/tmp/sirhosp-slice-<ID>-report.md` file
and stop before the next slice.

## Risks / Trade-offs

- Official census and discharge commands contain duplicated orchestration that
  may be tempting to abstract too early. This change should prefer explicit,
  readable services over premature generic orchestration.
- Discharge extraction uses XLS parsing and upsert semantics. Tests should use
  synthetic XLS fixtures and must not include real patient data.
- `scripts/test-in-container.sh unit` currently runs the entire unit suite and
  does not accept narrowed paths. Focused container validation may require a
  manual `docker compose run ... pytest <paths>` command or host-only diagnostic
  `uv run pytest ...`, with the distinction documented in reports.
- Existing unrelated gate failures may remain outside this change. Slice reports
  should record exact failures and classify them as unrelated only when evidence
  supports that conclusion.
