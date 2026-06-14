# Fix Revealed Typecheck Errors Tasks

## 1. Baseline

- [ ] 1.1 Create or switch to branch `change/fix-revealed-typecheck-errors`
- [ ] 1.2 Run `./scripts/test-in-container.sh typecheck` and capture current
  errors
- [ ] 1.3 Confirm the errors match the revealed mypy debt listed in the design
- [ ] 1.4 Create `/tmp/sirhosp-slice-TC-S1-report.md` with baseline evidence

## 2. Discharge Test Type Fixes

- [ ] 2.1 Inspect `tests/unit/test_discharge_persistence_hardening.py`
- [ ] 2.2 Inspect `tests/unit/test_discharge_extraction_service.py`
- [ ] 2.3 Fix heterogeneous tuple typing without weakening assertions
- [ ] 2.4 Run focused discharge unit tests touched by the change

## 3. Services Portal View Type Fixes

- [ ] 3.1 Inspect the affected code around mypy lines 2072 and 2108 in
  `apps/services_portal/views.py`
- [ ] 3.2 Add precise local typing or conversions to resolve assignment and
  unary-negation errors
- [ ] 3.3 Run focused services portal tests if available

## 4. Final Validation

- [ ] 4.1 Run `uv run ruff check` on changed Python files
- [ ] 4.2 Run `./scripts/test-in-container.sh check`
- [ ] 4.3 Run `./scripts/test-in-container.sh unit`
- [ ] 4.4 Run `./scripts/test-in-container.sh typecheck`
- [ ] 4.5 Run markdown lint for changed Markdown files
- [ ] 4.6 Run `openspec validate fix-revealed-typecheck-errors --type change --strict`
- [ ] 4.7 Update `/tmp/sirhosp-slice-TC-S1-report.md` with final evidence
- [ ] 4.8 Commit with a clear message and stop
