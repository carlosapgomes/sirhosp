# SLICE S8 - Safe failure hardening and period metadata

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1-S7 if available, especially
  `/tmp/sirhosp-slice-S7-report.md`.

Implement only Slice S8. This is a hardening slice before archiving Change 1.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Harden admission and death extraction services so failure metadata is safe,
period result metadata is correct, and unexpected exceptions do not leave
`IngestionRun` rows stuck as `running`.

## Background

A final review found three risks after S7:

1. Timeout handling uses `str(exc)` from `SubprocessTimeoutError`. That string
   can include the subprocess command and therefore the `--password` argument.
2. Service results currently use the parsed start date as both `target_start`
   and `target_end`, even when callers pass a real period.
3. The outer fallback `except Exception` returns a failed `ExtractionResult`,
   but may not mark an already-created `IngestionRun` as failed.

Fix these risks with minimal service changes and regression tests.

## Suggested scope

Prefer no more than 5 changed files.

Likely files:

- `apps/admissions/services.py`
- `apps/deaths/services.py`
- `tests/unit/test_admission_extraction_service.py`
- `tests/unit/test_death_extraction_service.py`
- `openspec/changes/extract-admission-death-services/tasks.md`

Do not create new modules unless there is a strong reason.

## Required behavior

### Period metadata

- Parse both `start_date` and `end_date` in `DD/MM/AAAA` format.
- Return `failure_reason="validation_error"` for an invalid start or end date.
- Set `ExtractionResult.target_start` to the parsed start date.
- Set `ExtractionResult.target_end` to the parsed end date.
- Preserve the existing persistence reference date behavior by continuing to use
  the parsed start date as the reference date unless existing tests require a
  different behavior.

### Safe timeout failure messages

- Do not use `str(exc)` from `SubprocessTimeoutError` for user-facing or
  persisted error messages.
- Use a deterministic safe message such as
  `"Source-system automation timed out."`.
- Preserve `failure_reason="timeout"` and `timed_out=True`.
- Ensure no source credential value appears in:
  - `ExtractionResult.error_message`;
  - `IngestionRun.error_message`;
  - any `IngestionRunStageMetric.details_json` value.

### Outer unexpected exception fallback

- If the outer fallback catches an exception after an `IngestionRun` was
  created, mark that run as `failed`.
- Persist a safe error message and `failure_reason="unexpected_exception"`.
- Add a failed stage metric only if it can be done without duplicating a more
  specific failed stage already recorded by an inner handler.
- Do not let the linked run remain `running` after the service returns a failed
  `ExtractionResult`.

## Test guidance

Use TDD. Add failing tests first, then implementation.

At minimum add coverage for both admissions and deaths:

- timeout result/run/stage metadata does not contain the mocked password;
- period request such as `01/06/2026` to `05/06/2026` returns
  `target_start=date(2026, 6, 1)` and `target_end=date(2026, 6, 5)`;
- an unexpected exception after run creation leaves the linked run with
  `status="failed"` and `failure_reason="unexpected_exception"`.

Suggested way to trigger the outer fallback without hitting real automation:

- patch the service's `tempfile.TemporaryDirectory` or another operation inside
  the outer `try` block to raise after the `IngestionRun` is created;
- keep credentials mocked and script existence mocked as needed.

## Constraints

- Do not modify discharge-related code in this change.
- Do not start official census/discharge refactoring in this slice.
- Do not create `recover_historical_data`.
- Do not add Celery, Redis, or new orchestration infrastructure.
- Preserve management command compatibility.
- Preserve Playwright scripts as subprocess boundaries.
- Do not persist or log real credentials.
- Keep changes minimal and local to this hardening slice.

## Validation

Run at least focused validations:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_admission_extraction_service.py \
  tests/unit/test_death_extraction_service.py
openspec validate extract-admission-death-services --type change --strict
CHANGE_DIR=openspec/changes/extract-admission-death-services
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  "$CHANGE_DIR/tasks.md" \
  "$CHANGE_DIR/slice-prompts/SLICE-S8.md"
```

If time allows, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If any command fails due to known pre-existing unrelated failures, document the
exact failing command, failing test or lint rule, and why it is unrelated.

## Required report

Create `/tmp/sirhosp-slice-S8-report.md` with:

- summary of the hardening slice;
- acceptance checklist for S8 tasks;
- files changed;
- before/after snippets for each changed production file;
- tests added or changed;
- validation commands and results;
- remaining risks, if any;
- explicit recommendation on whether Change 1 is ready to archive.
