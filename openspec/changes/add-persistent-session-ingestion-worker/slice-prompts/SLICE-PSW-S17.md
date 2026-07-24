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

## Authoritative PSW-S17 Closure Contract

This single section is the authoritative PSW-S17 closure record. It
supersedes and replaces the earlier chain of corrective appendices (the
D-numbered corrective rounds and their appendices); git history preserves
those rounds, so they are removed from the active file. State only the
final accepted behavior below; nothing stronger is claimed.

### Normalized failure categories

Failures normalize to exactly five categories: `source_unavailable`,
`invalid_payload`, `timeout`, `validation_error`, and
`unexpected_exception`. The shared classifier
(`classify_failure_reason` / `timed_out`) inspects only the typed
outer exception; it does NOT walk `__cause__`/`__context__` and does NOT
reinterpret raw Playwright exceptions. Source boundaries are the sole
owners of typed outer-exception conversion (`NavigationTimeoutError`,
`EvolutionPdfTimeoutError`, `ExtractionTimeoutError`).

### Timeout classification

A timeout failure records `failure_reason="timeout"` and `timed_out=True`
on both the run and the latest attempt, for both the current and the
persistent worker. A raw Playwright timeout that reaches a boundary
un-typed is NOT reinterpreted as a timeout by the classifier.

### Cross-worker lifecycle parity

The current and persistent workers share observable retry/terminal
lifecycle semantics: attempt number/status/timestamps, retry backoff,
`next_retry_at`, `FinalRunFailure` (exactly one row on terminal, with
matching fields), and batch closure (drained terminal batches close as
`failed`; batches with active siblings stay `running`). This is verified
through both worker commands for all five categories and both
retryable/terminal modes, asserting expected values independently per
worker (worker-to-worker equality is only supplementary).

### Observable-surface sanitization (frozen policy)

No sensitive source value (URL, cookie, credential, patient record,
admission key, selector, raw HTML, subprocess preview) and no arbitrary
`str(exc)` may appear on an observable or persisted surface: run, attempt,
or stage error fields; logs; command stdout/stderr; `CommandError` text;
or a traceback rendered through normal Python exception formatting.

This policy is evaluated ONLY on those surfaces. The following are
explicitly accepted:

- `raise SanitizedError(CONSTANT_MESSAGE) from None` is the accepted
  form; normal Python context suppression applies.
- the internal suppressed `__context__` object may remain attached when
  `__suppress_context__` is True;
- internal `__context__` is NOT an acceptance surface unless application
  code logs, serializes, displays, or otherwise re-emits it.

Universal `__cause__`/`__context__` absence is therefore NOT required and
NOT claimed. Observable sanitization tests are preserved and not weakened.

### Deadline semantics (frozen, cooperative)

The deadline guarantee is bounded timeout-capable calls plus monotonic
boundary checks:

- timeout-capable Playwright operations receive a strictly positive
  timeout no greater than the remaining caller budget;
- `response.body()` does NOT receive an explicit timeout argument;
- operations without an explicit timeout are checked at the documented
  monotonic boundaries before/after or immediately after return;
- an overrun is converted to `EvolutionPdfTimeoutError` at the next
  boundary;
- these checks do NOT interrupt a non-timeout-capable operation mid-call.

NO literal hard wall-clock bound is claimed or enforced. No thread,
signal, subprocess, second browser/context, or second login is
introduced.

### Runtime PDF URL resolution

Runtime PDF URL resolution uses the shared `resolve_pdf_url_from_page()`
helper reading the `<object>` `data` attribute through a bounded locator
attribute read. `page.content()` is absent from runtime PDF URL
resolution.

### Command output

The persistent admissions-only auto-enqueue output does NOT print any
patient identifier; safe operational run IDs and constant text remain.

### Scope boundary

PSW-S18 (Internal legacy-tab cleanup and recovery) and all later slices
are out of scope for PSW-S17 and remain untouched. Tasks 17.3-17.5 are
complete only because their literal contracts pass under this frozen
contract.
