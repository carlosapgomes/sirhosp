# SLICE-GCEC-S2: Guard snapshot processing and orchestrator behavior

## Handoff for zero-context executor

You are implementing one vertical slice in the SIRHOSP Django project. Start by
reading `AGENTS.md`, `PROJECT_CONTEXT.md`, this slice prompt, and all OpenSpec
artifacts in:

```text
openspec/changes/guard-census-extraction-completeness/
```

This slice assumes GCEC-S1 is complete. Implement only this slice. Use TDD:
write failing tests first, implement the smallest change, then refactor only if
it improves clarity. Follow clean code, DRY and YAGNI.

## Problem

Even if `extract_census` is guarded, operators or future code can still call
`process_census_snapshot` directly against already persisted incomplete
snapshots. The processing layer must refuse to create a batch from fewer than
40 sectors. The adaptive orchestrator must remain fail-safe when extraction is
rejected.

## Scope

Add defense in depth to snapshot processing:

- explicit `run_id` path rejects snapshots with fewer than 40 distinct sectors;
- latest-snapshot path without `run_id` applies the same guard;
- rejected processing creates no `CensusExecutionBatch`;
- rejected processing enqueues no `IngestionRun` records for patients;
- orchestrator behavior proves incomplete extraction does not call processing.

## Suggested files

Touch the minimum possible files. Expected limit: 4 files.

```text
apps/census/services.py
apps/census/management/commands/process_census_snapshot.py
tests/unit/test_process_census_snapshot.py
tests/unit/test_adaptive_census_orchestrator.py
```

If you need more than 5 project files, stop and report why.

## Implementation guidance

- Reuse the threshold helper or constant introduced in GCEC-S1.
- Keep the guard close to the point where `process_census_snapshot` selects its
  queryset.
- Prefer a small domain exception or explicit result shape over broad generic
  exceptions. Choose the smallest approach that preserves current tests.
- Ensure no batch is created before the completeness check passes.
- Ensure queue helper functions are not called for incomplete snapshots.
- The management command should print a clear aggregate message when processing
  is rejected.
- Do not log patient names, prontuários, credentials or clinical text.

## Required tests

Add or update tests so the first test run fails before implementation.

Minimum scenarios:

1. `process_census_snapshot(run_id=...)` with 39 sectors rejects processing.
2. The rejected explicit-run path creates no `CensusExecutionBatch`.
3. The rejected explicit-run path creates no queued admissions or demographics
   runs.
4. Calling without `run_id` rejects the latest snapshot when it has fewer than
   40 sectors.
5. A snapshot with at least 40 sectors still follows the existing happy path.
6. The adaptive orchestrator treats `extract_census` rejection as extraction
   failure and does not call `process_census_snapshot`.

Use synthetic patients and sectors only.

## Acceptance criteria

- Direct processing cannot create a batch from incomplete census data.
- Existing complete-snapshot behavior remains compatible.
- Orchestrator remains fail-safe and does not process rejected extraction.
- Tests prove no patient ingestion jobs are enqueued on rejection.
- No unrelated scraping or UI code is changed.

## Validation commands

Run focused tests first, then official checks appropriate for this slice:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate guard-census-extraction-completeness --type change --strict
```

If you run a narrower pytest command for speed, include it in the report along
with the official command results you completed.

## Required report

Create this file before stopping:

```text
/tmp/sirhosp-slice-GCEC-S2-report.md
```

The report must include:

- slice summary;
- acceptance checklist;
- files changed;
- before and after snippets for each changed file;
- commands executed and results;
- risks and pending items;
- suggested next step.

Stop after this slice. Do not implement GCEC-S3.
