# Tasks: dedicated-census-orchestrator-service

## 1. Slice DCOS-S1 - Dedicated orchestrator runtime wiring

- [x] 1.1 Read `slice-prompts/SLICE-DCOS-S1.md` completely before coding.
- [x] 1.2 Add failing characterization tests for the production
  `census_orchestrator` Compose service and systemd unit.
- [x] 1.3 Add the dedicated `census_orchestrator` service to
  `compose.prod.yml` with command, environment, networks, tmpfs, `shm_size`,
  log rotation and explicit-start/profile behavior.
- [x] 1.4 Update `deploy/systemd/sirhosp-census-orchestrator.service` to manage
  the dedicated service instead of executing the loop in `web`.
- [x] 1.5 Validate with focused tests and Compose rendering using synthetic
  secrets.
- [x] 1.6 Create `/tmp/sirhosp-slice-DCOS-S1-report.md` with before/after
  snippets, TDD evidence, commands, results, risks and next step.

## 2. Slice DCOS-S2 - Operator documentation and validation guidance

- [x] 2.1 Read `slice-prompts/SLICE-DCOS-S2.md` completely before coding.
- [x] 2.2 Add failing documentation tests proving deploy docs cover the
  dedicated orchestrator service, tmpfs validation, manual one-shot execution,
  monitoring and rollback.
- [x] 2.3 Update `deploy/README.md` so production operation uses the dedicated
  `census_orchestrator` service and warns against running the old `web` loop in
  parallel.
- [x] 2.4 Update any short top-level references only if they become inaccurate
  after the deploy README change.
- [x] 2.5 Validate focused documentation tests, markdown lint and OpenSpec strict
  validation for this change.
- [x] 2.6 Create `/tmp/sirhosp-slice-DCOS-S2-report.md` with before/after
  snippets, TDD evidence, commands, results, risks and final verification
  status.

## 3. Final verification

- [x] 3.1 Run `openspec validate dedicated-census-orchestrator-service --type
  change --strict`.
- [x] 3.2 Run `./scripts/test-in-container.sh check`.
- [x] 3.3 Run relevant unit tests in container for all touched test files.
- [x] 3.4 Run `./scripts/test-in-container.sh lint`.
- [x] 3.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing or justified exceptions.
- [x] 3.6 Run `./scripts/markdown-lint.sh` for changed Markdown files.
- [x] 3.7 Stop after final report; do not archive the change without explicit
  operator approval.
