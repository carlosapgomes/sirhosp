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

Rationale: persistence parity is now solved, so the remaining rollout blocker is
isolated to source-system extraction through the already-open persistent
browser/session.

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

## Risks / Trade-offs

- Profile/cache growth -> use exclusive profiles, tmpfs limits, safe cache
  clearing, and bounded restarts.
- Popup blocks actions -> renew at safe checkpoints and after timeouts.
- Tab close does not reset counter -> depend only on opening/rendering a new
  legacy tab for proactive renewal, then close tabs only as cleanup.
- Idle session expires -> handle popup during idle and relog before claim.
- Wrong tab closed -> enforce non-root selector and verify root state.
- Persistent group consumes more jobs -> compare rates and durations by group.
- Run semantics drift -> preserve model/status/stage behavior with tests.
- Persistence duplication -> extract evolution persistence into one shared
  service before enabling persistent full-sync.
- Real handle contract mismatch -> keep rollout blocked until the handle can
  supply real legacy admission/evolution data to the adapter contract.
- Invalid URL-template assumption -> real legacy smoke must use action-based
  JSP/PrimeFaces navigation modeled after `path2.py`, not reloadable deep
  links.
- Selector drift -> isolate selectors and test known synthetic HTML.
- Popup-detection regex is order-sensitive (expects `id` then
  `aria-hidden="false"` then `display: block` on the same element).
  Synthetic HTML in PSW-S1 is controlled, but PSW-S2 must verify that
  real PrimeFaces DOM keeps this attribute order or harden the detector
  (e.g. parse attributes independently instead of a single ordered
  regex) before relying on it for recovery decisions.

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
9. Do not start production side-by-side load until full-sync persistence, real
   action navigation, and the real-handle contract are resolved.
10. After prerequisites are met, start a small side-by-side experiment with
    distinct label prefixes.
11. Compare run count, success rate, timeout rate, durations, retries, and stale
    recovery incidents by group.
12. Roll back by stopping persistent workers and scaling current workers back.

## Open Questions

- Which legacy action should be used for artificial keepalive if needed later?
- Should per-attempt worker-group metadata be added later?
- What max-jobs and max-lifetime defaults are best for production?
- How will the real handle satisfy the legacy snapshot/evolution container
  contract without synthetic HTML injection?
- Which minimal action-navigation helper should become the shared source of
  truth between the persistent real handle and the existing Playwright scripts?
- When will full-sync persistence be extracted into a shared ingestion service?
