# Add Retry to Historical Recovery Tasks

## 1. Baseline and Planning

- [x] 1.1 Start from a clean working tree; commit or stash unrelated changes
  first
- [x] 1.2 Create or switch to branch `change/add-retry-to-historical-recovery`
- [x] 1.3 Review current recovery orchestration and command tests
- [x] 1.4 Record baseline behavior in `/tmp/sirhosp-slice-RTRY-S1-report.md`

## 2. Orchestrator Retry Semantics

- [x] 2.1 Add retry configuration to the recovery plan with default 3 retries
- [x] 2.2 Execute retry rounds only after the current batch/round completes
- [x] 2.3 Retry only failed date/extractor steps from the previous round
- [x] 2.4 Ensure successful steps are never retried
- [x] 2.5 Preserve dry-run behavior with no service calls and no retry execution
- [x] 2.6 Preserve fail-fast behavior with no retry rounds after first failure
- [x] 2.7 Preserve credential-safe unexpected exception handling

## 3. Command Interface and Output

- [x] 3.1 Add `--max-retries` with default `3`
- [x] 3.2 Reject negative retry values before extraction
- [x] 3.3 Print compact retry round output for operator visibility
- [x] 3.4 Ensure final exit status reflects final failed steps after retries

## 4. Tests

- [x] 4.1 Test failed steps are retried after the full initial batch
- [x] 4.2 Test retry success makes the final result successful
- [x] 4.3 Test failures after retry exhaustion still exit non-zero
- [x] 4.4 Test successful steps are not retried
- [x] 4.5 Test `--max-retries 0` preserves no-retry behavior
- [x] 4.6 Test `--dry-run` and `--fail-fast` do not run retry rounds
- [x] 4.7 Test CLI parsing and output for retry attempts

## 5. Documentation and Validation

- [x] 5.1 Update README operator documentation if command flags/output changed
- [x] 5.2 Run focused recovery unit tests
- [x] 5.3 Run `./scripts/test-in-container.sh check`
- [x] 5.4 Run `./scripts/test-in-container.sh unit`
- [x] 5.5 Run `./scripts/test-in-container.sh lint`
- [x] 5.6 Run `./scripts/test-in-container.sh typecheck`
- [x] 5.7 Run markdown lint for changed Markdown files
- [x] 5.8 Run OpenSpec strict validation for
  `add-retry-to-historical-recovery`
- [x] 5.9 Update `/tmp/sirhosp-slice-RTRY-S1-report.md` with final evidence
- [x] 5.10 Commit with a clear message and stop
