# Tasks: Add Historical Recovery Command

## 1. Slice C3-S1 - Recovery planning and result contracts

- [x] 1.1 Add tests for date parsing, inclusive range planning, invalid input,
      and extractor selection ordering.
- [x] 1.2 Implement minimal recovery planning and command-level result
      dataclasses in a testable Python module.
- [x] 1.3 Run focused planning tests.
- [x] 1.4 Create `/tmp/sirhosp-slice-C3-S1-report.md` with required
      before/after evidence.

## 2. Slice C3-S2 - Service orchestration engine

- [x] 2.1 Add tests proving the orchestrator calls the four extractor services
      directly in default order.
- [x] 2.2 Add tests proving selected extractor subsets run in deterministic
      default order.
- [x] 2.3 Implement service-call mapping for discharges, admissions, deaths,
      and official census using Python-callable services.
- [x] 2.4 Add tests proving no management-command boundary is used.
- [x] 2.5 Run focused orchestration tests.
- [x] 2.6 Create `/tmp/sirhosp-slice-C3-S2-report.md` with required
      before/after evidence.

## 3. Slice C3-S3 - Failure aggregation, dry-run, and fail-fast

- [x] 3.1 Add tests for dry-run planning that verifies no services are called.
- [x] 3.2 Add tests for default continue-on-failure aggregation.
- [x] 3.3 Add tests for `--fail-fast` stopping after the first failed step.
- [x] 3.4 Add tests for unexpected service exceptions becoming safe failed
      steps.
- [x] 3.5 Implement dry-run, aggregation, fail-fast, and safe exception
      handling in the orchestration module.
- [x] 3.6 Run focused failure-handling tests.
- [x] 3.7 Create `/tmp/sirhosp-slice-C3-S3-report.md` with required
      before/after evidence.

## 4. Slice C3-S4 - Management command wrapper and operator output

- [x] 4.1 Add command tests for `recover_historical_data` CLI argument parsing.
- [x] 4.2 Add command tests for deterministic stdout/stderr summary and exit
      status.
- [x] 4.3 Implement the management command as a thin wrapper around the
      orchestration module.
- [x] 4.4 Preserve existing extractor commands unchanged.
- [x] 4.5 Run focused command tests.
- [x] 4.6 Create `/tmp/sirhosp-slice-C3-S4-report.md` with required
      before/after evidence.

## 5. Slice C3-S5 - Legacy shell script and documentation handoff

- [x] 5.1 Decide whether to keep `scripts/recover-historical-data.sh` unchanged
      or update it to call the new Django command.
      **Decision:** updated header comment only; logic unchanged as legacy
      helper. See ``recovery-handoff.md``.
- [x] 5.2 If the script is updated, add focused coverage or documented manual
      validation for the wrapper behavior.
      The script logic was not changed; only a prominent header comment was
      added explaining legacy status. No test coverage needed.
- [x] 5.3 Add or update a short handoff note describing the canonical recovery
      entry point and known non-goals.
      Created ``recovery-handoff.md``.
- [x] 5.4 Confirm no persistent recovery job model or migration was added.
- [x] 5.5 Run markdown lint for changed `.md` files.
- [x] 5.6 Create `/tmp/sirhosp-slice-C3-S5-report.md` with required
      before/after evidence.

## 6. Slice C3-S6 - Final validation and archive readiness

- [x] 6.1 Run relevant containerized validation commands for this change.
- [x] 6.2 Run `openspec validate add-historical-recovery-command --type change
      --strict`.
- [x] 6.3 Update OpenSpec checkboxes for completed tasks.
- [x] 6.4 Confirm Change 1, Change 2, and Change 3 are ready for later archive,
      but do not archive them in this slice.
- [x] 6.5 Create `/tmp/sirhosp-slice-C3-S6-report.md` with final validation
      evidence and remaining known caveats.
