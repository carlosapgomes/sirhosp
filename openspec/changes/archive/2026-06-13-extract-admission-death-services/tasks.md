# Tasks: Extract Admission and Death Services

## 1. Slice S1 - Shared extraction contract

- [x] 1.1 Add tests for a small structured extraction result contract covering
      success and failure metadata.
- [x] 1.2 Implement the minimal shared contract for historical extraction
      services without changing existing commands.
- [x] 1.3 Run focused tests for the new contract.
- [x] 1.4 Create `/tmp/sirhosp-slice-S1-report.md` with required before/after
      evidence.

## 2. Slice S2 - Shared execution helpers

- [x] 2.1 Add tests for shared helper behavior needed by admissions and deaths,
      including safe credential resolution and stage/failure recording.
- [x] 2.2 Implement focused helper functions for source credentials,
      `IngestionRun` stage metrics, run finalization, and safe error handling.
- [x] 2.3 Run focused tests for helper behavior.
- [x] 2.4 Create `/tmp/sirhosp-slice-S2-report.md` with required before/after
      evidence.

## 3. Slice S3 - Admission extraction service and command wrapper

- [x] 3.1 Add characterization tests for `extract_admissions` service execution
      with mocked subprocess output.
- [x] 3.2 Move admission extraction orchestration into a Python-callable service
      while preserving the existing persistence function.
- [x] 3.3 Update `extract_admissions` management command to delegate to the
      service and preserve CLI behavior.
- [x] 3.4 Run focused admission extraction tests.
- [x] 3.5 Create `/tmp/sirhosp-slice-S3-report.md` with required before/after
      evidence.

## 4. Slice S4 - Admission persistence hardening

- [x] 4.1 Add tests proving repeated admission extraction persistence does not
      duplicate individual records.
- [x] 4.2 Add tests proving empty admission output persists a successful
      zero-count result.
- [x] 4.3 Harden admission persistence with the smallest safe
      transaction/idempotency changes required by the tests.
- [x] 4.4 Run focused admission persistence tests.
- [x] 4.5 Create `/tmp/sirhosp-slice-S4-report.md` with required before/after
      evidence.

## 5. Slice S5 - Death extraction service and command wrapper

- [x] 5.1 Add characterization tests for `extract_deaths` service execution with
      mocked subprocess output.
- [x] 5.2 Move death extraction orchestration into a Python-callable service
      while preserving the existing persistence function.
- [x] 5.3 Update `extract_deaths` management command to delegate to the service
      and preserve CLI behavior.
- [x] 5.4 Run focused death extraction tests.
- [x] 5.5 Create `/tmp/sirhosp-slice-S5-report.md` with required before/after
      evidence.

## 6. Slice S6 - Death persistence hardening

- [x] 6.1 Add tests proving repeated death extraction persistence does not
      duplicate individual records.
- [x] 6.2 Add tests proving empty death output persists a successful zero-count
      result.
- [x] 6.3 Harden death persistence with the smallest safe
      transaction/idempotency changes required by the tests.
- [x] 6.4 Run focused death persistence tests.
- [x] 6.5 Create `/tmp/sirhosp-slice-S6-report.md` with required before/after
      evidence.

## 7. Slice S7 - Change-level validation and documentation handoff

- [x] 7.1 Add or adjust tests that verify service executions preserve
      `IngestionRun` and stage metric observability for admissions and deaths.
- [x] 7.2 Verify commands still expose the existing `--date`, `--start-date`,
      and `--end-date` arguments.
- [x] 7.3 Run the relevant containerized validation commands for this change.
- [x] 7.4 Update OpenSpec checkboxes for completed tasks and confirm markdown
      lint passes for changed `.md` files.
- [x] 7.5 Create `/tmp/sirhosp-slice-S7-report.md` with final validation
      evidence and a handoff note for Change 2.

## 8. Slice S8 - Safe failure hardening and period metadata

- [x] 8.1 Add regression tests proving timeout failures do not expose source
      credentials in the result, `IngestionRun`, or stage metric details.
- [x] 8.2 Add regression tests proving service results preserve both parsed
      `target_start` and `target_end` for period extraction requests.
- [x] 8.3 Add regression tests proving unexpected exceptions after run creation
      mark the linked `IngestionRun` as failed instead of leaving it running.
- [x] 8.4 Harden admission and death service failure paths with the smallest
      safe changes required by the tests.
- [x] 8.5 Run focused validation for the hardened services and OpenSpec files.
- [x] 8.6 Create `/tmp/sirhosp-slice-S8-report.md` with before/after evidence
      and final archive readiness notes.
