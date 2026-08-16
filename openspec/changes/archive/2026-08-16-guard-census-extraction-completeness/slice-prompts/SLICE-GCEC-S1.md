# SLICE-GCEC-S1: Gate primary extraction completeness

## Handoff for zero-context executor

You are implementing one vertical slice in the SIRHOSP Django project. Start by
reading `AGENTS.md`, `PROJECT_CONTEXT.md`, this slice prompt, and the OpenSpec
artifacts in:

```text
openspec/changes/guard-census-extraction-completeness/
```

Implement only this slice. Use TDD: first add a failing test, then implement the
minimum production code, then refactor only if needed. Follow clean code, DRY
and YAGNI. Do not introduce Celery, Redis, external services, new scraping
architecture or broad refactors.

## Problem

Production observed a successful `census_extraction` with only 25 sectors. The
normal recent range is 42 to 46 sectors. This partial extraction created an
incomplete downstream batch. The first protection must reject incomplete CSV
parsing before persisting `CensusSnapshot` rows.

## Scope

Implement a completeness gate in `extract_census`:

- minimum accepted distinct non-empty sector count: `40`;
- parsed CSVs below the threshold must fail the command;
- failed incomplete extraction must persist no snapshots;
- failure metadata and stage metrics must use only aggregate safe values.

## Suggested files

Touch the minimum possible files. Expected limit: 3 files.

```text
apps/census/services.py
apps/census/management/commands/extract_census.py
tests/unit/test_extract_census_management_command.py
```

If you need more than 4 project files, stop and report why.

## Implementation guidance

- Add a small reusable constant or helper in census domain code, for example a
  minimum-sector constant and validation helper.
- Count distinct sectors after `parse_census_csv` returns parsed rows.
- Reject before `CensusSnapshot.objects.bulk_create(...)`.
- Mark `IngestionRun.status` as `failed`.
- Prefer `failure_reason="invalid_payload"` for insufficient coverage.
- Record stage metric details such as:
  - `sector_count`;
  - `row_count`;
  - `minimum_required_sectors`;
  - `completeness_status`.
- Do not store patient names, prontuários, credentials or clinical text in
  error messages or `details_json`.

## Required tests

Add or update tests so the first test run fails before implementation.

Minimum scenarios:

1. A mocked successful subprocess plus parsed rows from 39 sectors causes
   `call_command("extract_census")` to fail.
2. The incomplete extraction creates zero `CensusSnapshot` rows.
3. The associated `IngestionRun` is marked `failed` with safe failure metadata.
4. Stage metrics include aggregate sector and threshold values.
5. A mocked parsed CSV with at least 40 sectors still succeeds.

Use synthetic rows only. Do not use real patient data.

## Acceptance criteria

- `extract_census` rejects fewer than 40 distinct sectors.
- Accepted extractions keep existing behavior.
- Rejected extractions persist no snapshots from the incomplete CSV.
- Metrics and command output are safe and aggregate only.
- No unrelated files or architecture are changed.

## Validation commands

Run focused tests first, then official checks appropriate for this slice:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate guard-census-extraction-completeness --type change --strict
```

If full unit tests are too slow, also report the exact focused pytest command
used inside the container and why broader tests were deferred.

## Required report

Create this file before stopping:

```text
/tmp/sirhosp-slice-GCEC-S1-report.md
```

The report must include:

- slice summary;
- acceptance checklist;
- files changed;
- before and after snippets for each changed file;
- commands executed and results;
- risks and pending items;
- suggested next step.

Stop after this slice. Do not implement GCEC-S2 or GCEC-S3.
