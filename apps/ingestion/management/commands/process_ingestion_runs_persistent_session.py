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

Non-goals (deferred to PSW-S5+):
- Full-sync evolution extraction.
- Real Playwright ``SessionHandle`` implementation (production wiring).

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

from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.ingestion.batch_closure import try_close_batch
from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)

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

    def handle(self, *args, **options):
        loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]

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

        Calls the handle's ``restart_browser`` as a synchronous teardown
        hook. The real Playwright wiring (future slice) must release the
        exclusive profile here via ``ExclusiveBrowserProfile.release_after_shutdown``
        after the browser has shut down.
        """
        try:
            adapter.session.restart_browser()
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

        In production, the SessionHandle must be wired by a future slice.
        For now, this creates the adapter with a minimal handle stub that
        returns safe defaults (disconnected, empty HTML, etc.) but never
        performs actual browser actions.

        Tests patch ``adapter_class`` or the import path to inject fakes.
        """
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        config = SessionControllerConfig(base_admissions_url="/admissions/{patient_record}")
        adapter = self.adapter_class(
            session=self._create_session_handle(),
            config=config,
        )
        return adapter

    @staticmethod
    def _create_session_handle():
        """Create a SessionHandle protocol implementation (stub).

        Returns a stub that implements the ``SessionHandle`` protocol
        but never performs real browser actions. Production deployment
        must override this method or replace ``adapter_class`` with a
        version wired to a real Playwright-based handle.
        """
        return _StubSessionHandle()

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
    def _claim_eligible_run() -> IngestionRun | None:
        """Claim the next eligible queued run respecting next_retry_at.

        Eligible = status='queued' AND (next_retry_at IS NULL OR
        next_retry_at <= now). Uses ``select_for_update(skip_locked=True)``
        for safe concurrent access.
        """
        from django.db.models import Q

        now = timezone.now()
        return (
            IngestionRun.objects
            .select_for_update(skip_locked=True)
            .filter(status="queued")
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
            .order_by("pk")
            .first()
        )

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
        """Process all queued runs once and exit."""
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
        """
        while True:
            if not adapter.ensure_session_ready():
                self.stderr.write(
                    self.style.WARNING(
                        "Session not ready — skipping this claim cycle."
                    )
                )
                break

            with transaction.atomic():
                run = self._claim_eligible_run()
                if run is None:
                    break
                run.status = "running"
                run.save(update_fields=["status"])

            self._process_run(run, adapter)

            # Conservative health gate between jobs: if the shared session
            # has degraded past a threshold, restart it before the next claim
            # rather than carrying a sick browser into the next run.
            if adapter.controller.restart_required():
                adapter.session.restart_browser()
                adapter.controller.reset_after_restart()

    # ------------------------------------------------------------------
    # Process a single run
    # ------------------------------------------------------------------

    def _process_run(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process a single IngestionRun through the persistent adapter.

        Supports only ``admissions_only`` intent in this slice.
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
            else:
                self._process_admissions_only(
                    run, adapter
                )  # same path for now (no full-sync)

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
