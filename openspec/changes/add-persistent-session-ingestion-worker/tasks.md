# Persistent Session Ingestion Worker Tasks

## 0. Branch isolation

- [x] 0.1 Verify or create branch
  `feature/add-persistent-session-ingestion-worker` before coding.
- [x] 0.2 Keep all slices for this feature on that branch with no unrelated
  fixes, refactors, or other OpenSpec changes.
- [x] 0.3 If committing planning artifacts, explicitly force-add this ignored
  OpenSpec change directory on the feature branch.

## 1. PSW-S1: Session DOM policy primitives

- [x] 1.1 Add failing unit tests for parsing `#tempoSessao` into remaining
  seconds, including malformed and missing counter cases.
- [x] 1.2 Add failing unit tests for renewal-popup detection using
  `#casca_renovasession[aria-hidden="false"]` and the semantic button.
- [x] 1.3 Add failing unit tests for tab cleanup decisions: root tab preserved,
  last non-root tab selected, unsafe states flagged for recovery, and tab close
  never classified as session renewal.
- [x] 1.4 Implement pure functions or value objects for countdown parsing,
  popup state, and tab cleanup policy with no Playwright dependency.
- [x] 1.5 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S1-report.md`.

## 2. PSW-S2: Persistent legacy session controller

- [x] 2.1 Add tests with fake Playwright-like objects for readiness, renewal by
  opening a safe tab, defensive popup handling, tab cleanup, relogin fallback,
  and restart-required decisions.
- [x] 2.2 Implement a persistent session controller using PSW-S1 policies,
  centralized selectors, and a configurable safe-tab opener for renewal.
- [x] 2.3 Add configurable thresholds for max jobs, max lifetime, and
  consecutive renewal/login/tab-cleanup failures.
- [x] 2.4 Ensure profile/cache handling uses an exclusive per-process path and
  avoids destructive cleanup while the browser is running.
- [x] 2.5 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S2-report.md`.

## 3. PSW-S3: Admissions persistent extraction adapter

- [x] 3.1 Add tests for an adapter exposing `get_admission_snapshot(...)` with
  safe session checkpoints around source-system actions.
- [x] 3.2 Implement the first production-usable adapter path for admissions
  snapshot capture with existing parser or normalization behavior where safe.
- [x] 3.3 Ensure failures map to existing typed extraction exceptions without
  leaking credentials, cookies, screenshots, or raw patient artifacts.
- [x] 3.4 Add or adjust tests for successful admissions-only processing through
  the adapter with fake legacy responses.
- [x] 3.5 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S3-report.md`.

## 4. PSW-S4: New persistent-session worker command

- [x] 4.1 Add tests for `process_ingestion_runs_persistent_session` claiming
  queued runs safely while current worker semantics remain available.
- [x] 4.2 Implement the command with loop, sleep, headless options, labels,
  heartbeat, graceful shutdown, and session readiness before claim.
- [x] 4.3 Wire admissions-only processing through the persistent adapter while
  preserving attempts, statuses, stages, retries, failures, and batch closure.
- [x] 4.4 Ensure tab cleanup runs after admissions-only success and recoverable
  data failures, and unsafe cleanup triggers recovery before the next claim.
- [x] 4.5 Ensure the session handle supplies the PSW-S3 snapshot container
  contract, propagates timeout, and encodes real URL parameters when used.
- [x] 4.6 Add tests proving current `process_ingestion_runs` remains executable
  with unchanged command-line behavior.
- [x] 4.7 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S4-report.md`.

## 5. PSW-S5: Full-sync persistent evolution extraction

- [x] 5.1 Add tests for the real Playwright handle boundary and exclusive
  browser profile wiring, or stop with a blocker proposing a dedicated wiring
  slice before full-sync.
- [x] 5.2 Add tests for persistent `extract_evolutions(...)` over planned gap
  windows, including session checkpoints and timeout propagation.
- [x] 5.3 Implement real handle wiring and full-sync evolution extraction
  through the persistent adapter using existing normalization and persistence
  semantics.
- [x] 5.4 Add tests that full-sync preserves admissions-first behavior, gap
  planning, extraction, counters, and failure semantics.
- [x] 5.5 Ensure job-tab opening is the only proactive counter-reset signal;
  cleanup after success/errors must not be treated as renewal evidence.
- [x] 5.6 Ensure the command remains clearly non-rollout-ready if the real
  handle cannot be completed in this slice.
- [x] 5.7 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S5-report.md`.
- [x] 5.8 **RESOLVED IN CODE (PSW-S9; live validation remains):** Shared
  evolution ingestion exists in
  `apps.ingestion/evolution_ingestion.py` (PSW-S7) and the persistent worker's
  `_process_full_sync` is now wired to it (PSW-S8), so `full_sync` runs persist
  real admissions + events with full parity (including census ward/bed
  backfill via the shared `backfill_admission_ward_from_census` service).
  The real-handle container contract is resolved in code by
  `RealHandleBridge` (PSW-S9). Live validation, real bootstrap, and real
  evolution PDF flow remain scoped to PSW-S10/PSW-S11 before any production
  rollout.

## 6. PSW-S6: Runtime rollout and A/B observability

- [x] 6.1 Document current status prominently: persistent worker is not
  production rollout-ready until the real-handle container contract is resolved.
- [x] 6.2 Document how to run current and persistent workers side-by-side only
  as future production rollout guidance or controlled lab/staging experiment,
  with distinct `SIRHOSP_WORKER_LABEL` prefixes.
- [x] 6.3 Add deployment guidance or disabled examples for scaling both groups
  without sharing browser profile directories, guarded by rollout prerequisites.
- [x] 6.4 Document SQL or Django shell queries comparing count, success rate,
  timeout rate, queue latency, processing duration, attempts, and stale signals.
- [x] 6.5 Document tmpfs/profile/cache/RAM/swap/log checks and rollback steps.
- [x] 6.6 Run markdown lint plus relevant validation and create
  `/tmp/sirhosp-slice-PSW-S6-report.md`.

## 7. PSW-S7: Shared evolution ingestion service

- [x] 7.1 Add failing characterization tests for the current worker's evolution
  persistence behavior and counters.
- [x] 7.2 Extract `_ingest_evolutions` behavior into a shared service module
  that preserves patient upsert, admission resolution, fallback admission
  upsert, transactions, timezone handling, and event persistence.
- [x] 7.3 Update the current worker to delegate to the shared service without
  changing current command behavior.
- [x] 7.4 Keep persistent full-sync blocked in this slice; do not claim rollout
  readiness yet.
- [x] 7.5 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S7-report.md`.

## 8. PSW-S8: Real handle contract and persistent full-sync

- [x] 8.1 Add failing tests for the real handle/adapter contract using mocks or
  fakes, with no real legacy access.
- [x] 8.2 **RESOLVED IN CODE (PSW-S9):** adapt the real persistent
  handle contract so it no longer depends on fake-only synthetic containers
  from the legacy UI. `RealHandleBridge` translates representative legacy DOM
  output into the adapter contract. Live validation remains pending.
- [x] 8.3 Wire persistent `_process_full_sync` to admissions capture, gap
  planning, persistent evolution extraction, and the shared ingestion service.
- [x] 8.4 Preserve stage metrics, failure taxonomy, retry semantics, cleanup,
  recovery, timeout propagation, and counter-reset rules. Census ward/bed
  backfill parity ensured via shared `backfill_admission_ward_from_census`.
- [x] 8.5 Update runtime docs if rollout status changes; otherwise keep blockers
  explicit. (Module docstring + `docs/operations/persistent-worker-rollout.md`.
  Persistent worker remains non-rollout-ready until 8.2.)
- [x] 8.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S8-report.md`.

## 9. PSW-S9: Real handle bridge for legacy UI extraction

- [x] 9.1 Add failing tests for a bridge/translation layer that converts real
  legacy UI outputs or stable `path2.py` helper results into the persistent
  adapter's admission/evolution contract, with no real legacy access.
- [x] 9.2 Implement the bridge inside the real persistent handle or adapter
  boundary without launching a fresh browser per job and without subprocess
  execution of `path2.py`.
- [x] 9.3 Update `PlaywrightSessionHandle` so `--real-handle` can satisfy
  admissions and evolution extraction contracts against representative legacy
  HTML/download fakes.
- [x] 9.4 Preserve timeout propagation, tab cleanup, session renewal by opening
  tabs, exclusive profile behavior, and safe error taxonomy.
- [x] 9.5 Update rollout docs only if the real-handle blocker is resolved;
  otherwise keep production rollout guarded and document remaining blockers.
- [x] 9.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S9-report.md`.

## 10. PSW-S10: Safe real-legacy bootstrap smoke

- [x] 10.1 Add failing tests for `--run-id` and `--max-runs 1` manual
  validation controls.
- [x] 10.2 Add failing tests for real legacy bootstrap using mocked
  Playwright objects and sanitized credential handling.
- [x] 10.3 Implement guarded single-run claim behavior so `--real-handle`
  manual validation cannot drain the general queue.
- [x] 10.4 Implement real session bootstrap: source URL navigation, login,
  authenticated readiness via `#tempoSessao`, and sanitized failures.
- [x] 10.5 Add real URL-template configuration for admissions, evolutions, and
  safe renewal; fail before claim when required real-handle config is missing.
- [x] 10.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S10-report.md`.

## 11. PSW-S11: Persistent real evolution PDF flow

- [x] 11.1 Add failing tests for persistent evolution PDF extraction using
  fake Playwright pages/frames/downloads and synthetic anonymous PDF/text.
- [x] 11.2 Implement a minimal PDF report extraction path that reuses the
  existing persistent handle/context and never invokes subprocess or a new
  Playwright browser per job.
- [x] 11.3 Normalize PDF text into the existing evolution event contract and
  preserve PSW-S9 JSON/script and `pre.report-text` fast paths.
- [x] 11.4 Wire the PDF fallback through persistent full-sync while preserving
  shared persistence, stage metrics, retries, cleanup, and failure taxonomy.
- [x] 11.5 Keep current subprocess extractor and current worker behavior
  unchanged.
- [x] 11.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S11-report.md`.

## 12. PSW-S12: Real legacy patient/admissions navigation

- [x] 12.1 Add failing tests proving `--real-handle --run-id <id>
  --max-runs 1` no longer requires admissions/evolutions URL templates before
  starting the smoke path.
- [x] 12.2 Add failing tests for action-based patient search and admissions
  table navigation using fake Playwright page/frame objects modeled after
  `path2.py` (`#prontuarioInput`, `Pesquisa Avançada`, `Internações`,
  `frame_pol`, and `#tabelaInternacoes:resultList_data`).
- [x] 12.3 Implement a focused real legacy navigation helper/bridge path for
  admissions snapshot capture through UI actions, without subprocess,
  `path2.py` shell-out, or a new browser/context per job.
- [x] 12.4 Update the persistent real-handle command wiring so `admissions_only`
  smoke uses the action-navigation path and preserves guardrails, stage
  metrics, retries, sanitized errors, and tab-cleanup semantics.
- [x] 12.5 Keep full-sync real evolution navigation explicitly pending for
  PSW-S13; do not claim production rollout readiness.
- [x] 12.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S12-report.md`.

## 13. PSW-S13: Real legacy full-sync evolution navigation

- [x] 13.1 Add failing tests for selecting admissions overlapping a requested
  full-sync window and for sanitized failure when none is eligible.
- [x] 13.2 Add failing tests for the real evolution action sequence using fake
  Playwright page/frame objects: open details, click `Evolução`, fill
  `DD/MM/YYYY` dates, select ascending order when present, visualize report,
  and handle no-evolutions windows.
- [x] 13.3 Implement the minimal detail/evolution/PDF navigation path modeled
  after `path2.py`, reusing the already-open persistent page/context and never
  invoking subprocess, `sync_playwright()`, or a new browser/context per job.
- [x] 13.4 Wire persistent `full_sync` to the real action-navigation/PDF path
  while preserving PSW-S9 fast paths, PSW-S11 PDF normalization, shared
  persistence, stage metrics, retries, sanitized errors, and cleanup semantics.
- [x] 13.5 Keep current subprocess extractor and current worker behavior
  unchanged; keep production rollout blocked pending live validation and
  threshold tuning.
- [x] 13.6 Run relevant validation and create
  `/tmp/sirhosp-slice-PSW-S13-report.md`.

## 14. PSW-S14: Explicit supported-intent contract

- [x] 14.1 Characterize current queued intent behavior and add failing tests for
  explicit enabled dispatch of `admissions_only`, `full_sync`, and the
  `full_admission_sync` alias.
- [x] 14.2 Add failing tests proving empty, unknown, and not-yet-enabled
  `demographics_only` runs are not claimed during normal polling and explicit
  unsupported selection performs no source or clinical side effects.
- [x] 14.3 Implement explicit enabled-intent claiming and dispatch without an
  implicit `else -> full_sync` fallback or placeholder demographics handler.
- [x] 14.4 Prove production enqueue paths create explicit non-empty target
  intents and keep the current worker consuming demographics until PSW-S16
  atomically enables the persistent implementation.
- [x] 14.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S14-report.md`.

## 15. PSW-S15: Admissions-only persistence parity

- [x] 15.1 Add failing parity tests for patient/admission persistence, real
  counters, ward/bed backfill, follow-ups, attempts, stages, and batch closure.
- [x] 15.2 Reuse or extract the smallest canonical admissions orchestration so
  both workers preserve the same clinical effects without duplicated business
  logic.
- [x] 15.3 Replace fabricated persistent-worker counters with database outcomes
  and enqueue demographics/full-sync under current-worker conditions.
- [x] 15.4 Prove zero-admission and failure paths do not create false counters or
  follow-up jobs.
- [x] 15.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S15-report.md`.

## 16. PSW-S16: Persistent demographics-only end-to-end

- [x] 16.1 Add failing tests for action navigation to `Dados do Paciente`,
  `frame_pol` extraction, normalization, and persistence with synthetic data.
- [x] 16.2 Implement `demographics_only` through the already-authenticated
  persistent page/context and `upsert_patient_demographics`.
- [x] 16.3 Preserve demographics stages, attempts, timeouts, retries, heartbeat,
  extracted-field metrics, cleanup, and batch closure.
- [x] 16.4 Prove the persistent path performs no subprocess, temporary JSON,
  `sync_playwright()`, new browser/context, or second login.
- [x] 16.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S16-report.md`.

## 17. PSW-S17: Failure and attempt lifecycle parity

- [x] 17.1 Add failing cross-worker tests for timeout classification, retry
  scheduling, terminal attempts, `FinalRunFailure`, and batch closure.
- [x] 17.2 Share or align failure classification without duplicating divergent
  command-local rules.
- [x] 17.3 Ensure persistent source timeouts record `failure_reason=timeout`
  and `timed_out=True`, including navigation, report, and download timeouts.
- [x] 17.4 Preserve sanitized errors and current-worker behavior.
- [x] 17.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S17-report.md`.

PSW-S17 closure (authoritative): failures normalize to the five categories
(`source_unavailable`, `invalid_payload`, `timeout`, `validation_error`,
`unexpected_exception`); typed source timeouts
(`NavigationTimeoutError`, `EvolutionPdfTimeoutError`,
`ExtractionTimeoutError`) record `failure_reason=timeout` and
`timed_out=True`. The current and persistent workers share observable
retry/terminal lifecycle semantics (attempts, retry scheduling,
`FinalRunFailure`, and batch closure), verified through both worker
commands for all categories and modes with independent expected-value
assertions. Sanitization applies only to observable/persisted surfaces
(run/attempt/stage error fields, logs, stdout/stderr, `CommandError`
text, rendered tracebacks); `raise ... from None` is accepted and a
suppressed internal `__context__` is not a failure unless re-emitted; no
universal `__context__ is None` is required. The deadline is cooperative:
bounded timeout-capable Playwright calls plus monotonic boundary checks
(`response.body()` takes no explicit timeout); overruns are detected
after return at the next boundary — no literal hard wall-clock bound, no
thread/signal/subprocess/second browser. Runtime PDF URL resolution does
not call `page.content()`, and the persistent auto-enqueue output prints
no patient identifier. Tasks 17.3-17.5 are checked only because their
literal contracts pass. PSW-S18 remains untouched.

## 18. PSW-S18: Internal legacy-tab cleanup and recovery

- [x] 18.1 Add failing tests reproducing multiple legacy DOM tabs inside one
  Playwright Page and unsafe/ambiguous cleanup states.
- [x] 18.2 Close the last non-root PrimeFaces tab through its DOM close control,
  preserve root, and verify tab-count decrease or root restoration.
- [x] 18.3 Ensure unsafe cleanup failures are not erased by job accounting and
  force recovery before the next claim.
- [x] 18.4 Prove tab close is cleanup only and never renewal evidence.
- [x] 18.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S18-report.md`.

PSW-S18 closure (authoritative): cleanup reports exactly three observable
outcomes via `TabCleanupOutcome` (`ROOT_ONLY`, `CLOSED_AND_VERIFIED`,
`UNSAFE`) in `session_policy.py`. The concrete
`PlaywrightSessionHandle.close_last_non_root_tab()` now clicks the
centralized DOM close control (`SEL_TAB_LAST_CLOSE` =
`li.tabs-last:not(.tabs-first) a.tabs-close`) on the active page and
verifies the DOM tab count decreased or root-only state was restored within
a bounded timeout; it NEVER closes a Playwright Page (the previous
`context.pages[-1].close()` mismatch is removed). The controller's
`close_job_tab_if_present()` returns the outcome; `UNSAFE` sets a
`_recovery_required` flag and increments failure state, `mark_job_processed`
preserves it (R7), `restart_required()` surfaces it so the worker restarts
before the next claim (R6), and `reset_after_restart()` clears it. A verified
close never changes renewal evidence (R5). Cleanup is applied after success
and recoverable extraction failures for `admissions_only`,
`demographics_only`, `full_sync`, and `full_admission_sync` (R8). Cleanup
failures are sanitized (constant log messages) and never re-raised or
classified as a run timeout (R9). Inherited PSW-S17 contracts are preserved
and not re-audited.

PSW-S18-C1 corrective closure: four confirmed audit gaps closed. (1) The
concrete post-click verification is strict: a failed/empty verify read, a
reduction to zero, a removal of more than one tab, or an ambiguous resulting
state never yields `CLOSED_AND_VERIFIED` (always `UNSAFE`, Page kept alive).
(2) Root-only is recognized by class tokens (`tabs-first`, `tabs-last`,
`tabs-selected`) regardless of order or extra PrimeFaces classes. (3) All
recoverable `ExtractionError` branches for `admissions_only`,
`demographics_only`, `full_sync`, and `full_admission_sync` now run
`cleanup_after_failure()` before another claim. (4) Every protocol fake
returns a valid `TabCleanupOutcome`. A command-level proof observes
`UNSAFE -> restart_browser -> reset_after_restart -> next claim` for two
synthetic runs.

PSW-S18-C2 corrective closure: the verified state must also preserve the
root tab (`tabs-first` on the first remaining tab) or the outcome is
`UNSAFE`; the command-level proof D now asserts the full ordering
`first action < restart < reset < second claim < second action`.

## 19. PSW-S19: Restart, rebootstrap, and lifecycle configuration

- [x] 19.1 Add failing tests for authenticated rebootstrap after browser restart
  and no claim while rebootstrap is incomplete.
- [x] 19.2 Implement restart plus login/bootstrap readiness through the same
  persistent lifecycle boundary.
- [x] 19.3 Expose conservative max-jobs, max-lifetime, failure, renewal, and
  headless configuration without changing current-worker CLI behavior.
- [x] 19.4 Prove two jobs reuse one login/context and a later post-threshold job
  runs only after one controlled restart plus rebootstrap.
- [x] 19.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S19-report.md`.

PSW-S19 closure (authoritative): the adapter is the single lifecycle
boundary (`PersistentExtractionAdapter._restart_and_rebootstrap()` /
`restart_and_rebootstrap()`); it restarts the browser AND re-runs the
sanitized bootstrap/login through the `RealHandleBridge.bootstrap()` boundary
(reusing `bootstrap_legacy_session`; no duplicated credentials/selectors, no
background login thread), then requires `#tempoSessao` readiness via
`ensure_ready()` before any claim. A connected-but-blank page after restart is
NOT ready (self-eval gate 1). On rebootstrap failure (R5) recovery state is
retained (no `reset_after_restart`) so `ensure_session_ready()` retries safely
and no queued run is mutated (R4). The command's between-jobs restart now
calls `adapter.restart_and_rebootstrap()` instead of touching
session/controller directly (single lifecycle owner). The closed
configuration set is exposed through one documented CLI path
(`--max-jobs`, `--max-lifetime-seconds`, `--max-consecutive-failures`,
`--renewal-threshold-seconds`, `--headless`/`--no-headless` via
`BooleanOptionalAction`); positive ranges are validated in
`SessionControllerConfig.validate()` and re-checked by
`_validate_lifecycle_options()` before any claim (R6). The `--headless` CLI
value reaches the concrete `PlaywrightSessionHandle` (R6 proof). Profile
ownership is preserved across restart (`release_after_shutdown(remove=False)`
then `acquire()`; destructive cleanup only on shutdown) (R7). The current
worker (`process_ingestion_runs`) CLI and behavior are unchanged (R9).

PSW-S19-C1 closure (authoritative): the restart/rebootstrap boundary now
reports success and resets recovery only after authenticated readiness is
observed. `_restart_and_rebootstrap()` requires the `bootstrap()` capability
before restarting; captures `restart_browser()` and `bootstrap()` failures
with a constant sanitized warning (no exception text, URL, profile path,
credential, cookie, selector, or raw HTML); validates `#tempoSessao` via
`ensure_ready()` before calling `reset_after_restart()` exactly once; and
returns `False` without resetting on any other condition (bootstrap absent,
restart raise, bootstrap raise, or invalid marker). `ensure_session_ready()`
resolves `restart_required()` before ordinary readiness, so an old ready page
cannot bypass a pending threshold. Two compatibility corrections were made
in the command tests: the PSW-S18 fake now models the `bootstrap()`
capability (order strengthened to `restart < bootstrap < reset < second
claim`), and the no-bootstrap proof was renamed to reflect that a missing
bootstrap blocks restart (and the later run) with `restart_calls == 0`.
Audit findings A1/A2 are resolved; PSW-S17/PSW-S18 observable behavior is
preserved.

## 20. PSW-S20: Action-first real evolution dispatch

- [x] 20.1 Add a failing real-like adapter test proving the real handle reaches
  legacy action navigation without first opening a synthetic evolution URL.
- [x] 20.2 Make action navigation the real-handle path while retaining URL-based
  behavior only for explicit stubs/tests.
- [x] 20.3 Make required date filling and report waits fail safely with
  typed, sanitized timeout/error semantics instead of continuing with
  default dates. PSW-S17 corrective closure already delivers the typed
  outer-exception contract at the source boundary
  (`NavigationTimeoutError`, `EvolutionPdfTimeoutError`); this task
  hardens selectors and required actions and MUST preserve and reverify
  that contract rather than claim a new owner.
- [x] 20.4 Preserve fast paths only where they do not bypass required real
  navigation or persistence.
- [x] 20.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S20-report.md`.

PSW-S20 closure (authoritative): evolution extraction is now action-first for
the real persistent handle. Dispatch is selected by an EXPLICIT capability
(`RealHandleBridge.supports_real_evolution_actions()` returning `True`),
checked with ``is True`` so a plain ``MagicMock`` (whose auto-created
attribute call returns a truthy MagicMock) cannot switch dispatch to the
action path (R1, self-eval gate 4). The real handle calls the legacy
 evolution actions (`extract_evolutions_via_legacy_actions`) directly and
opens ZERO synthetic/direct evolution URLs (R2); the JSON/pre fast paths and
the PSW-S11 PDF fallback remain ONLY on the stub/test path, where `open_tab`
is the legitimate navigation and the container was reached legitimately
(R3/R4 of the closed scenario matrix). A real-handle JSON/pre page state no
longer bypasses required real navigation. Required date filling is hardened:
`fill_evolution_dates` returns ``True`` only when BOTH date inputs were
present and filled (aligning with `path2.open_report_for_interval`, which
treats them as required); the bridge raises a typed sanitized
`EvolutionPdfError` (constant message, raised outside the handler so no raw
`__context__` is attached) and generates NO report when the inputs cannot be
filled (R4). No-evolutions stays an empty successful list, distinct from a
typed report/download timeout that propagates unchanged through the shared
PSW-S17 taxonomy (R5); the requested `timeout` reaches the action waits and
downloads via the existing shared deadline (R6). Error/stage messages carry
no patient identifier, identifying URL, raw HTML, credential, or PDF bytes
(R7). Stub tests and the current worker behavior are preserved (R8). The
PSW-S17 command-level timeout tests were re-wired to reach the same typed
PDF-timeout boundary through the new action-first path (the timeout taxonomy
and sanitization contract is unchanged).

PSW-S20-C1 corrective closure (authoritative): dispatch is now fail-closed.
The capability is resolved as an explicit boolean: exact `True` MUST drive
the legacy action method (a missing/non-callable action method is a wiring
failure that NEVER falls back to a synthetic URL); exact `False` selects the
URL/container stub path; any other value (absent method, non-boolean return,
or an unconfigured MagicMock) raises one constant sanitized `ExtractionError`
with zero action calls and zero `open_tab`. Concrete stub/fake sessions
(`_StubSessionHandle`, `FakeExtractionSession`, `_PdfBridgeSession`) now
declare `supports_real_evolution_actions() -> False`. The cooperative
deadline is created before the first required UI action and every action
helper (`ensure_search_screen` through `click_visualizar_report`) plus the
report wait and download receive the same deadline's remaining budget via a
new optional `timeout_ms` keyword (default `None` preserves all existing
callers); the deadline is never reset per admission or helper. PSW-S17
taxonomy, sentinels, and the command-level timeout proofs are unchanged.

PSW-S20-C2 corrective closure (authoritative): post-operation deadline
classification. After a non-interruptible snapshot or overlap-selection
returns, an expired shared deadline is now classified BEFORE the result is
interpreted: `_pdf_remaining_ms(deadline_s)` is checked immediately after
the initial `_read_and_build_snapshot(...)`, immediately after
`choose_overlapping_admissions(...)` returns or raises a functional
NavigationError (before any no-overlap `EvolutionPdfError` or empty-result
interpretation), and immediately after each later-admission re-navigation
snapshot. An overrun propagates a typed `EvolutionPdfTimeoutError` through
the frozen PSW-S17 taxonomy; no new helper, state, exception, deadline, or
abstraction was added and the existing `deadline_s` is never reset.

## 21. PSW-S21: Canonical chunking and multi-admission flow

- [x] 21.1 Add failing tests for at-most-15-day chunks, canonical overlap,
  guaranteed progress, final single-day windows, and multiple overlapping
  admissions.
- [x] 21.2 Reuse the canonical dependency-free chunking module and remove the
  duplicate unused helper.
- [x] 21.3 Process every selected admission/chunk through the existing session,
  restore navigation between iterations, and retain the correct admission key.
- [x] 21.4 Preserve previously extracted events when a later chunk is empty and
  avoid fake data or infinite loops.
- [x] 21.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S21-report.md`.

PSW-S21 closure (authoritative; COMPLETE after C1): the persistent
evolution action flow now chunks each admission's bounded window and
processes every overlapping admission through the same authenticated session.
The app reuses the canonical dependency-free module
(`automation/source_system/medical_evolution/chunking.py`) via a lazily-loaded
file-path wrapper in `legacy_navigation.build_chunks_for_interval`; no
chunking algorithm is copied into `apps/ingestion` and the unused duplicate
`_build_chunks_for_interval` (plus its `_CHUNK_DAYS`/`_CHUNK_OVERLAP`
constants) was removed. For each overlapping admission the bridge clips the
requested window to `max(requested, admissionStart) ..
min(requested, admissionEnd)` (open-ended admissions fall back to the
requested bound, mirroring `path2`), builds the bounded chunks, opens the
detail once, and iterates the chunks: between consecutive chunks with a
prior report it restores the detail page via the new
`go_back_to_detail_from_report` helper (clicks the report ``Voltar`` and
waits for `consultaDetalheInternacao.xhtml` + the ``Evolução`` button); each
chunk fills its OWN bounded DD/MM/YYYY dates, so no report window exceeds 15
inclusive days with canonical one-day overlap. A genuine empty chunk now
RECOVERS the detail-page state before the next chunk: the no-evolutions
boundary in `wait_for_report_or_no_evolutions` closes the visible warning
dialog and the evolution modal (frame first, page fallback) within the
remaining wait budget and then waits for detail readiness before returning
`False`, so the next chunk re-opens the evolution modal from detail state; it
returns no fake events and never discards already-collected events
(`continue` leaves `all_events` untouched). The real admission key is stamped
on every event via `normalize_pdf_report_text(..., admission_key=...)`.
Every per-admission and per-chunk helper receives the SAME shared
cooperative deadline's remaining budget; typed timeouts propagate through
the frozen PSW-S17 taxonomy and non-timeout recoverable failures skip the
chunk while preserving priors. Each existing recoverable per-chunk failure
(between-chunk restore, Evolução click, required date-fill before raising the
constant error, optional ascending-order, visualize, PDF URL
resolution/missing, PDF download, text extraction, and normalization)
records its bounded `window_start`/`window_end` ISO dates via one tiny
sanitized logging helper that accepts only a constant reason plus the chunk
dates (R8); no patient record, admission key, ward/bed, event/PDF content,
URL, selector, cookie, credential, HTML, or raw exception reaches the record,
and a genuine empty chunk is not a failure and emits no failure warning. No
new browser/context/login is created during iteration (verified by a
no-subprocess/no-`sync_playwright` proof). PSW-S17/PSW-S18/PSW-S19/PSW-S20
observable contracts are preserved and not re-audited.

## 22. PSW-S22: Authenticated PDF form-download parity

- [x] 22.1 Add failing tests for direct PDF download and `#printLinks` POST
  fallback with synthetic ViewState and PDF bytes.
- [x] 22.2 Implement authenticated form fallback through the existing
  `context.request` without filesystem clinical artifacts.
- [x] 22.3 Propagate timeout and validate HTTP response, content type, and
  PDF signature with sanitized typed failures. PSW-S17 corrective closure
  already maps the persistent download timeout to a typed
  `EvolutionPdfTimeoutError` at the source boundary; this task hardens
  HTTP/PDF validation and MUST preserve and reverify the typed
  outer-exception contract rather than claim a new owner.
- [x] 22.4 Preserve normalization, shared persistence, cleanup, and no-new-login
  guarantees.
- [x] 22.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S22-report.md`.

PSW-S22 closure (authoritative; COMPLETE after C1): the persistent
evolution acquisition now has direct/form parity through the
already-authenticated context. A valid direct PDF URL uses an authenticated
`request.get`; when no direct URL is resolvable the bridge resolves the
existing `frame_pol` report frame (the same `SEL_FRAME_POL` contract used
by `wait_for_report_or_no_evolutions`) and reads the real `#printLinks`
JSF form `action` and `javax.faces.ViewState` from locators owned by that
report frame (never from the top-level page), resolving a relative action
against the report-frame URL. The POST still uses only the existing
`page.context.request` with the required JSF fields (`printLinks`,
`downloadLinkAjax`, `javax.faces.ViewState`). A missing report frame, form,
action, or ViewState raises a typed sanitized `EvolutionPdfError` BEFORE
any request is attempted; `read_locator_attribute` distinguishes genuine
absence (a non-blocking `count()` probe returns zero) from a real
attribute-read timeout, so absence reaches the unresolved-form path as an
exact `EvolutionPdfError` with zero GET/POST calls, while a bounded
Playwright attribute-read timeout on a locator proven present surfaces as a
typed `EvolutionPdfTimeoutError` raised outside the `except` handler
(neither `__cause__` nor `__context__` carries a raw exception). The
existing authenticated context cookies/session are used implicitly; no
cookie, authorization, patient, URL, or raw-payload value is copied or
logged. The bounded chunk timeout reaches GET and POST (via the shared
monotonic deadline and `_pdf_bound_ms`), and a Playwright/request timeout
or deadline overrun surfaces as a typed `EvolutionPdfTimeoutError` (raised
outside the `except` handlers so neither `__cause__` nor `__context__`
carries a raw exception). Response validation runs before parsing in this
order: HTTP status (`response.ok`), PDF-compatible content-type when the
header is present (`text/*` rejected; absent/binary deferred to the
signature), and the `%PDF-` signature on a non-empty body — so HTML/error
bytes never reach PyMuPDF as if valid. PDF bytes and extracted text stay in
memory; no PDF, HTML, or debug file is created. The acquisition layer is
kept separate from text normalization, which still stamps the real
admission key on every event. PSW-S17/S18/S19/S20/S21 observable
contracts, the current subprocess extractor, and the current worker
behavior are preserved and not re-audited; the stub `EvolutionPdfFlow`
download path remains guarded by `extract_pdf_text` and is out of scope for
this acquisition-parity slice.

## 23. PSW-S23: Current-versus-persistent parity suite

- [x] 23.1 Build parameterized parity tests for all supported intents using the
  same synthetic inputs and comparing externally visible effects.
- [x] 23.2 Compare lifecycle, attempts, stages, failures, counters, Patient,
  Admission, ClinicalEvent, demographics, follow-ups, and batch closure.
- [x] 23.3 Add a multi-job sequence proving admissions, demographics, full-sync,
  and a later job reuse one authenticated handle without subprocess or browser
  relaunch between jobs.
- [x] 23.4 Keep rollout blocked and report every intentional difference rather
  than weakening parity assertions.
- [x] 23.5 Run official validation and create
  `/tmp/sirhosp-slice-PSW-S23-report.md`.

PSW-S23 closure (authoritative): one focused parity module
(`tests/unit/test_current_vs_persistent_parity.py`) proves the persistent
worker can replace the current worker for every supported queued intent while
reusing one authenticated session across heterogeneous jobs. R1/R2: a closed
pairwise matrix runs each supported intent (`admissions_only`,
`demographics_only`, `full_sync`, `full_admission_sync`) through BOTH worker
commands with identical synthetic source payloads and compares ONLY observable
effects (status, counters, Patient/Admission/ClinicalEvent rows, demographics
fields, follow-up enqueue pattern, stages, batch closure) via a normalized
snapshot; private call order is never compared. R3: the timeout /
invalid-payload / retryable / terminal boundaries are covered ONCE through both
workers (PSW-S17 owns the full taxonomy x mode matrix); this slice adds the
complementary "no bad persistence" angle (zero clinical rows on failure) plus
cross-worker observable equality. R5: a real `PersistentExtractionAdapter`
backed by a fake session processes `admissions_only -> demographics_only ->
full_sync -> admissions_only` through ONE handle (one adapter creation, no
`restart_browser`, no browser/context relaunch) with the controller cleanup
checkpoint firing after each job. R6: a subprocess spy proves zero
subprocess/Popen calls on the persistent per-job path for every intent. R7:
empty/unknown intents are not claimed and receive no source action (composed
from PSW-S14, confirmed in the suite). No assertion was weakened: the sole
intentional difference (the persistent `demographics_only` identity check) is a
command-level defense that does not change observable parity because both
workers receive matching data. Production rollout REMAINS BLOCKED pending the
PSW-S24-PRE operational command slice and PSW-S24 guarded live validation.
PSW-S17..PSW-S22 observable contracts are preserved and not re-audited.

## 23A. PSW-S24-PRE: Guarded real multi-run execution

- [x] 23A.1 Add a closed real-handle CLI mode matrix that preserves the
  single-run smoke and rejects invalid combinations before adapter creation.
- [x] 23A.2 Add a bounded, ordered allow-list of two through four explicit run
  IDs that preflights every row before one adapter/bootstrap and never claims
  unlisted work.
- [x] 23A.3 Make the existing continuous real queue loop reachable only through
  an explicit default-off `--enable-real-queue` opt-in; do not enable deployment
  or claim rollout readiness.
- [x] 23A.4 Prove with command/DB tests that heterogeneous listed jobs reuse the
  session, stop after a failed job, and complete restart plus rebootstrap before
  a later claim.
- [x] 23A.5 Preserve frozen worker/extraction contracts, update only the allowed
  design/spec/rollout/task artifacts, run official validation, and create
  `/tmp/sirhosp-slice-PSW-S24-PRE-report.md`.
- [x] 23A.6 PSW-S24-PRE-C2 corrective closure (authoritative; COMPLETE after
  C2): the integrated real-startup proof now runs the exact intent sequence
  admissions -> demographics -> full_sync -> admissions (job 3 uses
  `full_sync`, not the `full_admission_sync` alias); command help describes all
  three real modes (single smoke, bounded validation, continuous real queue)
  and `--validation-run-id` explicitly requires `--real-handle`, with the stale
  smoke-only claim removed; the synthetic real-session bridge records an
  ordered cleanup/claim/restart/rebootstrap/shutdown trace proving a cleanup
  checkpoint after every completed extraction (five for the successful
  sequence: 1 + 1 + 2 for full_sync admissions+evolutions + 1), every job-3
  cleanup before restart, restart plus rebootstrap before claim 4, the final
  cleanup before the single shutdown, and a failed rebootstrap that prevents
  claim 4 while still shutting down once. Bounded still requires
  `--real-handle` and bounded stdout/stderr stay free of run primary keys and
  source data (C1 preserved). Official check, unit (2325), integration (390),
  lint, typecheck, quality-gate, and strict OpenSpec pass; deployment stays
  blocked pending PSW-S24 live validation, which remains unverified against
  the real legacy UI.

## 24. PSW-S24: Guarded live validation and cutover readiness

- [x] 24.0 PSW-S24-PROD-C1 production bootstrap hotfix: propagate the shared
  optional `PLAYWRIGHT_PROXY_SERVER` configuration into the real persistent
  Chromium context and enable HTTPS tolerance already used by production
  legacy extractors. Regression tests cover configured-proxy and direct
  environments without exposing connection details. Automated gates pass;
  live bootstrap/login remains pending on deployment of the corrected image.
- [x] 24.0a PSW-S24-PROD-C2 production login-submission hotfix: preserve the
  canonical `Entrar` button as the first path and fall back to pressing Enter
  in the already-filled password field when the real portal rejects that click,
  matching an existing production extractor. The authenticated boundary
  remains `#tempoSessao`; dual-path failure remains sanitized. Automated gates
  pass; real readiness remains pending deployment and production retest.
- [x] 24.0b PSW-S24-PROD-C3 production-proven login correction
  (authoritative): live evidence disproved the speculative C2 button/role
  fallback, while the exact established discharge login path reached real
  authenticated readiness. Bootstrap now applies the 180-second action timeout,
  uses exact username/password placeholder selectors, submits with password
  Enter, and still requires `#tempoSessao`. Automated gates pass; standard
  bridge bootstrap and bounded validation remain pending production redeploy.
- [x] 24.0c PSW-S24-PROD-C4 real Playwright/ORM lifecycle correction: live
  single-run evidence exposed Django `SynchronousOnlyOperation` before claim
  because Playwright's synchronous dispatcher loop remains active on the
  command thread. Explicit real mode now scopes Django's documented synchronous
  ORM escape hatch around serialized processing and teardown, restores the
  previous environment value, and stops the returned Playwright object through
  `stop()` rather than an invalid `__exit__()` call. Automated gates pass;
  production single-run retest and bounded validation remain pending redeploy.
- [x] 24.0d PSW-S24-PROD-C5 production-proven POL navigation correction:
  sanitized live probes showed the visible `#polMenu` timing out under
  Playwright's normal actionability click while the established direct DOM
  click immediately revealed `#prontuarioInput`. Persistent navigation now
  tries the exact production interaction first and retains the bounded normal
  click fallback. Regression coverage and automated gates pass; production
  single-run retest and bounded validation remain pending redeploy.
- [x] 24.0e PSW-S24-PROD-C6 production restart-lifecycle correction:
  admissions succeeded and naturally enqueued demographics plus `full_sync`,
  but the bounded run stopped after row one because `restart_browser()` still
  called invalid `__exit__()` on the public Playwright object. Restart now uses
  `stop()` and preserves the configured proxy plus HTTPS tolerance on the fresh
  context. Regression coverage and automated gates pass; production bounded
  retest remains pending redeploy.
- [x] 24.0f PSW-S24-PROD-C7 stale bridge page-state correction: after a
  successful browser restart, `RealHandleBridge` still classified the fresh
  post-login page using the previous admissions URL and transformed its HTML
  before controller readiness parsing. Restart now clears the obsolete page
  type only after the wrapped handle succeeds. Regression coverage passes;
  production bounded retest remains pending redeploy.
- [x] 24.0g PSW-S24-PROD-C8 authenticated-readiness timing correction:
  sanitized post-restart probing proved `#tempoSessao` was attached before its
  three countdown spans were populated (`sample 0=False`, `sample 0.1=True`).
  Bootstrap now waits on a bounded browser predicate for three numeric values
  before returning, without arbitrary sleeps or weakened controller checks.
  Regression coverage passes; production bounded retest remains pending.
- [x] 24.0h PSW-S24-PROD-C9 evolution-modal and framed-PDF correction:
  sanitized production probes proved date-input actionability timeouts, a
  Visualizar click that emitted no request, and a direct PDF object inside
  `frame_pol`. Date focus now uses the proven DOM interaction, report generation
  invokes the exact declared PrimeFaces action, and direct PDF resolution uses
  the report frame and its base URL. Regression coverage passes; production
  `full_sync` and bounded retests remain pending rebuild from the committed
  revision.
- [x] 24.0i PSW-S24-PROD-C10 renewal-popup fail-closed correction:
  a real session left idle showed the popup at minute 30; the unscoped
  affirmative selector failed while the stale countdown made
  `ensure_ready()` return true. Renewal now targets the popup-scoped button,
  falls back once to the declared DOM click after non-timeout actionability
  failure, and rejects readiness while the popup remains visible. Regression
  coverage passes; the 30-minute production retest remains pending deployment
  of the committed correction.
- [x] 24.0j PSW-S24-PROD-C10-R1 renewal completion wait:
  the first committed production retest proved the scoped DOM action worked
  (`popup_cleared=True`, `counter_advanced=True`) but immediate verification
  returned false before the asynchronous PrimeFaces update completed. The
  concrete click now awaits the scoped control's hidden state with a bounded
  browser-native timeout and preserves sanitized typed timeout propagation.
  Unit and quality gates pass. Integration was independently blocked on three
  attempts solely by OpenRouter shared-pool HTTP 429 responses in summary
  tests. The committed production retest observed the popup at minute 30;
  handler readiness, popup clearance, and countdown advancement were all true.
  Teardown and exit were clean, and no continuous worker was left running.
- [x] 24.0k PSW-S24-PROD-C11 authorized stale disposal:
  with all ingestion workers stopped, dry-run found exactly 12 abandoned
  `running` rows from one batch. Apply used an exact 12-row circuit breaker
  and terminally marked all 12 failed without requeue (`skipped=0`,
  `closed_batches=1`). Post-flight found zero stale candidates and zero
  `running` rows; queued and succeeded counts remained unchanged. No production
  code change was needed because the existing transactional command already
  satisfied the authorized contract.

- [x] 24.1 Define sanitized operator-run evidence using the PSW-S24-PRE bounded
  allow-list for real admissions, demographics, chunked evolutions, renewal,
  cleanup, and restart/rebootstrap. The production evidence matrix uses only
  ordinal rows, aggregate counters, lifecycle outcomes, and sanitized paths.
- [x] 24.2 Run guarded validation within the approved concurrency limit. One
  process completed the four-intent allow-list, restart/rebootstrap boundary,
  and the independent 30-minute renewal proof without enabling continuous mode.
- [ ] 24.3 Reconcile proposal, design, specs, tasks, rollout docs, defaults, and
  remaining risks with observed results.
- [ ] 24.4 Approve replacement readiness only if automated parity, live
  validation, official gates, rollback, and observability criteria all pass.
- [ ] 24.5 Run final official validation and create
  `/tmp/sirhosp-slice-PSW-S24-report.md`.
