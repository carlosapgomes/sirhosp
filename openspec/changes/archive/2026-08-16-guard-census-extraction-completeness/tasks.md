# Tasks: guard-census-extraction-completeness

## 1. Slice GCEC-S1 - Gate primary extraction completeness

- [x] 1.1 Read `slice-prompts/SLICE-GCEC-S1.md` completely before coding.
- [x] 1.2 Add failing unit tests proving `extract_census` rejects parsed CSVs
  with fewer than 40 distinct sectors and persists no `CensusSnapshot` rows.
- [x] 1.3 Add a small reusable helper or constant for the minimum sector
  threshold without spreading magic numbers.
- [x] 1.4 Implement the `extract_census` completeness gate, failure status and
  safe aggregate stage metrics.
- [x] 1.5 Validate with focused tests plus official container checks required by
  the slice prompt.
- [x] 1.6 Create `/tmp/sirhosp-slice-GCEC-S1-report.md` with before/after
  snippets, commands, results, risks and next step.

## 2. Slice GCEC-S2 - Guard snapshot processing and orchestrator behavior

- [x] 2.1 Read `slice-prompts/SLICE-GCEC-S2.md` completely before coding.
- [x] 2.2 Add failing tests proving `process_census_snapshot` refuses snapshots
  with fewer than 40 sectors for both explicit `run_id` and latest-snapshot
  paths.
- [x] 2.3 Implement the processing guard so no `CensusExecutionBatch` or patient
  ingestion runs are created from incomplete snapshots.
- [x] 2.4 Add or update a focused orchestrator regression test proving
  incomplete extraction is treated as extraction failure and snapshot
  processing is not called.
- [x] 2.5 Validate with focused tests plus official container checks required by
  the slice prompt.
- [x] 2.6 Create `/tmp/sirhosp-slice-GCEC-S2-report.md` with implementation
  evidence for third-party LLM review.

## 3. Slice GCEC-S3 - Improve Playwright sector discovery diagnostics

- [x] 3.1 Read `slice-prompts/SLICE-GCEC-S3.md` completely before coding.
- [x] 3.2 Add failing unit tests for pure sector normalization/deduplication and
  aggregate summary counters in the Playwright census script.
- [x] 3.3 Improve `extract_setores()` or its helper functions to reduce partial
  dropdown collection risk without adding external dependencies.
- [x] 3.4 Ensure the script prints safe aggregate counters for sectors
  discovered, processed, empty and failed.
- [x] 3.5 Validate with focused tests plus official container checks required by
  the slice prompt.
- [x] 3.6 Create `/tmp/sirhosp-slice-GCEC-S3-report.md` with implementation
  evidence for third-party LLM review.

## 4. Final verification

- [x] 4.1 Run OpenSpec strict validation for
  `guard-census-extraction-completeness`.
- [x] 4.2 Run `./scripts/test-in-container.sh check`.
- [x] 4.3 Run relevant unit/integration tests in container for all touched code.
- [x] 4.4 Run `./scripts/test-in-container.sh lint`.
- [x] 4.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing or justified exceptions.
- [x] 4.6 Run `./scripts/markdown-lint.sh` for changed Markdown files.
- [x] 4.7 Stop after final report; do not archive the change without explicit
  operator approval.
