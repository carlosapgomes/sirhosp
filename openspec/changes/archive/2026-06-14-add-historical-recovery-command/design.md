# Design: Add Historical Recovery Command

## Context

The project previously had `scripts/recover-historical-data.sh`, a shell helper
that iterated over dates and invoked four Django management commands:

1. `extract_discharges`
2. `extract_admissions`
3. `extract_deaths`
4. `extract_official_census`

That script is useful operationally but is not a durable integration boundary:
it depends on Docker Compose shell execution, parses success through process
exit codes, and cannot produce structured in-process recovery results.

Changes 1 and 2 refactored the four extractor flows into Python-callable
services returning `ExtractionResult`. This change adds command-level recovery
orchestration over those service entry points without introducing persistent job
state or asynchronous infrastructure.

## Goals / Non-Goals

**Goals:**

- Add `recover_historical_data` as a deterministic Django management command.
- Support a single date and an inclusive date range in `DD/MM/AAAA` format.
- Call the four Python service entry points directly, not management commands.
- Preserve the operational extraction order used by the legacy shell script by
  default:
  1. discharges;
  2. admissions;
  3. deaths;
  4. official census.
- Support selecting a subset of extractors for targeted recovery.
- Support `--dry-run` to print the planned execution without running services.
- Support `--fail-fast` to stop on the first failed extraction.
- Produce structured in-memory results suitable for unit testing.
- Return a non-zero command exit when any selected extraction fails.
- Keep implementation synchronous and coordinated only by Python and the
  database state already written by extractor services.

**Non-Goals:**

- Do not persist a recovery-job model or recovery-attempt table.
- Do not implement retries, backoff, scheduling, or resumable job state.
- Do not introduce Celery, Redis, queues, or new worker infrastructure.
- Do not change extractor service internals unless a small compatibility issue
  is found and covered by tests.
- Do not modify `apps/discharges/services.py`.
- Do not delete or rewrite existing extractor management commands.

## Decisions

### Command location and service boundary

Create the management command under ingestion because recovery orchestrates
multiple domains:

```text
apps/ingestion/management/commands/recover_historical_data.py
```

Put orchestration logic in a Python module that can be unit tested without
Django command I/O, for example:

```text
apps/ingestion/historical_recovery.py
```

The command should parse CLI arguments and delegate planning/execution to this
module. Business orchestration should not live directly in the command.

### Date arguments

The command should support these forms:

```bash
python manage.py recover_historical_data --date 01/06/2026
python manage.py recover_historical_data --start-date 01/06/2026 --end-date 05/06/2026
```

`--date` is shorthand for a single-day range. If neither `--date` nor both
`--start-date` and `--end-date` are provided, the command should fail with a
clear validation error. If both forms are provided together, the command should
fail with a clear validation error.

Date parsing should be deterministic and independent of locale. The accepted
format is `DD/MM/AAAA`.

### Extractor selection

Use a repeatable `--extractor` option with constrained values:

```bash
python manage.py recover_historical_data --date 01/06/2026 \
  --extractor admissions --extractor deaths
```

Supported extractor names:

- `discharges`
- `admissions`
- `deaths`
- `official_census`

If no extractor is specified, all four run in the default order. If extractors
are specified, preserve default ordering rather than caller ordering to keep
execution deterministic.

### Service call mapping

The orchestrator should call services directly:

```python
run_discharge_extraction(date=day_br, headless=headless)
run_admission_extraction(start_date=day_br, end_date=day_br, headless=headless)
run_death_extraction(start_date=day_br, end_date=day_br, headless=headless)
run_official_census_extraction(date=day_br, headless=headless)
```

Do not use `call_command`, `subprocess`, or shell scripts as the integration
boundary.

### Result model

Add small dataclasses for command-level results, for example:

```python
@dataclass(frozen=True)
class RecoveryStepResult:
    date: date
    date_label: str
    extractor: str
    result: ExtractionResult | None
    skipped: bool = False

@dataclass(frozen=True)
class RecoveryRunResult:
    start_date: date
    end_date: date
    steps: list[RecoveryStepResult]

    @property
    def success(self) -> bool: ...
```

The exact shape can vary, but tests must be able to assert date planning,
extractor ordering, failure aggregation, and dry-run behavior without reading
stdout.

### Dry run

`--dry-run` should build and print the plan without calling extractor services.
Dry-run results should be successful unless input validation fails. Dry-run step
results can be marked `skipped=True` or use an equivalent explicit field.

### Failure handling

Default behavior should continue after failed extractions and collect all
failures, matching the legacy shell script's "continuing" behavior. The command
exits non-zero after the plan completes if any selected extraction failed.

With `--fail-fast`, stop after the first failed extraction and return a non-zero
exit status.

A service-level result with `success=False` is a failed step. Unexpected Python
exceptions escaping a service call should be converted into a failed step with a
safe error message and should not expose credentials.

### Output format

The command should print deterministic human-readable output:

- planned date range and selected extractors;
- one line per day/extractor with success, failure, or dry-run status;
- final summary with counts for days, steps, successes, failures, and skipped
  steps.

No JSON output is required in this change, but the internal result model should
make JSON output easy to add later.

### Legacy shell script

Keep `scripts/recover-historical-data.sh` unless a slice explicitly updates it
to call the new command. If updated, keep behavior simple and document that the
Django command is the canonical entry point.

## Risks / Trade-offs

- The command is synchronous and may take a long time over large date ranges.
  This is acceptable for this phase because persistent recovery jobs are a
  separate optional follow-up change.
- Running discharges before admissions preserves the legacy order but may not be
  the only clinically intuitive sequence. This change prioritizes compatibility.
- `scripts/test-in-container.sh unit` runs the full unit suite and does not
  accept focused test paths. Slice reports should document focused diagnostic
  runs separately when needed.
- Existing unrelated gate failures may still be present. Do not hide them;
  report exact commands and evidence.
