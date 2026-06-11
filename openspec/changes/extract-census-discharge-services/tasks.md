# Tasks: Extract Census and Discharge Services

## 1. Slice S1 - Official census extraction service and command wrapper

- [x] 1.1 Add characterization tests for official census service execution with
      mocked subprocess output and synthetic JSON records.
- [x] 1.2 Move official census extraction orchestration into a Python-callable
      service while preserving existing persistence semantics.
- [x] 1.3 Update `extract_official_census` management command to delegate to the
      service and preserve CLI behavior.
- [x] 1.4 Run focused official census extraction tests.
- [x] 1.5 Create `/tmp/sirhosp-slice-C2-S1-report.md` with required
      before/after evidence.

## 2. Slice S2 - Official census persistence hardening

- [x] 2.1 Add tests proving repeated official census extraction for the same
      date does not duplicate records.
- [x] 2.2 Add tests proving empty official census output persists a successful
      zero-count result and clears stale rows for the target date.
- [x] 2.3 Harden official census persistence with the smallest safe
      transaction/idempotency changes required by the tests.
- [x] 2.4 Run focused official census persistence tests.
- [x] 2.5 Create `/tmp/sirhosp-slice-C2-S2-report.md` with required
      before/after evidence.

## 3. Slice S3 - Discharge extraction service and command wrapper

- [x] 3.1 Add characterization tests for discharge service execution with mocked
      subprocess output and synthetic XLS data.
- [x] 3.2 Move discharge report extraction orchestration into a Python-callable
      service outside `apps/discharges/services.py`.
- [x] 3.3 Preserve XLS row parsing behavior and report persistence semantics.
- [x] 3.4 Update `extract_discharges` management command to delegate to the
      extraction service and preserve CLI behavior.
- [x] 3.5 Run focused discharge extraction tests.
- [x] 3.6 Create `/tmp/sirhosp-slice-C2-S3-report.md` with required
      before/after evidence.

## 4. Slice S4 - Discharge persistence hardening

- [ ] 4.1 Add tests proving repeated discharge extraction for the same date does
      not duplicate `DischargeRecord` rows.
- [ ] 4.2 Add tests proving empty discharge output persists a successful
      zero-count result.
- [ ] 4.3 Harden discharge report persistence with the smallest safe
      transaction/idempotency changes required by the tests.
- [ ] 4.4 Confirm `apps/discharges/services.py` remains unchanged.
- [ ] 4.5 Run focused discharge persistence tests.
- [ ] 4.6 Create `/tmp/sirhosp-slice-C2-S4-report.md` with required
      before/after evidence.

## 5. Slice S5 - Observability, failure safety, and CLI compatibility

- [ ] 5.1 Add or adjust tests that verify census and discharge service
      executions preserve `IngestionRun` lifecycle and stage metrics.
- [ ] 5.2 Add tests proving timeout and unexpected failure metadata does not
      expose source credentials.
- [ ] 5.3 Verify commands still expose the existing `--date`, `--headless`, and
      `--no-headless` arguments.
- [ ] 5.4 Ensure outer unexpected failures after run creation mark the linked
      `IngestionRun` as failed.
- [ ] 5.5 Run focused observability and command compatibility tests.
- [ ] 5.6 Create `/tmp/sirhosp-slice-C2-S5-report.md` with required
      before/after evidence.

## 6. Slice S6 - Change-level validation and Change 3 handoff

- [ ] 6.1 Run relevant containerized validation commands for this change.
- [ ] 6.2 Update OpenSpec checkboxes for completed tasks and confirm markdown
      lint passes for changed `.md` files.
- [ ] 6.3 Create `change-3-handoff.md` describing service entry points and known
      validation caveats for `add-historical-recovery-command`.
- [ ] 6.4 Confirm no discharge reconciliation code was modified.
- [ ] 6.5 Create `/tmp/sirhosp-slice-C2-S6-report.md` with final validation
      evidence and archive readiness notes.
