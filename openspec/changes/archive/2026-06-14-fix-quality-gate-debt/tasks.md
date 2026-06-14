# Fix Quality Gate Debt Tasks

## 1. Reproduce Current Debt

- [ ] 1.1 Confirm branch `change/fix-quality-gate-debt` exists or create it
- [ ] 1.2 Run `./scripts/test-in-container.sh unit` and capture failing tests
- [ ] 1.3 Run `./scripts/test-in-container.sh lint` and capture lint failures
- [ ] 1.4 Run `./scripts/test-in-container.sh typecheck` and capture mypy failure
- [ ] 1.5 Record baseline evidence in `/tmp/sirhosp-slice-QG-S1-report.md`

## 2. Fix Unit Test Debt

- [ ] 2.1 Reproduce the stale inpatient report failure with a focused test if
  possible
- [ ] 2.2 Inspect `report_suspected_stale_inpatients` behavior before changing
  assertions
- [ ] 2.3 Fix the command or test so active/latest admission semantics remain
  explicit
- [ ] 2.4 Run focused stale inpatient tests and document results

## 3. Fix Lint Debt

- [ ] 3.1 Wrap the long services portal route without changing the URL pattern
- [ ] 3.2 Remove or use unused variables reported by ruff
- [ ] 3.3 Run focused ruff on changed files

## 4. Fix Typecheck Debt

- [ ] 4.1 Reproduce the duplicate-module mypy issue
- [ ] 4.2 Fix mypy discovery/package layout with the smallest safe change
- [ ] 4.3 Avoid broad excludes or suppressions unless explicitly justified
- [ ] 4.4 Run the official typecheck gate and document results

## 5. Final Validation

- [ ] 5.1 Run `./scripts/test-in-container.sh check`
- [ ] 5.2 Run `./scripts/test-in-container.sh unit`
- [ ] 5.3 Run `./scripts/test-in-container.sh lint`
- [ ] 5.4 Run `./scripts/test-in-container.sh typecheck`
- [ ] 5.5 Run markdown lint for changed Markdown files
- [ ] 5.6 Run `openspec validate fix-quality-gate-debt --type change --strict`
- [ ] 5.7 Update `/tmp/sirhosp-slice-QG-S1-report.md` with final evidence
- [ ] 5.8 Commit with a clear message and stop
