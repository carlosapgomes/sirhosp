# SLICE PSW-S17: Failure and Attempt Lifecycle Parity

## Handoff for a Context-Zero Implementer

Implement only PSW-S17 after PSW-S16 is committed. Read `AGENTS.md`, project
context, all change artifacts, PSW-S14-S16 reports, both worker commands,
extractor errors, subprocess timeout mapping, `IngestionRunAttempt`,
`FinalRunFailure`, batch closure, stale recovery, and retry integration tests.
Start with a clean branch.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, branch, and clean status.
2. Add the requirement matrix to the report.
3. Run official unit baseline before edits and record exact exit/summary.
4. Add parity tests first and capture expected RED.
5. Implement minimum GREEN; do not rewrite both commands wholesale.
6. Run inspections and interpret every classification path.
7. Run all official validation commands.
8. Only when complete: update PSW-S17, report, commit, push, and stop.

Missing evidence or any nonzero gate means `Status: INCOMPLETE`.

## Objective

Make persistent run failures externally equivalent to current-worker failures,
including typed timeout classification, attempts, retry scheduling,
`FinalRunFailure`, and batch closure.

## Requirements

- **R1:** Parameterize identical current/persistent failure scenarios for
  validation, source unavailable, invalid payload, timeout, and unexpected
  exception.
- **R2:** Map every persistent navigation, wait, report, and download timeout to
  `ExtractionTimeoutError` or an equivalent shared typed timeout.
- **R3:** Record `failure_reason="timeout"` and `timed_out=True` on both run and
  attempt for timeout failures.
- **R4:** Preserve current retry backoff, `next_retry_at`, attempt number/status,
  timestamps, and error sanitization.
- **R5:** On attempts exhausted, create exactly one `FinalRunFailure` with the
  same conditions and fields as the current worker.
- **R6:** Close or retain batches under the same active/terminal rules.
- **R7:** Share only cohesive classification/finalization helpers needed to
  prevent drift; keep extraction-specific cleanup outside them.
- **R8:** Keep current-worker output and behavior unchanged.

## Expected Scope

Target maximum: 6 versioned files including `tasks.md`.

Expected:

- one small shared lifecycle helper if characterization justifies it;
- both commands for delegation;
- extractor error types only if needed;
- focused unit/integration tests;
- `tasks.md`.

Forbidden: models/migrations, browser navigation, demographics fields,
admission/evolution persistence, templates, rollout docs.

## TDD

### RED

Add cross-worker tests for all R1 categories, retryable and terminal attempts,
timeout fields, one-and-only-one `FinalRunFailure`, and batch state. Initial RED
must expose persistent timeout or final-failure divergence.

### GREEN

Align classification/finalization with minimal shared code or exact delegation.
Preserve public messages unless sanitization requires safer text.

### REFACTOR

Remove duplicate divergent rules. Do not introduce a general job framework.

## Mandatory Inspection Checks

```bash
rg -n "ExtractionTimeoutError|SubprocessTimeoutError|timed_out|failure_reason" \
  apps/ingestion/management/commands apps/ingestion/extractors
rg -n "FinalRunFailure|next_retry_at|attempt_number" \
  apps/ingestion/management/commands apps/ingestion
rg -n "except Exception" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
```

Map each broad catch to its resulting typed classification in the report.

## Binary Success Criteria

- [ ] Current/persistent failure matrix matches for all categories.
- [ ] All source timeout paths set timeout fields correctly.
- [ ] Retry and terminal attempts contain correct timestamps/status.
- [ ] Exactly one final-failure row is created when appropriate.
- [ ] Batch behavior matches current worker.
- [ ] No sensitive payload appears in stored/logged errors.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Can a Playwright timeout still become `source_unavailable` or
   `invalid_payload`?
2. Can terminal failure omit or duplicate `FinalRunFailure`?
3. Can a retry close its batch prematurely?
4. Did shared code absorb browser cleanup responsibilities?
5. Is current-worker behavior covered before and after refactor?

Required answers: no, no, no, no, yes.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S17-report.md` with matrix, baseline, RED/GREEN,
full failure-parity table, snippets, inspections, commands and exit codes,
changed files, risks, and verifier handoff.

Final prompt: implement only PSW-S17. Any unclassified timeout, missing terminal
record, current-worker regression, or absent gate makes the slice incomplete.
