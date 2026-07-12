"""Persistent-session ingestion worker (PSW-S4).

Alternative ingestion worker that reuses a persistent browser session across
multiple ``IngestionRun`` jobs. Consumes the same PostgreSQL queue as
``process_ingestion_runs`` using the same claim discipline, but delegates
extraction to the ``PersistentExtractionAdapter`` backed by a ``SessionHandle``
protocol implementation.

Design (see ``openspec/changes/add-persistent-session-ingestion-worker/design.md``):

- Creates a ``PersistentExtractionAdapter`` at startup and reuses the underlying
  browser/session across jobs.
- Calls session readiness checkpoints (``ensure_session_ready``) before claiming
  a run.
- Processes admissions-only runs through the adapter.
- Closes the job tab after success (handled by adapter) and after recoverable
  data failures (handled by this command).
- Preserves existing ``IngestionRun`` lifecycle semantics: attempts, statuses,
  stages, retries, failures, heartbeat, labels, and batch closure.
- Uses ``WorkerHeartbeat`` from the existing worker for heartbeat.

PSW-S9 status:
- RealHandleBridge IS implemented: wraps PlaywrightSessionHandle to
  translate real legacy DOM table/script data into the synthetic container
  format (<div id="admission-snapshot-data">, <div id="evolution-data">)
  expected by PersistentExtractionAdapter.
- When ``--real-handle`` is passed, the bridge extracts admission data
  from the legacy ``#tabelaInternacoes`` table rows and evolution data
  from ``<script id="evolution-data-json">`` or ``<pre class="report-text">``
  elements, wrapping them in the adapter's expected container format.
- The bridge does NOT launch a fresh browser, subprocess, or new
  Playwright context per job — it delegates all session operations
  to the already-open persistent handle.
- Production rollout REMAINS GUARDED: the bridge has been tested with
  representative legacy HTML fakes but has NOT been validated against
  the real legacy UI in a live environment. Keep ``--real-handle`` as
  an opt-in integration experiment flag.

PSW-S10 status:
- ``--real-handle`` requires BOTH an explicit ``--run-id`` AND ``--max-runs 1``
  so a manual smoke test processes exactly one selected queued run and cannot
  accidentally drain the general queue or enter an idle loop. Both are checked
  before ``_create_adapter()`` (no browser launched) and before any claim.
  ``--max-runs`` also caps the number of processed runs on the stub path.
- The real-handle path resolves source-system credentials and real URL
  templates (admissions, evolutions, safe renewal), validates them, and
  bootstraps an authenticated legacy session (navigate + login + wait
  for ``#tempoSessao``) BEFORE any run is claimed.
- Failures before claim (missing credentials, missing URL templates,
  bootstrap errors) are sanitized and never mutate queued runs.
- This is a guarded MANUAL SMOKE path only — it is NOT production
  rollout-ready.

PSW-S11 status:
- The persistent ``full_sync`` can now extract evolutions from the real
  legacy PDF report flow via ``EvolutionPdfFlow``, reusing the already-open
  persistent page/context. It never invokes ``subprocess``, never shells out
  to ``path2.py``, never calls ``sync_playwright()`` again, and never launches
  a fresh browser per job.
- The PDF flow is a FALLBACK only: the PSW-S9 lightweight fast paths
  (``evolution-data-json`` script and ``pre.report-text``) are tried first by
  ``RealHandleBridge``; when they yield no events, the adapter delegates to
  ``extract_evolutions_pdf``. JSON/script and ``pre.report-text`` paths are
  unchanged.
- Failures map to ``EvolutionPdfError`` (sanitized; no credentials/cookies/
  raw HTML/patient data) and are classified as recoverable data-level
  failures (tab cleanup runs; retry taxonomy preserved).
- This is still a guarded MANUAL SMOKE path — it has NOT been validated
  against the real legacy UI in a live environment.

Usage::

    # Single pass
    uv run python manage.py process_ingestion_runs_persistent_session

    # Continuous loop
    uv run python manage.py process_ingestion_runs_persistent_session \\
        --loop --sleep-seconds 5
"""

from __future__ import annotations

import os
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.ingestion.batch_closure import try_close_batch
from apps.ingestion.evolution_ingestion import ingest_evolutions
from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.gap_planner import plan_extraction_windows

# ---------------------------------------------------------------------------
# Reuse WorkerHeartbeat from the existing worker
# ---------------------------------------------------------------------------
from apps.ingestion.management.commands.process_ingestion_runs import (
    WorkerHeartbeat,
)
from apps.ingestion.models import IngestionRun, IngestionRunAttempt

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_ADMISSIONS_TIMEOUT = 120
"""Default timeout (seconds) for admissions snapshot extraction."""

_LOGIN_TIMEOUT_SECONDS = 60
"""Default timeout (seconds) for each legacy bootstrap navigation/wait step."""

_PERSISTENT_LABEL_PREFIX = "persistent-worker"
"""Default worker label prefix when SIRHOSP_WORKER_LABEL is not set."""


class _StubSessionHandle:
    """Minimal stub implementing the SessionHandle protocol.

    Returns safe defaults (disconnected, empty HTML, no tabs) and never
    performs real browser actions. Used when no real Playwright-based
    SessionHandle is wired yet.
    """

    def get_page_html(self) -> str:
        return ""

    def is_connected(self) -> bool:
        return False

    def click_selector(self, selector: str) -> None:
        pass

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        return False

    def get_tab_classes(self) -> list[str]:
        return []

    def close_last_non_root_tab(self) -> None:
        pass

    def restart_browser(self) -> None:
        pass

    def shutdown(self) -> None:
        """No-op teardown for the stub (no real resources to release)."""
        pass


class Command(BaseCommand):
    """Process queued IngestionRuns using a persistent browser session."""

    help = (
        "Process queued ingestion runs using a persistent browser session "
        "(alternative worker, same queue as process_ingestion_runs)."
    )

    # Allow dependency injection for tests — override via class attribute
    # or patch at import path.
    adapter_class = PersistentExtractionAdapter

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously, processing queued runs as they appear.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=5,
            help="Seconds to sleep when no queued runs are found (default: 5).",
        )
        parser.add_argument(
            "--real-handle",
            action="store_true",
            help=(
                "Use a real Playwright Chromium session handle wrapped in "
                "RealHandleBridge instead of the safe stub. The bridge "
                "extracts admission/evolution data from the real legacy DOM "
                "and wraps it in synthetic containers for the adapter. "
                "Requires --run-id and --max-runs 1 (manual smoke only); NOT "
                "production-validated — keep guarded."
            ),
        )
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help=(
                "Claim only this IngestionRun id (must be queued and "
                "eligible). Required with --real-handle to avoid draining "
                "the production queue during a manual smoke test."
            ),
        )
        parser.add_argument(
            "--max-runs",
            type=int,
            default=None,
            help=(
                "Stop after processing this many runs. Useful to bound "
                "manual smoke tests (e.g. --max-runs 1)."
            ),
        )

    def handle(self, *args, **options):
        loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]
        self._use_real_handle: bool = options["real_handle"]
        self._run_id: int | None = options.get("run_id")
        self._max_runs: int | None = options.get("max_runs")
        self._processed_count: int = 0

        # Safety guard: a real-legacy manual smoke must target exactly one
        # explicitly selected run so it cannot accidentally drain the
        # production queue. This is checked before any run is claimed.
        if self._use_real_handle and self._run_id is None:
            raise CommandError(
                "--real-handle requires --run-id to avoid draining the "
                "production queue. Specify a single queued IngestionRun id "
                "for the manual smoke."
            )

        # Safety guard: a real-legacy manual smoke must be bounded to exactly
        # one run via --max-runs 1 so it cannot enter an idle loop or process
        # more than the selected run. Checked before _create_adapter() (no
        # browser launched) and before any claim. Does not affect the stub path.
        if self._use_real_handle and self._max_runs != 1:
            raise CommandError(
                "--real-handle requires --max-runs 1 to bound the manual smoke "
                "to a single run. Pass --max-runs 1 explicitly."
            )

        # The adapter (and its persistent browser/session) is created ONCE
        # at startup and reused across all claimed runs. This is the core
        # persistence guarantee of this worker (see design Decision 2 / spec
        # "Browser and session reuse").
        adapter = self._create_adapter()
        try:
            if loop:
                self._run_loop(adapter, sleep_seconds=sleep_seconds)
            else:
                self._process_once(adapter)
        finally:
            self._shutdown_adapter(adapter)

    def _shutdown_adapter(self, adapter: PersistentExtractionAdapter) -> None:
        """Tear down the persistent session after the run/loop ends.

        Calls the handle's ``shutdown()`` to close the browser and release the
        exclusive profile (``ExclusiveBrowserProfile.release_after_shutdown``).
        Falls back gracefully for handles without an explicit ``shutdown``
        (e.g. the safe stub).
        """
        session = adapter.session
        shutdown = getattr(session, "shutdown", None)
        try:
            if callable(shutdown):
                shutdown()
            else:
                # Stub handle has no shutdown — nothing to tear down.
                pass
        except Exception as exc:  # noqa: BLE001 - best-effort teardown logging
            self.stderr.write(
                self.style.WARNING(
                    f"Error during persistent session teardown: {exc}"
                )
            )

    # ------------------------------------------------------------------
    # Adapter creation (overridable for tests)
    # ------------------------------------------------------------------

    def _create_adapter(self) -> PersistentExtractionAdapter:
        """Create a new PersistentExtractionAdapter.

        The session handle defaults to the safe ``_StubSessionHandle`` (no
        Chromium) so the command is NOT rollout-ready. Pass ``--real-handle``
        (with ``--run-id``) to opt into the real legacy path: it resolves and
        validates credentials and real URL templates, starts a
        ``PlaywrightSessionHandle`` (exclusive ``ExclusiveBrowserProfile``),
        bootstraps an authenticated session (navigate + login + wait for
        ``#tempoSessao``), and wraps the handle in ``RealHandleBridge`` which
        translates the real legacy DOM into the adapter's container format.

        Tests patch ``adapter_class`` or the import path to inject fakes.
        """
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        if getattr(self, "_use_real_handle", False):
            # Real path: validate config, resolve creds, bootstrap, bridge.
            # ``_create_session_handle`` also stores the resolved real URL
            # templates on ``self`` so the adapter can use them.
            session = self._create_session_handle()
            config = SessionControllerConfig(
                base_admissions_url=self._real_url_templates.admissions_url_template,
                base_evolutions_url=self._real_url_templates.evolutions_url_template,
                safe_renewal_tab_url=self._real_url_templates.safe_renewal_url,
            )
        else:
            session = self._create_session_handle()
            config = SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}"
            )
        adapter = self.adapter_class(session=session, config=config)
        return adapter

    def _create_session_handle(self):
        """Create a SessionHandle protocol implementation.

        By default returns the safe ``_StubSessionHandle`` so the command is
        NOT rollout-ready out of the box (no Chromium is launched).

        Opt into the real path with ``--real-handle``: it resolves and
        validates credentials and real URL templates, starts a
        ``PlaywrightSessionHandle`` (exclusive ``ExclusiveBrowserProfile``),
        bootstraps an authenticated legacy session, and wraps it in
        ``RealHandleBridge``, which translates the real legacy DOM
        (``#tabelaInternacoes`` table, evolution script/pre) into the
        synthetic containers the adapter expects. The bridge resolves the
        container contract at the code level but is **not validated against
        the real legacy UI**; keep ``--real-handle`` as a guarded
        manual-smoke flag until live validation.
        """
        if not getattr(self, "_use_real_handle", False):
            return _StubSessionHandle()

        return self._create_bootstrapped_real_handle()

    def _create_bootstrapped_real_handle(self):
        """Create, start, bootstrap, and bridge a real PlaywrightSessionHandle.

        Resolves and validates the real legacy URL templates and credentials
        BEFORE launching Chromium, so a missing-config failure cannot leak a
        half-started browser or claim any run. On a bootstrap failure after
        the browser has started, the handle is shut down before the sanitized
        error is re-raised as :class:`CommandError`.
        """
        from apps.ingestion.extractors.browser_profile import (
            ExclusiveBrowserProfile,
        )
        from apps.ingestion.extractors.legacy_session_bootstrap import (
            LegacyBootstrapError,
            bootstrap_legacy_session,
            resolve_legacy_url_templates,
        )
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.historical_extraction import (
            resolve_source_credentials,
        )

        # Validate configuration BEFORE launching the browser (fail fast).
        self._real_url_templates = resolve_legacy_url_templates()
        self._require_real_handle_config()
        try:
            credentials = resolve_source_credentials()
        except ValueError as exc:
            # resolve_source_credentials raises sanitized ValueErrors listing
            # the missing setting NAMES (never values). Surface as CommandError.
            raise CommandError(str(exc)) from exc

        profile = ExclusiveBrowserProfile(label="persistent-worker")
        handle = PlaywrightSessionHandle(profile=profile, headless=True)
        handle.start()
        try:
            # Bootstrap the authenticated legacy session on the root page.
            page = handle.ensure_current_page()
            bootstrap_legacy_session(
                page,
                credentials=credentials,
                login_timeout=_LOGIN_TIMEOUT_SECONDS,
            )
        except LegacyBootstrapError as exc:
            # Best-effort teardown, then surface a sanitized error.
            try:
                handle.shutdown()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            raise CommandError(str(exc)) from exc
        except CommandError:
            try:
                handle.shutdown()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            raise

        return RealHandleBridge(handle)

    def _require_real_handle_config(self) -> None:
        """Raise a sanitized CommandError if a required real URL template is missing.

        Checked before the browser is launched and before any run is claimed.
        """
        templates = self._real_url_templates
        missing: list[str] = []
        if not templates.admissions_url_template:
            missing.append("SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE")
        if not templates.evolutions_url_template:
            missing.append("SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE")
        if not templates.safe_renewal_url:
            missing.append("SOURCE_SYSTEM_SAFE_RENEWAL_URL")
        if missing:
            raise CommandError(
                "Cannot start --real-handle: missing real legacy URL "
                "template(s): " + ", ".join(missing)
                + ". Configure them before claiming any run."
            )

    # ------------------------------------------------------------------
    # Worker label
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_worker_label() -> str:
        """Resolve an operational worker label for identifying this process.

        Priority:
        1. ``SIRHOSP_WORKER_LABEL`` env var (if set and non-empty).
        2. ``persistent-worker`` default prefix.
        3. PID suffix to differentiate processes.

        Returns:
            Label in the format ``'<base>:<pid>'``.
        """
        base = os.environ.get("SIRHOSP_WORKER_LABEL", "") or _PERSISTENT_LABEL_PREFIX
        pid = os.getpid()
        return f"{base}:{pid}"

    # ------------------------------------------------------------------
    # Run claiming (same discipline as current worker)
    # ------------------------------------------------------------------

    @staticmethod
    def _claim_eligible_run(run_id: int | None = None) -> IngestionRun | None:
        """Claim the next eligible queued run respecting next_retry_at.

        Eligible = status='queued' AND (next_retry_at IS NULL OR
        next_retry_at <= now). Uses ``select_for_update(skip_locked=True)``
        for safe concurrent access.

        Args:
            run_id: When provided, claim only that run (still requiring it to
                be queued and eligible). Used by the manual smoke
                ``--run-id`` control.
        """
        from django.db.models import Q

        now = timezone.now()
        qs = (
            IngestionRun.objects
            .select_for_update(skip_locked=True)
            .filter(status="queued")
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        )
        if run_id is not None:
            qs = qs.filter(pk=run_id)
        return qs.order_by("pk").first()

    # ------------------------------------------------------------------
    # Loop mode
    # ------------------------------------------------------------------

    def _run_loop(self, adapter: PersistentExtractionAdapter, sleep_seconds: int) -> None:
        """Continuously poll and process queued runs until interrupted."""
        import signal
        import sys

        def _signal_handler(signum, frame):
            self.stdout.write(
                "\nReceived signal, shutting down persistent worker gracefully..."
            )
            sys.exit(0)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                "Persistent-session worker started in continuous mode "
                f"(sleep={sleep_seconds}s)."
            )
        )

        while True:
            if self._max_runs_reached():
                self.stdout.write(
                    f"Reached --max-runs limit ({self._max_runs}); exiting loop."
                )
                break
            try:
                close_old_connections()
                count = IngestionRun.objects.filter(status="queued").count()
            except (OperationalError, ProgrammingError) as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"[{timezone.now():%H:%M:%S}] Worker startup check failed "
                        f"({exc.__class__.__name__}): {exc}. "
                        f"Retrying in {sleep_seconds}s..."
                    )
                )
                close_old_connections()
                time.sleep(sleep_seconds)
                continue

            if count == 0:
                self.stdout.write(
                    f"[{timezone.now():%H:%M:%S}] No queued runs, "
                    f"sleeping {sleep_seconds}s..."
                )
                time.sleep(sleep_seconds)
                continue

            self.stdout.write(
                f"[{timezone.now():%H:%M:%S}] Found {count} queued run(s), "
                "processing..."
            )
            self._process_all_queued(adapter)

    # ------------------------------------------------------------------
    # Single-pass mode
    # ------------------------------------------------------------------

    def _process_once(self, adapter: PersistentExtractionAdapter) -> None:
        """Process all queued runs once and exit.

        Honors ``--run-id`` (scope to one run) and ``--max-runs`` (bound the
        number of processed runs).
        """
        run_id = getattr(self, "_run_id", None)
        if run_id is not None:
            scoped = IngestionRun.objects.filter(pk=run_id)
            exists = scoped.exists()
            eligible = scoped.filter(status="queued").exists()
            if not exists:
                self.stderr.write(
                    self.style.WARNING(
                        f"Run #{run_id} does not exist; nothing processed."
                    )
                )
                return
            if not eligible:
                self.stderr.write(
                    self.style.WARNING(
                        f"Run #{run_id} is not eligible (not queued); "
                        "nothing processed."
                    )
                )
                return
            self.stdout.write(f"Processing selected run #{run_id}...")
            self._process_all_queued(adapter)
            self.stdout.write(self.style.SUCCESS("Done."))
            return

        count = IngestionRun.objects.filter(status="queued").count()
        if count == 0:
            self.stdout.write("No queued runs to process.")
            return
        self.stdout.write(f"Processing {count} queued run(s)...")
        self._process_all_queued(adapter)
        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------
    # Process all queued
    # ------------------------------------------------------------------

    def _process_all_queued(self, adapter: PersistentExtractionAdapter) -> None:
        """Claim and process all eligible queued runs atomically.

        The persistent ``adapter`` (shared browser/session) is reused for
        every claim in this pass; it is NOT recreated per run.

        Respects ``--run-id`` (claim only that run) and ``--max-runs``
        (stop after that many processed runs).
        """
        while True:
            if self._max_runs_reached():
                self.stdout.write(
                    f"Reached --max-runs limit ({self._max_runs}); stopping."
                )
                break

            if not adapter.ensure_session_ready():
                self.stderr.write(
                    self.style.WARNING(
                        "Session not ready — skipping this claim cycle."
                    )
                )
                break

            with transaction.atomic():
                run = self._claim_eligible_run(getattr(self, "_run_id", None))
                if run is None:
                    break
                run.status = "running"
                run.save(update_fields=["status"])

            self._process_run(run, adapter)
            self._processed_count += 1

            # Conservative health gate between jobs: if the shared session
            # has degraded past a threshold, restart it before the next claim
            # rather than carrying a sick browser into the next run.
            if adapter.controller.restart_required():
                adapter.session.restart_browser()
                adapter.controller.reset_after_restart()

    def _max_runs_reached(self) -> bool:
        """Return whether the ``--max-runs`` cap has been reached.

        Returns ``False`` when ``--max-runs`` is unset (unlimited), preserving
        the default stub behavior of draining the eligible queue.
        """
        max_runs = getattr(self, "_max_runs", None)
        processed = getattr(self, "_processed_count", 0)
        return max_runs is not None and processed >= max_runs

    # ------------------------------------------------------------------
    # Process a single run
    # ------------------------------------------------------------------

    def _process_run(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process a single IngestionRun through the persistent adapter.

        Dispatches to admissions-only or full-sync based on intent.
        Heartbeat is refreshed via ``WorkerHeartbeat`` context manager.
        """
        params = run.parameters_json or {}
        intent = params.get("intent", "") or run.intent

        # Transition to running + record attempt start
        run.status = "running"
        run.attempt_count += 1
        if run.processing_started_at is None:
            run.processing_started_at = timezone.now()
        run.worker_label = self._resolve_worker_label()
        run.save(
            update_fields=[
                "status",
                "attempt_count",
                "processing_started_at",
                "worker_label",
            ]
        )

        IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=run.attempt_count,
        )

        with WorkerHeartbeat(run, interval_seconds=60):
            if intent == "admissions_only":
                self._process_admissions_only(run, adapter)
            elif intent == "full_sync":
                self._process_full_sync(run, adapter)
            else:
                # Unknown intent — treat as full_sync (backward compat)
                self._process_full_sync(run, adapter)

    # ------------------------------------------------------------------
    # Admissions-only processing via persistent adapter
    # ------------------------------------------------------------------

    def _process_admissions_only(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process an admissions-only run through the persistent adapter.

        Lifecycle:
        1. Call adapter.get_admission_snapshot() (includes session checkpoints).
        2. On success: mark run succeeded, adapter already cleaned tab.
        3. On data failure (missing container, invalid JSON):
           - Mark run failed/retry.
           - Call adapter.cleanup_after_failure() (close tab + mark processed).
        4. On session failure (not ready, renewal fail, nav fail):
           - Mark run failed/retry.
           - Do NOT call cleanup — no tab was opened.
        5. Check restart_required and restart if needed.
        """
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")

        # Build date range from parameters or use wide defaults
        start_date = params.get("start_date", "") or "2000-01-01"
        end_date = params.get("end_date", "") or timezone.now().strftime("%Y-%m-%d")

        stage_start = timezone.now()

        try:
            result = adapter.get_admission_snapshot(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
                timeout=_ADMISSIONS_TIMEOUT,
            )
        except InvalidJsonError as exc:
            # Data failure — tab was opened, need cleanup
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture "
                f"(invalid JSON from persistent session): {exc}"
            )
            return
        except SnapshotContainerMissingError as exc:
            # Data-level failure: a job tab was opened, so cleanup is required
            # before claiming another run (spec: "after each job or recoverable
            # job error"). Tab close is cleanup only, never renewal evidence.
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture "
                f"(snapshot data missing from persistent session): {exc}"
            )
            return
        except ExtractionError as exc:
            # Session-level failure (not ready, renewal fail, nav fail): no job
            # tab was opened, so tab cleanup is skipped.
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  Run #{run.pk} failed during admissions capture "
                f"(persistent session): {exc}"
            )
            return
        except Exception as exc:
            # Unexpected error — treat as session/infra failure
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        # Success — adapter already handled tab cleanup and mark_job_processed
        adm_seen = len(result)
        self._record_stage(
            run, "admissions_capture", "succeeded", stage_start,
        )

        # Persist metrics and mark succeeded
        run.admissions_seen = adm_seen
        run.admissions_created = adm_seen  # simplified: all seen are new here
        run.admissions_updated = 0
        run.events_processed = 0
        run.events_created = 0
        run.events_skipped = 0
        run.events_revised = 0
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.failure_reason = ""
        run.timed_out = False
        run.save()

        # Mark attempt as succeeded
        self._mark_latest_attempt_succeeded(run)

        # Close batch if all runs drained
        self._try_close_batch(run.batch)

        self.stdout.write(
            f"  Run #{run.pk} admissions-only succeeded (persistent session) "
            f"(admissions_seen={adm_seen})"
        )

    # ------------------------------------------------------------------
    # Full-sync processing via persistent adapter (PSW-S8)
    # ------------------------------------------------------------------

    def _process_full_sync(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process full-sync run through the persistent adapter.

        Lifecycle (matches current worker's ``_process_full_sync`` semantics):
        1. Capture admissions snapshot (fails run if error).
        2. Plan extraction windows (cache-first).
        3. If full coverage: succeed with zero events.
        4. Extract evolutions for gap windows.
        5. Ingest evolutions via shared ``ingest_evolutions`` service.
        6. Transition to 'succeeded' with metrics.
        7. On any failure after admissions: preserve admissions + fail run.
        """
        from apps.ingestion.services import (
            backfill_admission_ward_from_census,
            upsert_admission_snapshot,
        )
        from apps.patients.models import Patient

        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")

        # Resolve default dates
        snap_start = start_date or "2000-01-01"
        snap_end = end_date or timezone.now().strftime("%Y-%m-%d")

        # ------------------------------------------------------------------
        # Step 1: Capture admissions snapshot (mandatory — fail-fast)
        # ------------------------------------------------------------------
        adm_stage_start = timezone.now()
        try:
            admissions_data = adapter.get_admission_snapshot(
                patient_record=patient_record,
                start_date=snap_start,
                end_date=snap_end,
                timeout=_ADMISSIONS_TIMEOUT,
            )
        except (InvalidJsonError, SnapshotContainerMissingError) as exc:
            # Data-level failure — tab was opened, cleanup required
            self._record_stage(
                run, "admissions_capture", "failed", adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            return
        except ExtractionError as exc:
            # Session-level failure — no tab was opened
            self._record_stage(
                run, "admissions_capture", "failed", adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return
        except Exception as exc:
            self._record_stage(
                run, "admissions_capture", "failed", adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        # Create/get patient and upsert admissions
        patient, _ = Patient.objects.get_or_create(
            source_system="tasy",
            patient_source_key=patient_record,
            defaults={"name": ""},
        )
        adm_metrics = {"seen": len(admissions_data), "created": 0, "updated": 0}
        if admissions_data:
            upsert_result = upsert_admission_snapshot(
                patient=patient,
                admissions_snapshot=admissions_data,
            )
            adm_metrics["created"] = upsert_result.get("created", 0)
            adm_metrics["updated"] = upsert_result.get("updated", 0)

        # Enrich active admissions with ward/bed from the latest census
        # (admission snapshot does not carry setor/leito). Same behavior as
        # the current worker's _capture_admissions.
        backfill_admission_ward_from_census(patient)

        self._record_stage(
            run, "admissions_capture", "succeeded", adm_stage_start,
        )

        # ------------------------------------------------------------------
        # Step 2: Plan extraction windows (cache-first)
        # ------------------------------------------------------------------
        gap_stage_start = timezone.now()
        try:
            plan = plan_extraction_windows(
                patient_source_key=patient_record,
                source_system="tasy",
                start_date=snap_start,
                end_date=snap_end,
            )
        except Exception as exc:
            self._record_stage(
                run, "gap_planning", "failed", gap_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        run.gaps_json = plan["gaps"]
        self._record_stage(
            run, "gap_planning", "succeeded", gap_stage_start,
        )

        if plan["skip_extraction"]:
            # Full coverage — evolution_extraction skipped
            self._record_stage(
                run, "evolution_extraction", "skipped",
                started_at=timezone.now(),
            )
            run.admissions_seen = adm_metrics["seen"]
            run.admissions_created = adm_metrics["created"]
            run.admissions_updated = adm_metrics["updated"]
            run.events_processed = 0
            run.events_created = 0
            run.events_skipped = 0
            run.events_revised = 0
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.failure_reason = ""
            run.timed_out = False
            run.save()
            self._mark_latest_attempt_succeeded(run)
            self._try_close_batch(run.batch)
            self.stdout.write(
                f"  Run #{run.pk} full-sync succeeded (persistent session) — "
                f"skipped extraction (full coverage)."
            )
            return

        # ------------------------------------------------------------------
        # Step 3: Extract evolutions for each gap window
        # ------------------------------------------------------------------
        ev_stage_start = timezone.now()
        all_evolutions: list[dict] = []
        try:
            for window in plan["windows"]:
                evolutions = adapter.extract_evolutions(
                    patient_record=patient_record,
                    start_date=window["start_date"],
                    end_date=window["end_date"],
                    timeout=120,
                )
                all_evolutions.extend(evolutions)
        except (InvalidJsonError, SnapshotContainerMissingError, EvolutionPdfError) as exc:
            # Data-level failure with tab opened — cleanup
            self._record_stage(
                run, "evolution_extraction", "failed", ev_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            return
        except ExtractionError as exc:
            # Session-level failure
            self._record_stage(
                run, "evolution_extraction", "failed", ev_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return
        except Exception as exc:
            self._record_stage(
                run, "evolution_extraction", "failed", ev_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        self._record_stage(
            run, "evolution_extraction", "succeeded", ev_stage_start,
        )

        # ------------------------------------------------------------------
        # Step 4: Ingest evolutions via shared service
        # ------------------------------------------------------------------
        ingest_stage_start = timezone.now()
        try:
            ev_created, ev_skipped, ev_revised = ingest_evolutions(
                all_evolutions, run, patient=patient,
            )
        except Exception as exc:
            self._record_stage(
                run, "ingestion_persistence", "failed", ingest_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        self._record_stage(
            run, "ingestion_persistence", "succeeded", ingest_stage_start,
            details_json={
                "processed": len(all_evolutions),
                "created": ev_created,
                "skipped": ev_skipped,
                "revised": ev_revised,
            },
        )

        # Persist metrics and mark succeeded
        run.events_processed = len(all_evolutions)
        run.events_created = ev_created
        run.events_skipped = ev_skipped
        run.events_revised = ev_revised
        run.admissions_seen = adm_metrics["seen"]
        run.admissions_created = adm_metrics["created"]
        run.admissions_updated = adm_metrics["updated"]
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.failure_reason = ""
        run.timed_out = False
        run.save()

        self._mark_latest_attempt_succeeded(run)
        self._try_close_batch(run.batch)

        self.stdout.write(
            f"  Run #{run.pk} full-sync succeeded (persistent session) "
            f"(admissions_seen={adm_metrics['seen']}, "
            f"admissions_created={adm_metrics['created']}, "
            f"admissions_updated={adm_metrics['updated']}, "
            f"gaps={len(plan['windows'])}, "
            f"processed={len(all_evolutions)}, "
            f"created={ev_created}, "
            f"skipped={ev_skipped}, "
            f"revised={ev_revised})"
        )

    # ------------------------------------------------------------------
    # Failure handling (reuses taxonomy from current worker)
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_failure_reason(exc: Exception) -> tuple[str, bool]:
        """Classify an exception into normalized failure taxonomy."""
        if isinstance(exc, InvalidJsonError):
            return ("invalid_payload", False)
        if isinstance(exc, SnapshotContainerMissingError):
            # Page rendered but the expected data container was absent — a
            # data-level issue, not a session/availability issue.
            return ("invalid_payload", False)
        if isinstance(exc, EvolutionPdfError):
            # PSW-S11: real legacy PDF flow failed after a tab was opened —
            # data-level/recoverable (e.g. PDF unavailable, invalid PDF).
            return ("invalid_payload", False)
        if isinstance(exc, ExtractionError):
            return ("source_unavailable", False)
        return ("unexpected_exception", False)

    @staticmethod
    def _record_stage(run, stage_name, status, started_at,
                      finished_at=None, details_json=None):
        """Persist a stage metric record for the given run."""
        from apps.ingestion.models import IngestionRunStageMetric

        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    @staticmethod
    def _stage_error_details(exc: Exception) -> dict:
        """Build normalized stage-level error details payload."""
        return {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }

    @staticmethod
    def _mark_latest_attempt_succeeded(run: IngestionRun) -> None:
        """Mark the latest attempt for this run as succeeded."""
        attempt = (
            IngestionRunAttempt.objects
            .filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        if attempt is not None:
            attempt.status = "succeeded"
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "finished_at"])

    @staticmethod
    def _try_close_batch(batch) -> None:
        """Close the batch if no queued/running runs remain."""
        try_close_batch(batch)

    def _mark_run_failed(self, run: IngestionRun, exc: Exception) -> None:
        """Transition run to failed with retry logic.

        If attempts remain, requeue with backoff. Otherwise mark as
        terminally failed.
        """
        failure_reason, timed_out = self._classify_failure_reason(exc)
        now = timezone.now()

        # Update the existing attempt record
        attempt = (
            IngestionRunAttempt.objects
            .filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        if attempt is not None:
            attempt.finished_at = now
            attempt.status = "failed"
            attempt.failure_reason = failure_reason
            attempt.timed_out = timed_out
            attempt.error_message = str(exc)
            attempt.save(
                update_fields=[
                    "finished_at",
                    "status",
                    "failure_reason",
                    "timed_out",
                    "error_message",
                ]
            )

        if run.attempt_count < run.max_attempts:
            run.status = "queued"
            run.next_retry_at = now + timedelta(seconds=60)
            run.failure_reason = failure_reason
            run.timed_out = timed_out
            run.error_message = str(exc)
            run.save(
                update_fields=[
                    "status",
                    "next_retry_at",
                    "failure_reason",
                    "timed_out",
                    "error_message",
                ]
            )
            self.stdout.write(
                f"  Run #{run.pk} failed (attempt {run.attempt_count}/"
                f"{run.max_attempts}), requeued at {run.next_retry_at}"
            )
        else:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = now
            run.failure_reason = failure_reason
            run.timed_out = timed_out
            run.next_retry_at = None
            run.save(
                update_fields=[
                    "status",
                    "error_message",
                    "finished_at",
                    "failure_reason",
                    "timed_out",
                    "next_retry_at",
                ]
            )
            self._try_close_batch(run.batch)
            self.stderr.write(
                f"  Run #{run.pk} failed permanently "
                f"(attempt {run.attempt_count}/{run.max_attempts}): {exc}"
            )
