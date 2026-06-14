# Fix Summary Integration Failures Tasks

## 1. Baseline and Diagnosis

- [ ] 1.1 Start from a clean working tree; commit or stash unrelated README
  documentation changes first
- [ ] 1.2 Create or switch to branch `change/fix-summary-integration-failures`
- [ ] 1.3 Reproduce the focused failing tests in
  `tests/integration/test_summary_cost_visibility_http.py`
- [ ] 1.4 Reproduce the focused failing test in
  `tests/integration/test_summary_http.py`
- [ ] 1.5 Inspect current summary views/templates and linked pipeline run lookup
- [ ] 1.6 Record baseline evidence in `/tmp/sirhosp-slice-SIF-S1-report.md`

## 2. Cost Visibility Fix

- [ ] 2.1 Determine whether failing cost tests use stale unlinked pipeline
  fixtures or expose a production page regression
- [ ] 2.2 Update fixtures to link `SummaryPipelineRun` to `SummaryRun` if the
  current spec requires linked-run lookup
- [ ] 2.3 Fix views/templates if linked pipeline costs are still not displayed
- [ ] 2.4 Preserve USD, BRL, missing-exchange-rate fallback, zero-cost, and
  phase-1 reuse assertions

## 3. Admission Context Fix

- [ ] 3.1 Determine why `source_admission_key` is absent from the run
  status page
- [ ] 3.2 Fix the status page template or context if admission reference is
  expected to be operator-visible
- [ ] 3.3 Keep patient name and run status/mode/timestamp behavior intact

## 4. Final Validation

- [ ] 4.1 Run focused integration tests for summary cost visibility and status
- [ ] 4.2 Run `./scripts/test-in-container.sh integration`
- [ ] 4.3 Run `./scripts/test-in-container.sh check`
- [ ] 4.4 Run `./scripts/test-in-container.sh unit`
- [ ] 4.5 Run `./scripts/test-in-container.sh lint`
- [ ] 4.6 Run `./scripts/test-in-container.sh typecheck`
- [ ] 4.7 Run markdown lint for changed Markdown files
- [ ] 4.8 Run OpenSpec strict validation for
  `fix-summary-integration-failures`
- [ ] 4.9 Update `/tmp/sirhosp-slice-SIF-S1-report.md` with final evidence
- [ ] 4.10 Commit with a clear message and stop
