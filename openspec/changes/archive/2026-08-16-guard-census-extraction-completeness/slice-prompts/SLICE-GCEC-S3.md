# SLICE-GCEC-S3: Improve Playwright sector discovery diagnostics

## Handoff for zero-context executor

You are implementing one vertical slice in the SIRHOSP Django project. Start by
reading `AGENTS.md`, `PROJECT_CONTEXT.md`, this slice prompt, and all OpenSpec
artifacts in:

```text
openspec/changes/guard-census-extraction-completeness/
```

This slice assumes GCEC-S1 and GCEC-S2 are complete. Implement only this slice.
Use TDD: add failing tests for pure helpers or deterministic script behavior
first, then implement the smallest production change. Follow clean code, DRY and
YAGNI. Do not run real scraping in tests.

## Problem

The likely cause of the partial extraction was incomplete sector discovery from
the source-system dropdown/autocomplete. The gate added in earlier slices
prevents downstream damage, but operators also need safer script diagnostics and
a more robust sector collection routine.

## Scope

Improve the Playwright census script diagnostics and sector discovery helpers:

- normalize and deduplicate sector labels consistently;
- attempt to collect the full dropdown contents more robustly;
- print aggregate counters for discovered, processed, empty and failed sectors;
- keep output safe and free of patient identifiers or credentials.

## Suggested files

Touch the minimum possible files. Expected limit: 3 files.

```text
automation/source_system/current_inpatients/extract_census.py
tests/unit/test_extract_census_script.py
```

If an existing test file is more appropriate, use it instead. If you need more
than 4 project files, stop and report why.

## Implementation guidance

- Prefer adding small pure helper functions for sector label normalization,
  deduplication and summary counting.
- Unit-test pure helpers without launching Playwright.
- Keep Playwright interactions local to `extract_setores()` or very small
  helper functions.
- If adding scrolling or repeated panel reads, keep timeouts bounded and avoid
  broad sleeps that slow every sector extraction unnecessarily.
- Preserve existing command-line arguments and output paths.
- Do not persist patient names, prontuários, credentials or clinical text in
  new diagnostics.

## Required tests

Add or update tests so the first test run fails before implementation.

Minimum scenarios:

1. Sector normalization drops blank labels and preserves valid labels.
2. Deduplication keeps first occurrence order.
3. Summary counters report discovered, processed, empty and failed counts from
   synthetic result dictionaries.
4. The terminal summary includes the new aggregate labels.
5. Existing proxy-related tests for the script still pass.

Do not contact the source system. Do not use real patient data.

## Acceptance criteria

- Script output exposes safe aggregate sector counters.
- Sector helper tests are deterministic and do not require Playwright browser
  execution.
- Existing extraction behavior and CLI remain compatible.
- No downstream Django processing logic is changed in this slice.
- No unrelated scraping modules are refactored.

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
/tmp/sirhosp-slice-GCEC-S3-report.md
```

The report must include:

- slice summary;
- acceptance checklist;
- files changed;
- before and after snippets for each changed file;
- commands executed and results;
- risks and pending items;
- suggested next step.

Stop after this slice and final validation. Do not archive the change.
