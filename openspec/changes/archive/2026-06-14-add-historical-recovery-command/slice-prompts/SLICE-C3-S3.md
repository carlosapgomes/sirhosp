# SLICE C3-S3 - Failure aggregation, dry-run, and fail-fast

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/add-historical-recovery-command/proposal.md`
- `openspec/changes/add-historical-recovery-command/design.md`
- `openspec/changes/add-historical-recovery-command/specs/historical-recovery-command/spec.md`
- `openspec/changes/add-historical-recovery-command/specs/ingestion-run-observability/spec.md`
- `openspec/changes/add-historical-recovery-command/tasks.md`
- `openspec/changes/extract-census-discharge-services/change-3-handoff.md`

Implement only Slice C3-S3. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/add-historical-recovery-command
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Add dry-run planning and robust failure aggregation semantics to the
recovery orchestrator.

## Suggested scope

Use mocked services returning `ExtractionResult` or raising exceptions. Cover
continue-on-failure, fail-fast, dry-run skip behavior, and safe exception text.

Before coding, confirm Slice C3-S2 was committed. If not, stop and ask for the
S2 commit/handoff. Do not mix uncommitted S2 changes into this slice.

Carry forward these verifier findings from C3-S2:

- `execute_recovery_plan()` currently ignores `plan.dry_run` and
  `plan.fail_fast`; this is expected to be fixed in C3-S3.
- The current unexpected-exception path uses raw exception text via
  `traceback.format_exception_only(...)`. This is not credential-safe and must
  be replaced or sanitized in this slice.
- Do not claim credential safety unless tests prove secrets are redacted from
  `RecoveryStepResult.error_message` and any command-facing summary text added
  by this slice.

## Suggested files

Prefer no more than 5 changed files unless tests require a small helper.

Likely files:

- `apps/ingestion/historical_recovery.py`
- `tests/unit/test_historical_recovery_failures.py`
- optional existing historical recovery tests

If you touch `tests/unit/test_historical_recovery_planning.py` or
`tests/unit/test_historical_recovery_orchestration.py`, list the file and reason
explicitly in the slice report.

## Required behavior

Implement and test all of the following:

1. `dry_run=True` must never call extractor services.
2. Dry-run steps must be represented explicitly, preferably with
   `skipped=True`, `success=True`, empty metrics, and no `ingestion_run_id`.
3. Default execution must continue after failed service results and aggregate
   all failures.
4. `fail_fast=True` must stop after the first failed service result.
5. Unexpected Python exceptions raised by service calls must become failed
   steps with `failure_reason="unexpected_error"` or the existing normalized
   value used by the module.
6. Unexpected exception messages must not leak credential-like values.

At minimum, test redaction for exception messages containing values like:

```text
auth failed for postgresql://user:SECRET@host with --password SECRET
```

The resulting `RecoveryStepResult.error_message` must not contain `SECRET`,
`--password SECRET`, or an embedded credential URL.

Prefer a deterministic generic message for unexpected exceptions, such as:

```text
Unexpected extractor failure.
```

If you implement a redaction helper instead, cover it with focused tests.

## Constraints

- Do not modify `apps/discharges/services.py`.
- Do not modify Playwright automation scripts.
- Do not add Celery, Redis, queues, or new orchestration infrastructure.
- Do not add persistent recovery job models or migrations.
- Do not use `call_command` or subprocessed Django commands to run extractors.
- Do not delete existing extractor management commands.
- Do not archive OpenSpec changes in this slice.
- Use synthetic/anonymized test data only.
- Do not defer dry-run safety to the future command wrapper. The orchestration
  function must itself avoid service calls when `plan.dry_run` is true.

## Validation

Run at least:

```bash
uv run ruff check apps/ingestion/historical_recovery.py \
  tests/unit/test_historical_recovery_failures.py
uv run pytest -q tests/unit/test_historical_recovery_failures.py
./scripts/test-in-container.sh unit
openspec validate add-historical-recovery-command --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. Host-only `uv run pytest ...` is
acceptable only as diagnostic evidence, not as the official gate.

## Required report

Create `/tmp/sirhosp-slice-C3-S3-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for changed production files;
- commands executed and results;
- risks, pending work, and next suggested slice.
