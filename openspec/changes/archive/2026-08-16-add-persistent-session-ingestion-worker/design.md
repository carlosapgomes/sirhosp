# Persistent Session Ingestion Worker Design

## Context

The current ingestion worker is `process_ingestion_runs`. It consumes
`IngestionRun` rows from PostgreSQL with transactional claiming and
`select_for_update(skip_locked=True)`. It records `worker_label`, maintains
`worker_heartbeat_at`, and delegates legacy extraction to a Playwright
subprocess adapter.

Each run starts a fresh browser execution, logs into the legacy system, opens
the required screen, performs extraction, and exits. The proposed worker is an
additional command, not a replacement. Operators should be able to run both
worker types against the same queue and compare outcomes by label.

This preserves the phase-1 architecture: Django monolith, PostgreSQL
coordination, no Celery/Redis, and deployment through existing Docker/systemd
patterns.

All implementation work for this change must stay on isolated branch
`feature/add-persistent-session-ingestion-worker`. The branch must not include
unrelated fixes, other OpenSpec changes, or opportunistic refactors.

Active OpenSpec change directories are ignored by `.gitignore` in this project.
If the branch must carry planning artifacts, force-add this change directory
explicitly on that branch.

Legacy session observations:

- The legacy UI exposes a countdown at `#tempoSessao` with three spans in
  `HH:MM:SS` format.
- The renewal popup appears exactly when 5 minutes remain.
- The popup container is `#casca_renovasession` with
  `aria-hidden="false"` when visible.
- The semantic renewal button is `.ui-confirmdialog-yes` or text `Renovar`
  inside `#formRenovaSession`.
- A root-only tab has classes `tabs-first tabs-last tabs-selected`.
- Job actions open additional tabs. The current job tab is the last non-root
  tab and has `a.tabs-close`.
- Opening and rendering a new legacy tab consistently renews the sliding
  30-minute session window.
- Closing a legacy tab does not consistently renew the counter and must be
  treated as cleanup only, never as the renewal mechanism.

## Goals / Non-Goals

**Goals:**

- Add a separate persistent-session ingestion worker.
- Keep one browser context and authenticated session across multiple jobs.
- Renew the legacy session through opening/rendering a new legacy tab, with the
  popup as defensive fallback.
- Preserve queue claim safety, attempts, status transitions, stage metrics,
  worker label, heartbeat, retries, stale-run compatibility, and batch closure.
- Provide labels and docs for side-by-side A/B-style operation.
- Keep slices vertical, small, test-driven, and reviewable.

**Non-Goals:**

- Do not remove, disable, or replace `process_ingestion_runs`.
- Do not add Celery, Redis, a second queue, or a microservice.
- Do not persist raw patient data, real PDFs, debug HTML, screenshots,
  credentials, or session cookies in repository artifacts.
- Do not require real legacy access in unit tests.
- Do not add aggressive background clicking during arbitrary actions.

## Decisions

### Decision 1: Add a separate management command

Create `process_ingestion_runs_persistent_session`. It consumes the same queue
and uses the same claim discipline as the current worker.

Rationale: this allows controlled side-by-side operation, simple rollback, and
no change to current worker behavior.

Alternative considered: add `--persistent-session` to the current command. This
is deferred because it increases blast radius.

### Decision 2: Use a persistent extractor boundary

Introduce a boundary with the extraction methods required by the ingestion
lifecycle:

- `get_admission_snapshot(...)`
- `extract_evolutions(...)`
- `ensure_ready()`
- `renew_if_needed()`
- `close_job_tab_if_present()`
- `restart_browser()`

Rationale: queue/run orchestration remains separate from browser/session
details.

Alternative considered: place Playwright calls directly in the command. This is
rejected because commands should not contain complex automation logic.

### Decision 3: Renew only at safe checkpoints

The worker checks renewal:

- before claiming a job;
- before long source-system actions;
- after long waits or timeouts;
- after each job while cleaning tabs;
- during idle polling.

It must not run an unconstrained background clicker.

Rationale: safe checkpoints avoid interfering with modals, submits, downloads,
or tab transitions.

### Decision 4: Renew by opening a safe legacy tab

The worker parses `#tempoSessao` when available. When proactive renewal is
needed, it must open a configured safe legacy tab, wait until that tab is fully
rendered, and verify that the counter reset. Closing the opened tab is cleanup
only and must not be treated as renewal evidence.

During active batches, opening the job tab should naturally renew the session.
During empty-queue idle periods, the worker may use the same safe tab-opening
renewal path when configured. The renewal popup remains a defensive unblock path
when already visible, but popup dismissal alone is not the evidence used for
counter reset.

Alternative considered: tab-close keepalive. This is rejected because manual
testing showed close events do not consistently renew the counter.

### Decision 5: Close only non-root last tabs

The tab cleanup invariant is:

- if there is exactly one tab and it is root-only, do nothing;
- if there is more than one tab, close
  `li.tabs-last:not(.tabs-first) a.tabs-close`;
- verify that tab count decreases or root state is restored;
- never use successful close as proof that session renewal occurred.

Rationale: the root tab is the stable session anchor. Opening a tab renews the
session; closing a tab only returns the UI to a clean baseline.

### Decision 6: Isolate profile directories

Each persistent worker process must use an exclusive browser profile or user
data directory. Cache cleanup may use safe browser APIs, but destructive profile
cleanup happens only after browser shutdown.

Rationale: sharing mutable Chromium profiles risks corruption and
cross-process interference.

### Decision 7: Restart unhealthy sessions

The worker supports conservative restart triggers:

- browser or page disconnected;
- repeated renewal or relogin failures;
- repeated tab cleanup failures;
- max jobs per browser session;
- max browser lifetime;
- optional profile/cache size threshold.

Rationale: persistent browsers can degrade over time.

### Decision 8: Extract evolution persistence into a shared service

Full-sync persistence must not be duplicated inside the persistent worker.
Extract the current worker's `_ingest_evolutions` behavior into a shared service
that both worker commands call.

Rationale: this preserves current semantics and avoids two divergent clinical
persistence paths.

Alternative considered: copy the current command method into the persistent
command. Rejected because it duplicates business logic in management commands.

### Decision 9: Resolve real handle contract before rollout

The real `PlaywrightSessionHandle` must satisfy the persistent adapter's data
contract against the legacy UI before production rollout. It may transform real
DOM/download output into the adapter contract, or the adapter/handle boundary
may be adjusted to return already-normalized data.

Rationale: synthetic test containers are useful for unit tests but cannot be the
basis for production extraction.

Alternative considered: keep the real handle opt-in and proceed with rollout.
Rejected because it would fail real jobs or give misleading operational data.

### Decision 10: Add a dedicated real-handle bridge slice

PSW-S9 owns the bridge/translation layer between the real legacy UI and the
persistent extraction contract. The slice must not reintroduce subprocess-per-job
execution or launch a fresh browser per job.

Rationale at that stage: persistence parity was solved and source extraction
through the already-open browser/session was the remaining blocker. PSW-S24
later validated that boundary in production.

### Decision 11: Use action-based legacy navigation, not URL templates

Manual validation confirmed the legacy system is Java/JSP/PrimeFaces and does
not expose reloadable patient/admission/evolution URLs that can be safely opened
from templates. The real persistent handle must therefore model the working
Playwright action flow from
`automation/source_system/medical_evolution/path2.py`: search by prontuário,
open `Internações`, read `frame_pol` rows, open admission details, open
`Evolução`, fill dates, generate the report, and download the PDF through the
existing authenticated context.

`SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE` and
`SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE` are treated as an invalid rollout
assumption for the real legacy path. They may remain only as test/stub
compatibility until PSW-S12/PSW-S13 remove their real-smoke requirement.

Rationale: direct URL templates would give misleading smoke-test results or fail
against the real JSP navigation model. Action navigation keeps the persistent
worker aligned with the known-good integrated Playwright script while still
preserving the no-subprocess/no-new-browser requirement.

### Decision 12: Target replacement readiness, not partial queue support

The persistent worker is the operator-approved replacement for
`process_ingestion_runs` after automated and live-validated parity for every
supported queued intent. The current service definition remains unchanged and
available, but is not required to run beside the persistent worker.

Rationale: side-by-side operation is a migration mechanism, not the final
functional boundary. A worker sharing the queue cannot safely omit a supported
intent or report success with different clinical and operational side effects.

### Decision 13: Use an explicit supported-intent contract

The persistent worker supports `admissions_only`, `demographics_only`,
`full_sync`, and `full_admission_sync` (an explicit alias of the full-sync
path). It must not use a generic `else -> full_sync` fallback. Empty intents are
not supported: the persistent worker must not claim them, tests must prove that
current production enqueue paths do not create them, and any explicitly
selected empty/unknown run must fail validation without source-system actions.

Rationale: implicit fallback can make a faster persistent worker steal and
misprocess unrelated jobs. An explicit contract makes replacement scope and
queue ownership auditable.

### Decision 14: Demographics reuse the authenticated persistent session

`demographics_only` must navigate to `Dados do Paciente`, read `frame_pol`,
normalize fields in memory, and call the existing
`upsert_patient_demographics` service through the already-open persistent
page/context. It must not execute the current demographics subprocess, create a
temporary JSON file, call `sync_playwright()`, launch another browser/context,
or perform another login.

Rationale: copying the current command method would provide intent coverage but
would defeat the central session-reuse objective.

### Decision 15: Require parity and live validation before cutover

Replacement readiness requires: per-intent behavior tests, shared-session
multi-job tests, failure/attempt parity, safe tab cleanup, restart plus
rebootstrap, action-first evolution navigation, canonical chunking,
authenticated PDF fallback, and guarded validation against the real legacy UI.
Passing fake-only unit tests is necessary but not sufficient.

Rationale: the persistent lifecycle changes source navigation and operational
failure modes. Cutover must be based on observable parity, not matching method
names or mock call counts.

### Decision 16: Closed real-handle CLI mode matrix

The real persistent handle must never drain the production queue by accident.
The command therefore exposes exactly four closed CLI modes, validated before
any adapter/browser creation or run mutation:

1. stub (no `--real-handle`): existing queue behavior unchanged;
2. single real smoke: `--real-handle --run-id ID --max-runs 1`;
3. bounded validation: repeatable `--validation-run-id` of two through four
   distinct positive IDs in operator order, WITH `--real-handle` and
   `--max-runs` equal to the count; every listed row is preflichted before
   one real adapter/bootstrap, jobs reuse the same authenticated session,
   processing never falls through to an unlisted row, a claim race, job
   failure, or restart failure leaves later selected rows untouched, and all
   bounded-mode output (success, failure, follow-up, retry, and terminal
   branches for every supported intent) carries NO run primary keys (selected
   or auto-enqueued follow-up) and NO source/patient data — only ordinal,
   count, stage, and normalized-reason information;
4. continuous real queue: `--real-handle --loop --enable-real-queue`, default
   off and forbidden with `--run-id`/`--validation-run-id`/`--max-runs`.

`--real-handle --loop` without the explicit opt-in fails before adapter/browser
creation. Every other combination fails before `_create_adapter()` and before
any run mutation. The production `persistent_worker` service preserves a
second default-off boundary through the explicit `persistent-worker` Compose
profile.

Rationale: the closed matrix prevents an accidental real queue drain. The
guarded PSW-S24 sequence subsequently proved multi-job session reuse,
restart/rebootstrap, every supported intent, cleanup, and sanitized output.

### Decision 17: Authorized forward cutover

After the guarded production proof, the operator accepted the
persistent-session worker as the production path and explicitly waived a
rollback rehearsal as a cutover gate. Cutover starts with one replica behind
the explicit Compose profile and command opt-in. The legacy service definition
remains available but is not part of the acceptance decision.

Production tuning is evidence-driven. Operators observe aggregate queue
progress, attempts, duration, queue latency, heartbeat, session failures,
RSS/CPU, shared memory, tmpfs/profile use, and log growth without exposing
source or patient data. Authentication loops, stale heartbeats, repeated
restarts, cleanup failures, retry amplification, resource exhaustion, or
unsanitized output require an emergency stop and diagnosis.

Rationale: real authentication, all supported intents, PDF extraction,
restart/rebootstrap, renewal after a 30-minute idle interval, cleanup, and
stale-run disposal have passed. Remaining uncertainty is operational tuning,
which the operator chose to perform on the deployed production path.

## Risks / Trade-offs

- Profile/cache growth -> use exclusive profiles, tmpfs limits, safe cache
  clearing, and bounded restarts.
- Popup blocks actions -> renew at safe checkpoints and after timeouts.
- Tab close does not reset counter -> depend only on opening/rendering a new
  legacy tab for proactive renewal, then close tabs only as cleanup.
- Idle session expires -> handle popup during idle and relog before claim.
- Wrong tab closed -> enforce non-root selector and verify root state.
- Persistent group consumes more jobs -> use explicit supported-intent claims
  and compare rates and durations by group.
- Run semantics drift -> compare persistent and current external effects for
  each supported intent.
- Unsupported/empty intent is misrouted -> never use an implicit full-sync
  fallback and never claim unsupported rows.
- Demographics opens another login -> require navigation through the already
  authenticated persistent page/context and inspect for forbidden subprocess or
  browser-launch calls.
- Persistence duplication -> extract or reuse small shared services rather than
  copying command-local business logic.
- Real handle contract drift -> monitor admissions, demographics, full-sync,
  and evolutions through aggregate production outcomes.
- Invalid URL-template assumption -> real legacy flows must use action-based
  JSP/PrimeFaces navigation modeled after the known working scripts.
- Selector drift -> isolate selectors and validate them in guarded live smoke.
- Popup detection drift -> parse attributes independently and verify popup
  disappearance before treating the page as ready.
- Production tuning reveals a regression -> start with one explicit-profile
  replica and stop on the Decision 17 safety conditions.

## Migration Plan

1. Create or switch to branch
   `feature/add-persistent-session-ingestion-worker` before coding.
2. Keep every implementation slice on that branch and avoid unrelated changes.
3. Implement the new command without changing the current command.
4. Test with fake Playwright/session objects.
5. Deploy with zero persistent workers configured.
6. Extract evolution persistence into a shared service and keep the current
   worker behavior unchanged.
7. Resolve the real handle contract for legacy admission/evolution data.
8. Replace real-smoke URL-template navigation with action-based legacy
   navigation modeled after `path2.py`.
9. Implement explicit dispatch and claim ownership for every supported intent;
   reject empty and unknown intents without source-system actions.
10. Restore `admissions_only` clinical persistence and follow-up parity.
11. Implement persistent-session `demographics_only` without subprocess or a
    second browser/login.
12. Restore timeout, attempt, final-failure, and batch lifecycle parity.
13. Correct internal legacy-tab cleanup and unsafe-cleanup recovery.
14. Rebootstrap authentication after browser restart and expose conservative
    lifecycle/headless configuration.
15. Make the real evolution path action-first, then add canonical chunking,
    multi-admission handling, and authenticated PDF form fallback.
16. Run current-versus-persistent parity tests for all supported intents and a
    multi-job sequence through one authenticated handle.
17. Resolve automated blockers and pass the official quality gates before
    continuous production use.
18. Run guarded live validation within the project-approved concurrency limit.
19. Record the operator's explicit forward-cutover authorization without a
    rollback-rehearsal gate.
20. Deploy one default-off-profile persistent replica and compare aggregate run
    outcomes, retries, timeouts, queue latency, resource use, and stale state.
21. Tune lifecycle/resource parameters from observed production evidence and
    scale only while health and resource headroom remain acceptable.

## Open Questions

- What lifecycle and resource values should change after the first continuous
  production measurements?
- What observation window supports scaling beyond one replica?
