# Add Retry to Historical Recovery

## Why

Manual recovery over longer historical ranges can produce a small number of
transient extractor failures, such as temporary source unavailability. Retrying
only failed steps after the full batch finishes gives the source system a
natural recovery window without blocking successful extractors or repeating the
whole batch.

## What Changes

- Add automatic end-of-batch retry support to `recover_historical_data`.
- Retry only failed date/extractor steps, not successful steps.
- Default maximum retries to 3 attempts after the initial batch.
- Preserve deterministic ordering for retry attempts.
- Include retry attempts and final outcome in command output and result
  aggregation.
- Keep retry state in memory only; do not add recovery job/attempt tables or
  migrations.
- Preserve `--dry-run` and `--fail-fast` behavior.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `historical-recovery-command`: Add end-of-batch retry semantics for failed
  recovery steps.

## Impact

- Expected files:
  - `apps/ingestion/historical_recovery.py`
  - `apps/ingestion/management/commands/recover_historical_data.py`
  - `tests/unit/test_historical_recovery_failures.py`
  - `tests/unit/test_recover_historical_data_command.py`
  - `README.md` if operator documentation is updated
- No database migrations, Celery/Redis, Playwright automation changes, or
  persistent recovery state are expected.
