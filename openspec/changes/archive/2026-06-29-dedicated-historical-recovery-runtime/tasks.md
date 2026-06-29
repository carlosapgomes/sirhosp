# Tasks: dedicated-historical-recovery-runtime

## 1. Slice DHRR-S1 - Dedicated batch runtime wiring

- [x] 1.1 Read `slice-prompts/SLICE-DHRR-S1.md` completely before coding.
- [x] 1.2 Add failing characterization tests for the production
  `historical_recovery` Compose service/runtime.
- [x] 1.3 Add the dedicated `historical_recovery` service to `compose.prod.yml`
  with explicit profile, safe default command, source-system environment,
  networks, bounded tmpfs, `shm_size`, log rotation and no long-running restart
  behavior.
- [x] 1.4 Validate with focused tests and Compose rendering using synthetic
  secrets; inspect only the `historical_recovery` section.
- [x] 1.5 Create `/tmp/sirhosp-slice-DHRR-S1-report.md` with before/after
  snippets, TDD evidence, commands, results, risks and next step.

## 2. Slice DHRR-S2 - Operator documentation and validation guidance

- [x] 2.1 Read `slice-prompts/SLICE-DHRR-S2.md` completely before coding.
- [x] 2.2 Add failing documentation tests proving deploy docs cover the
  dedicated historical recovery runtime, selected extractor execution, dry-run,
  tmpfs validation, monitoring, sizing, safety and rollback.
- [x] 2.3 Update `deploy/README.md` so production historical recovery uses the
  dedicated `historical_recovery` runtime for manual batches.
- [x] 2.4 Update any short top-level references only if they become inaccurate
  after the deploy README change.
- [x] 2.5 Validate focused documentation tests, markdown lint and OpenSpec strict
  validation for this change.
- [x] 2.6 Create `/tmp/sirhosp-slice-DHRR-S2-report.md` with before/after
  snippets, TDD evidence, commands, results, risks and final verification
  status.

## 3. Final verification

- [x] 3.1 Run `openspec validate dedicated-historical-recovery-runtime --type
  change --strict`.
- [x] 3.2 Run `./scripts/test-in-container.sh check`.
- [x] 3.3 Run relevant unit tests in container for all touched test files.
- [x] 3.4 Run `./scripts/test-in-container.sh lint`.
- [x] 3.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing or justified exceptions.
- [x] 3.6 Run `./scripts/markdown-lint.sh` for changed Markdown files.
- [ ] 3.7 Stop after final report; do not archive the change without explicit
  operator approval.
