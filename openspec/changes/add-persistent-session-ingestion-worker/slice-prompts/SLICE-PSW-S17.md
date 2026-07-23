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

## Final Corrective Appendix (PSW-S17 final closure)

The second corrective appendix left two integration tests asserting the
pre-S17 unsafe passthrough behavior and kept a hybrid sanitization policy
that still persisted ``str(exc)`` for typed ``ExtractionError`` subclasses.
An audit identified ten additional defects (D1-D10) that are corrected in
this final closure so PSW-S17 can be marked complete.

### D1: `click_evolucao` typed timeouts

`click_evolucao` now uses `_raise_required_action_error` for both its
``wait_for`` and ``click`` exception handlers. A real Playwright timeout
becomes a typed ``NavigationTimeoutError`` (not a generic
``NavigationError`` with a raw cause chain).

### D2: optional probe vs terminal timeout

`select_ascending_order` now probes presence via a non-blocking
``_locator_count()`` before interacting. When the select is absent, the
function is a documented no-op. When it IS present, a Playwright timeout
from its ``wait_for`` or ``evaluate`` raises a typed
``NavigationTimeoutError`` instead of being swallowed as optional absence.

### D3: `PlaywrightSessionHandle` typed timeouts and sanitized logs

`get_page_html`, `click_selector`, and `get_tab_classes` now propagate a
typed ``ExtractionTimeoutError`` on a real Playwright timeout. Non-timeout
failures keep their legacy fallback (empty string / empty list / no-op)
with constant sanitized log messages — no raw exception object, traceback,
URL, selector, or ``exc_info=True``. All cleanup paths (``shutdown``,
``restart_browser``, ``close_last_non_root_tab``, ``ensure_current_page``)
use constant sanitized logs.

### D4: strict normalized sanitization

`safe_error_message` and `safe_error_type` in `run_lifecycle.py` derive
text solely from the normalized failure category. No ``str(exc)`` is
persisted for ANY exception class — not even typed ``ExtractionError``
subclasses. ``error_type`` is always the normalized category, never a
dynamic class name. This is the single source of truth consumed by both
worker commands for run, attempt, and stage error fields.

### D5-D6: corrected integration contracts

`test_json_is_string_instead_of_array_causes_run_failure` now writes the
bad JSON payload to the real ``--admissions-output`` path and asserts
``failure_reason=invalid_payload``. `test_ingestion_persistence_stage_failed`
now asserts the normalized category/type and proves an injected sentinel
appears nowhere persisted.

### D7-D9: cross-worker matrix and sentinel coverage

The matrix now compares exact normalized stage details (``error_type``,
``error_message``) for all five categories through both workers. Batch
closure parity (drained terminal closes as failed; active sibling stays
open) is tested through both commands. Sentinel assertions cover run,
attempt, stage, stdout, stderr, and every log record.

### D8: command-level persistent PDF timeout

A new test drives the real chain (persistent command ->
``PersistentExtractionAdapter`` -> ``RealHandleBridge`` ->
``EvolutionPdfFlow``) with a synthetic browser-like fake whose
``context.request.get`` raises the public real
``playwright.sync_api.TimeoutError``. The timeout propagates as
``EvolutionPdfTimeoutError`` and records ``failure_reason=timeout``,
``timed_out=True`` end to end.

### D10: report accuracy

The report distinguishes genuine behavioral RED at source/persistence
boundaries from implementation-detail changes, records exact baseline
counts, and claims only behavior proved by tests or inspection.

## Post-ce2c494 Corrective Appendix (PSW-S17 final evidence closure)

The `ce2c494` commit was pushed while source-timeout and evidence
requirements remained incomplete. Independent reproduction with the
public real `playwright.sync_api.TimeoutError` identified six additional
defects (D11-D16) that are corrected in this closure.

### D11: ensure_search_screen present-element timeouts

`ensure_search_screen()` now uses a non-blocking `_locator_count()` probe
for optional POL-menu/dashboard discovery. Once an element is positively
present, its click and the post-click readiness wait route through
`_raise_required_action_error`, so a real Playwright timeout becomes a
typed `NavigationTimeoutError` — not a swallowed fallback miss.

### D12: PDF report-content timeout

`EvolutionPdfFlow._resolve_pdf_url()` and
`RealHandleBridge._resolve_pdf_url_from_report_page()` detect a real
Playwright timeout from `page.content()` and raise
`EvolutionPdfTimeoutError` instead of substituting empty HTML. The
bridge action-flow caller re-raises the typed timeout instead of
catching generic `Exception` and continuing.

### D13: demographics field-read timeout

`read_demographic_fields()` detects a Playwright timeout from
`Frame.evaluate()` and raises `NavigationTimeoutError`. Non-timeout
evaluation failures stay ordinary `NavigationError`.

### D14: strict PDF deadline

`EvolutionPdfFlow.extract()` uses a single monotonic deadline
(`_deadline_s` / `_remaining_ms` / `_bound_ms`). The caller `timeout` is
an UPPER BOUND: a 5-second caller budget never yields a 120-second
download. Every phase (date fills, generate click, report wait, content
read, download) receives a strictly-positive bounded timeout no greater
than the remaining budget. Expiration raises `EvolutionPdfTimeoutError`.

### D15: exact cross-worker matrix

The main matrix now compares exact normalized run/attempt error messages
(equal to `safe_failure_text(expected_reason)`), stage metric
`error_type`/`error_message`, batch status, and `FinalRunFailure` fields
(batch_id, run_id, patient_record, intent, attempts_exhausted,
failed_at). Both retryable and terminal modes are exercised through both
worker commands.

### D16: complete sentinel coverage

Every injected sentinel is asserted absent from run error_message,
latest-attempt error_message, every stage `details_json`, command
stdout, command stderr, and every captured log record. The
current-worker subprocess test now checks stderr sentinel against
command stderr (not just stdout). The persistent and integration tests
capture stdout, stderr, and logs.

## Post-cbf50c1 Final Truthful Closure Appendix

The `cbf50c1` commit was pushed while two confirmed defects (D17, D18)
remained open and required test evidence (D19) and OpenSpec/report
truthfulness (D20) were incomplete. This appendix records the exact
implemented semantics after the post-cbf50c1 closure and supersedes the
stronger-than-evidence wording of the D12/D14 entries above.

### D17: bounded PDF source interactions (corrects D12/D14)

The PDF URL-resolution path MUST NOT call the unbounded `page.content()`
(this corrects the D12/D14 entries above, which only detected a
`page.content()` timeout after the fact instead of bounding the read).

- `EvolutionPdfFlow._resolve_pdf_url()` and
  `RealHandleBridge._resolve_pdf_url_from_report_page()` both delegate to
  ONE shared resolver, `resolve_pdf_url_from_page()`, in
  `persistent_evolution_pdf.py`.
- The resolver reads the `<object type="application/pdf">` `data`
  attribute through a bounded `locator.get_attribute("data",
  timeout=...)` call, never through `page.content()`.
- One monotonic deadline (`_deadline_s` / `_remaining_ms` / `_bound_ms`)
  governs every phase of `extract()` and the bridge action flow. The
  caller `timeout` is an UPPER BOUND: a 5-second budget never yields a
  120000 ms download or report wait. Every phase receives a
  strictly-positive bounded timeout no greater than the remaining budget.
- Deadline expiry before/after any non-timeout-capable operation raises
  `EvolutionPdfTimeoutError`. A positively present PDF object whose
  bounded read times out raises `EvolutionPdfTimeoutError` with a constant
  sanitized message. A genuinely absent object remains an absence, but
  the deadline is checked before converting absence to a generic
  missing-PDF error.
- The dead `_derive_download_timeout_ms()` helper is removed; the legacy
  `download_timeout_ms = max(120_000, timeout*1000)` bridge calculation is
  replaced with the shared bounded deadline.
- The shared deadline is enforced only at the source boundary via typed
  outer exceptions; no threads, signals, subprocesses, second Playwright
  instance/browser/context, or second login are introduced.

### D18: strict sanitization of all persistent-worker surfaces

No arbitrary `str(exc)`, dynamic exception class, URL, selector,
credential, cookie, patient record, admission key, raw HTML, subprocess
preview, stdout, or stderr reaches run/attempt/stage error text, command
stdout/stderr, logger messages, `CommandError` text, or
`__cause__`/`__context__` at sanitized boundaries:

- persistent command teardown emits a constant sanitized warning
  (`_TEARDOWN_FAILURE_MESSAGE`), never `{exc}`;
- startup database retry emits a constant sanitized warning
  (`_STARTUP_DB_RETRY_MESSAGE`) plus the safe retry-delay value, never
  `exc.__class__.__name__` or `{exc}`;
- credential and bootstrap failures raise a constant `CommandError`
  (`_CREDENTIAL_RESOLUTION_MESSAGE` / `_BOOTSTRAP_FAILURE_MESSAGE`)
  raised OUTSIDE the `except` handler so Python does not auto-link the
  raw exception as `__context__` (both `__cause__` and `__context__` are
  `None`);
- the bridge wraps `choose_overlapping_admissions` navigation failures
  with `EvolutionPdfError(...) from None` (the previous `from exc` chain
  is removed);
- the five-category normalized taxonomy and current-worker behavior are
  preserved.

### D19: complete typed-timeout and adversarial evidence

Added deterministic tests using the public real
`playwright.sync_api.TimeoutError`: dashboard post-click readiness
timeout; PDF object bounded attribute-read timeout (flow + bridge);
full command -> adapter -> bridge -> `EvolutionPdfFlow` chain for both
URL-resolution and download timeouts. Added unconditional adversarial
dealine tests (trap page proves `page.content()` is not called; a
5-second budget never sends 120000 ms; elapsed work reduces later
timeouts; expiry before report wait/download raises typed timeout and
skips later phases; a fake operation that overruns the clock raises
typed timeout rather than `invalid_payload`). The cross-worker matrix
now INDEPENDENTLY asserts exact attempt/stage `error_type` and
`error_message` against `safe_failure_text(expected_reason)` on BOTH
workers (not only worker-to-worker equality).

### D20: truthful OpenSpec and report

Tasks 17.3 through 17.5 are complete only because their literal
contracts now pass: every persistent source timeout records
`failure_reason=timeout` and `timed_out=True`; sanitized errors and
current-worker behavior are preserved; official validation and the
report are green. The earlier D12/D14 wording that claimed a bounded
"content read" is corrected above to the implemented bounded object
attribute read. Sentinel coverage is now complete for URL, cookie,
credential, patient record, admission key, selector, stdout, and stderr
across all applicable surfaces. PSW-S18 remains untouched.

## Post-31dd3c0 Verification Closure Appendix (D21-D25)

This appendix supersedes earlier wording in D17/D18/D20 that overstated the
implementation. The implemented guarantee is stated exactly below; nothing
stronger is claimed.

### D21: one deadline through response handling and PDF processing

`EvolutionPdfFlow.extract()` and the bridge action flow share ONE monotonic
deadline. It is now observed (not only computed) at every later boundary:

- the shared `deadline_s` (not only a derived timeout integer) is passed into
  the download helpers (`_download`, `_download_pdf`);
- the deadline is checked immediately after `request.get()` returns, and
  immediately before and after `response.body()`;
- the deadline is checked after PDF text extraction and after normalization
  (the post-body check also serves as the pre-extraction boundary, so no
  duplicate adjacent check is added);
- a fake/implementation that ignores its supplied timeout and overruns the
  deadline is caught at the next boundary and raises
  `EvolutionPdfTimeoutError` (a typed timeout) with a constant sanitized
  message; it never returns success and never becomes `invalid_payload`,
  `source_unavailable`, or a generic `EvolutionPdfError`;
- a public real `playwright.sync_api.TimeoutError` from `request.get()` or
  `response.body()` becomes `EvolutionPdfTimeoutError` with no raw
  URL/cookie/cause/context text.

Boundary checks detect and classify an overrun AFTER a non-timeout-capable
local/cached operation (body read, PyMuPDF parse, normalization) returns;
they do NOT interrupt that operation mid-call. This is therefore NOT a
literal hard wall-clock bound. The timeout-capable Playwright calls
(`request.get`, `response.body`, locator attribute reads) receive a strictly
positive bounded timeout no greater than the remaining budget; no operation
receives `timeout=0`; elapsed work reduces every later timeout.

### D22: bridge overlap wrapper has no raw cause/context

The earlier `from None` inside the `except NavigationError` handler only
suppressed *display* of the context; the raw `NavigationError` reference was
still attached as `__context__`. The wrapper is now raised OUTSIDE the
handler (flag-then-raise), so BOTH `__cause__` and `__context__` are `None`,
and the constant message contains no admission, date, patient, selector,
URL, or raw exception text. The flow/bridge download wrappers are likewise
raised outside their handlers.

### D23: no patient identifier in command stdout

The successful admissions-only auto-enqueue message no longer prints
`patient.patient_source_key`. Safe operational run IDs (`demo_run.pk`,
`full_sync_run.pk`) and constant text remain. No patient/admission value
reaches stdout/stderr.

### D24: complete evidence

Added tests using a controlled monotonic clock against the real `extract()`
and bridge methods: request-receives-bounded-timeout; request-ignores-timeout
overrun caught before body; response-body overrun caught after body; PDF-text
extraction and normalization overruns caught at the next boundary (and later
phases skipped); public real Playwright body timeout -> typed timeout with no
sentinel/cause/context. The cross-worker matrix now INDEPENDENTLY asserts
stage `started_at`/`finished_at` on BOTH workers. Distinct admission-key and
selector sentinels are injected at realistic boundaries (snapshot
`admissionKey`; selector carried by a Playwright locator-timeout error) and
asserted absent from every run/attempt/stage/stdout/stderr/log surface.

### D25: truthful OpenSpec and report

Earlier claims that "every PDF phase is governed by the deadline", that a
"literal wall-clock hard bound" is enforced, and that `response.body()` was
"guarded before and after" are corrected above to the implemented
bounded-call + before/after boundary-check semantics. The report now
contains actual before/after code fragments for every changed versioned file.
Tasks 17.3-17.5 remain checked only because their literal contracts now pass.
PSW-S18 remains untouched.
