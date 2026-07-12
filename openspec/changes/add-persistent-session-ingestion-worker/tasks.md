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
