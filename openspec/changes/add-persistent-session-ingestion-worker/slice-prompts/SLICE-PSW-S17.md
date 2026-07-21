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

## Corrective Appendix (PSW-S17 corrective closure)

The original prompt above contained two internally inconsistent constraints
that blocked a correct closure: a six-file cap and a blanket
"browser-navigation" prohibition, both incompatible with the requirement
that every persistent navigation, wait, report, and download timeout be
typed at the source boundary. This appendix authorizes the single
exception and records the expanded file cap.

### Authorized exception to the browser-navigation prohibition

Typed timeout propagation and error-message sanitization may touch the
following source boundaries, but only to:

- raise a typed domain timeout (`NavigationTimeoutError`,
  `EvolutionPdfTimeoutError`, or `ExtractionTimeoutError`) where the
  current code returns `False`, returns `[]`, swallows the timeout into a
  generic `ExtractionError`/`EvolutionPdfError`, or `continue`s;
- re-raise typed timeouts through broad `except` clauses instead of
  wrapping them;
- replace URL/patient-record/raw-exception text in logs and error messages
  with constant sanitized strings.

This explicitly forbids selector redesign, new navigation actions, new
browser/context launches, subprocesses, second logins, and any change to
navigation sequencing, clinical persistence, counters, cleanup policy, or
restart policy.

### Expanded file cap

The six-file cap is replaced by a maximum of **18 versioned files**,
including OpenSpec artifacts. The expected files are listed in the
corrective closure prompt (`/tmp/sirhosp-slice-PSW-S17-correction-prompt.md`).
Exceeding 18 requires `Status: INCOMPLETE`.

### Classifier contract

The shared `classify_failure_reason` MUST NOT walk `__cause__`/`__context__`
or reinterpret raw Playwright exceptions (the previous chain walker changed
the current worker's pre-S17 taxonomy and is removed). Persistent source
boundaries are the sole owners of typed outer-exception conversion.

### Ownership boundary

PSW-S17 owns the typed persistent timeout invariant delivered here.
PSW-S20 and PSW-S22 may harden selectors, required actions, HTTP/PDF
validation, and live flow behavior, but MUST preserve and reverify the
typed outer-exception contract rather than claim a new owner.

## Second Corrective Appendix (PSW-S17 second closure)

The first corrective appendix authorized source-boundary typed-timeout
propagation and an 18-file cap. An audit of the resulting commit
(`b7fee73`) established that several required-action Playwright timeouts
were still untyped, persisted error text still stored arbitrary
`str(exc)`, and `playwright_extractor.py` still embedded `patient_record`
and subprocess previews in lifecycle error messages. This second appendix
records the additional rules.

### Real Playwright timeout type (R1)

`is_playwright_timeout_error()` MUST use `isinstance()` against the real
public `playwright.sync_api.TimeoutError` (lazy import, no browser
launch). Class-name/module-prefix duck typing is removed. Tests raise the
real type; no forged `__module__`.

### Optional probe vs terminal timeout (R2)

- An optional element that is absent is detected with a non-blocking
  presence probe (`count()`) and remains a documented no-op.
- An internal short polling wait may continue only while a separate
  whole-operation budget is still active.
- Expiration of the whole-operation budget raises a typed timeout.
- Once a required element is positively present, a Playwright timeout
  from its `wait_for`/`click`/`fill`/`goto`/report wait/download action
  raises a typed domain timeout.
- A raw Playwright timeout must never become successful extraction,
  generic `NavigationError`, generic `EvolutionPdfError`, `False`, `[]`,
  or `continue`.

### Sanitized navigation conversion (R3)

A small helper in `legacy_navigation.py`
(`_raise_required_action_error`) maps a caught exception to either a
`NavigationTimeoutError` with one constant message (Playwright timeout)
or a constant sanitized `NavigationError` (other required-action
failures), using `from None` to suppress the raw chain. Equivalent
typed conversion is applied in `EvolutionPdfFlow` and
`PlaywrightSessionHandle`.

### Category-normalized persisted text (R4)

Lifecycle DB text is normalized by category via
`safe_error_message(exc, reason)` and `safe_error_type(exc, reason)` in
`run_lifecycle.py`:

- typed domain exceptions (`ExtractionError` subclasses) carry sanitized
  constant messages from source boundaries, so `str(exc)` is safe to
  persist;
- unexpected exceptions (`ValueError`, `RuntimeError`, raw Playwright
  errors that escaped a source boundary) are replaced with the stable
  category constant from `safe_failure_text(reason)`.

Command stdout/stderr failure lines use `reason=<category>`, never
`str(exc)`. `safe_failure_text` is a real consumer-backed helper.

### Current-worker extractor sanitization (R5)

`playwright_extractor.py` no longer interpolates:

- `patient_record` into timeout messages;
- subprocess stdout/stderr previews into exceptions;
- raw caught exception text.

Only the non-sensitive return code is retained. Extraction taxonomy and
command behavior are unchanged.

### Identifier-free legacy messages (R6)

`open_internacao_detail`, bridge per-admission logs, and PDF
normalization logs no longer echo `admission_key`, URLs, selectors, raw
dates, or raw exception text. Constant sanitized messages are used.

### Remaining INCOMPLETE blocker

Two integration tests outside the second-closure file cap
(`tests/integration/test_worker_lifecycle.py::test_ingestion_persistence_stage_failed`
and
`tests/integration/test_connector_failure_regression.py::test_json_is_string_instead_of_array_causes_run_failure`)
assert the pre-S17 unsafe passthrough behavior that R4/R5 remove. They
must be updated to assert classification/category rather than message
passthrough in a separate change. Until then tasks 17.3-17.5 remain
unchecked and the slice is INCOMPLETE.
