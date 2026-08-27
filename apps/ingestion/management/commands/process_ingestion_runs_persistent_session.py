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

PSW-S12 status:
- ``SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE`` and
  ``SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE`` are NO LONGER REQUIRED for the
  ``--real-handle`` smoke path. The real legacy navigation now uses action-
  based UI actions (modeled after ``path2.py``) instead of reloadable deep-
  link URL templates.
- ``RealHandleBridge`` exposes ``navigate_to_admissions(patient_record)``
  which performs the UI action sequence: ensure search screen, fill
  prontuário, click Pesquisa Avançada, click Internações, wait for
  frame_pol, read table rows, and build the canonical admission snapshot.
- The adapter's ``get_admission_snapshot()`` detects and uses
  ``navigate_to_admissions`` when available (real handle path), falling back
  to URL-template ``open_tab`` for stub/test compatibility.
- ``SOURCE_SYSTEM_SAFE_RENEWAL_URL`` is optional; when not configured,
  proactive renewal is unavailable but the manual smoke path still works.
- This is still a guarded MANUAL SMOKE path — full-sync real evolution
  navigation is scoped to PSW-S13.

PSW-S24-PRE status:
- The real-handle CLI exposes a CLOSED mode matrix, validated before any
  adapter/browser creation or run mutation:

  1. stub (no ``--real-handle``): existing queue behavior unchanged;
  2. single real smoke: ``--real-handle --run-id ID --max-runs 1``;
  3. bounded validation: repeatable ``--validation-run-id`` (two through four
     distinct positive IDs, operator order) WITH ``--real-handle`` and
     ``--max-runs`` equal to the count; every listed row is preflichted
     before one real adapter/bootstrap, runs reuse the same authenticated
     session, processing never falls through to an unlisted row, and a claim
     race, job failure, or restart failure leaves later selected rows
     untouched; bounded output carries no run IDs;
  4. continuous real queue: ``--real-handle --loop --enable-real-queue``;
     default-off and forbidden with ``--run-id``/``--validation-run-id``/
     ``--max-runs``. ``--real-handle --loop`` without the opt-in fails before
     adapter/browser creation.

- Neither the bounded nor the continuous real mode is rollout-ready. Both stay
  disabled until authorized PSW-S24 live validation succeeds.

Usage::

    # Single pass
    uv run python manage.py process_ingestion_runs_persistent_session

    # Continuous loop
    uv run python manage.py process_ingestion_runs_persistent_session \\
        --loop --sleep-seconds 5
"""

from __future__ import annotations

import argparse
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
    EmptyAdmissionsSnapshotError,
    ExtractionError,
    InvalidJsonError,
    SnapshotContainerMissingError,
    ensure_nonempty_batch_admissions,
)
from apps.ingestion.extractors.legacy_navigation import (
    DEMOGRAPHICS_IDENTITY_MESSAGE,
    demographics_identity_matches,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.session_policy import TabCleanupOutcome
from apps.ingestion.gap_planner import plan_extraction_windows

# ---------------------------------------------------------------------------
# Reuse WorkerHeartbeat from the existing worker
# ---------------------------------------------------------------------------
from apps.ingestion.management.commands.process_ingestion_runs import (
    WorkerHeartbeat,
)
from apps.ingestion.models import IngestionRun, IngestionRunAttempt
from apps.ingestion.services import (
    enqueue_most_recent_admission_full_sync,
    persist_admissions_snapshot,
    queue_demographics_only_run,
    upsert_patient_demographics,
)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_ADMISSIONS_TIMEOUT = 120
"""Default timeout (seconds) for admissions snapshot extraction."""

_DEMOGRAPHICS_TIMEOUT = 120
"""Default timeout (seconds) for persistent demographics extraction.

Reuses the already-open persistent page/context (no subprocess), so this
matches the admissions-style bounded wait rather than the current worker's
5-minute subprocess timeout."""

# Field count metric: mirror the current worker's exact 25-field list so the
# ``demographics_fields_extracted`` metric is identical across workers.
_DEMOGRAPHICS_FIELD_COUNT_FIELDS: tuple[str, ...] = (
    "name", "social_name", "date_of_birth", "gender",
    "gender_identity", "mother_name", "father_name",
    "race_color", "birthplace", "nationality",
    "marital_status", "education_level", "profession",
    "cns", "cpf", "phone_home", "phone_cellular",
    "phone_contact", "street", "address_number",
    "address_complement", "neighborhood", "city",
    "state", "postal_code",
)

_LOGIN_TIMEOUT_SECONDS = 180
"""Production-proven timeout for every real legacy login page action."""

_DJANGO_ALLOW_ASYNC_UNSAFE_ENV = "DJANGO_ALLOW_ASYNC_UNSAFE"
"""Django guard required while Playwright's synchronous event loop is active."""

# PSW-S17 post-cbf50c1 (D18/R2): constant sanitized messages for command
# surfaces. No arbitrary ``str(exc)``, dynamic exception class, URL,
# selector, credential, cookie, patient record, admission key, raw HTML,
# subprocess preview, stdout, or stderr may reach stdout/stderr, CommandError
# text, logs, or cause/context chains.
_TEARDOWN_FAILURE_MESSAGE = (
    "Persistent session teardown encountered an error (sanitized)."
)
_CREDENTIAL_RESOLUTION_MESSAGE = (
    "Source system credentials are not configured."
)
_BOOTSTRAP_FAILURE_MESSAGE = "Persistent session bootstrap failed."
_STARTUP_DB_RETRY_MESSAGE = (
    "Worker startup check failed; retrying."
)

# PSW-S19 R6: default lifecycle configuration (closed set). These mirror the
# conservative defaults of ``SessionControllerConfig`` and are exposed through
# one documented CLI path on this command.
_DEFAULT_MAX_JOBS = 50
_DEFAULT_MAX_LIFETIME_SECONDS = 3600
_DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
_DEFAULT_RENEWAL_THRESHOLD_SECONDS = 600
_DEFAULT_HEADLESS = True
_INVALID_LIFELIFE_CONFIG_MESSAGE = (
    "Persistent-session lifecycle configuration is invalid "
    "(max jobs, max lifetime, consecutive failures, and renewal threshold "
    "must all be positive integers)."
)

# PSW-S24-PRE: closed real-handle CLI mode labels.
_MODE_STUB = "stub"
_MODE_SINGLE_SMOKE = "single_smoke"
_MODE_BOUNDED = "bounded"
_MODE_CONTINUOUS_REAL = "continuous_real"

# Single real smoke messages (preserved verbatim for the R2 regression).
_REAL_HANDLE_REQUIRES_RUN_ID = (
    "--real-handle requires --run-id to avoid draining the "
    "production queue. Specify a single queued IngestionRun id "
    "for the manual smoke."
)
_REAL_HANDLE_REQUIRES_MAX_RUNS_ONE = (
    "--real-handle requires --max-runs 1 to bound the manual smoke "
    "to a single run. Pass --max-runs 1 explicitly."
)

# Continuous real queue opt-in messages (R8).
_ENABLE_REAL_QUEUE_REQUIRES_REAL_AND_LOOP = (
    "--enable-real-queue is valid only with both --real-handle and --loop."
)
_ENABLE_REAL_QUEUE_FORBIDS_SELECTION = (
    "--enable-real-queue forbids --run-id, --validation-run-id, and "
    "--max-runs."
)
_REAL_LOOP_REQUIRES_ENABLE_REAL_QUEUE = (
    "--real-handle --loop requires --enable-real-queue to enter the "
    "continuous real queue. Without the opt-in the real loop stays disabled."
)

# Bounded validation mode messages (R1/R3/R4/R7/R9). No run IDs, patient
# identifiers, or source data: ordinal/count information only.
_BOUNDED_REQUIRES_REAL_HANDLE_MESSAGE = (
    "Bounded validation requires --real-handle so the allow-list runs under "
    "one real authenticated session."
)
_BOUNDED_FORBIDS_LOOP_RUN_ID = (
    "Bounded validation mode forbids --loop and --run-id."
)
_BOUNDED_SIZE_MESSAGE = (
    "Bounded validation requires between two and four --validation-run-id "
    "values."
)
_BOUNDED_DISTINCT_MESSAGE = (
    "Bounded validation --validation-run-id values must be distinct."
)
_BOUNDED_POSITIVE_MESSAGE = (
    "Bounded validation --validation-run-id values must be positive."
)
_BOUNDED_REQUIRES_MAX_RUNS = (
    "Bounded validation requires --max-runs equal to the number of "
    "--validation-run-id values."
)
_BOUNDED_MAX_RUNS_MISMATCH = (
    "Bounded validation requires --max-runs equal to the number of "
    "--validation-run-id values."
)
_BOUNDED_ROW_MISSING_MESSAGE = (
    "A selected validation row does not exist; nothing processed."
)
_BOUNDED_ROW_NOT_QUEUED_MESSAGE = (
    "A selected validation row is not queued; nothing processed."
)
_BOUNDED_ROW_RETRY_NOT_DUE_MESSAGE = (
    "A selected validation row retry is not yet due; nothing processed."
)
_BOUNDED_ROW_UNSUPPORTED_INTENT_MESSAGE = (
    "A selected validation row has an unsupported intent; nothing processed."
)
_BOUNDED_ROW_UNCLAIMABLE_MESSAGE = (
    "A selected validation row is no longer claimable; stopping the "
    "bounded sequence."
)
_BOUNDED_ROW_NOT_SUCCEEDED_MESSAGE = (
    "A selected validation row did not finish as succeeded; stopping the "
    "bounded sequence."
)
_BOUNDED_RESTART_FAILED_MESSAGE = (
    "Persistent session restart failed during bounded validation; stopping "
    "the bounded sequence."
)
_BOUNDED_SESSION_NOT_READY_MESSAGE = (
    "Session not ready during bounded validation; stopping the bounded "
    "sequence."
)

_PERSISTENT_LABEL_PREFIX = "persistent-worker"
"""Default worker label prefix when SIRHOSP_WORKER_LABEL is not set."""

# ---------------------------------------------------------------------------
# Explicit supported-intent contract (PSW-S14)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Explicit supported-intent contract (PSW-S14)
# Single source of truth: _DISPATCH_MAP is the declaration; _ENABLED_INTENTS
# is derived from its keys and cannot drift.
# ---------------------------------------------------------------------------

_DISPATCH_MAP: dict[str, str] = {
    "admissions_only": "admissions_only",
    "demographics_only": "demographics_only",
    "full_sync": "full_sync",
    "full_admission_sync": "full_sync",
}
"""Maps queued intent to dispatch action.

``full_admission_sync`` is an explicit alias that dispatches to the same
full-sync code path as ``full_sync``. ``demographics_only`` is enabled in
PSW-S16 and dispatches to the persistent demographics path
(``_process_demographics_only``) through the already-authenticated page.
This is the single declaration of which intents are supported;
``_ENABLED_INTENTS`` is derived from its keys.
"""

_ENABLED_INTENTS: frozenset[str] = frozenset(_DISPATCH_MAP)
"""Intents the persistent worker MAY claim during normal polling.

Derived from ``_DISPATCH_MAP`` keys — cannot drift independently.
Empty or unknown intents must never fall through to full-sync.
"""



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

    def supports_real_evolution_actions(self) -> bool:
        """PSW-S20-C1: explicit stub capability (URL/container path)."""
        return False

    def click_selector(self, selector: str) -> None:
        pass

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        return False

    def get_tab_classes(self) -> list[str]:
        return []

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        return TabCleanupOutcome.ROOT_ONLY

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
                "RealHandleBridge instead of the safe stub. Selects the real "
                "session for one of three guarded real modes: single smoke "
                "(--run-id ID --max-runs 1), bounded live validation "
                "(--validation-run-id IDs --max-runs N), or the explicitly "
                "opted-in continuous real queue (--loop --enable-real-queue). "
                "NOT production rollout-ready; keep guarded."
            ),
        )
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help=(
                "Claim only this IngestionRun id (must be queued and "
                "eligible). Required for the single real smoke "
                "(--real-handle --max-runs 1) and forbidden in bounded and "
                "continuous real modes."
            ),
        )
        parser.add_argument(
            "--max-runs",
            type=int,
            default=None,
            help=(
                "Stop after processing this many runs. Equals 1 for the "
                "single real smoke and the selected-ID count for bounded "
                "validation. Useful to bound manual smoke tests "
                "(e.g. --max-runs 1)."
            ),
        )
        # PSW-S19 R6: the closed lifecycle/headless configuration set, exposed
        # through one documented CLI path. Positive ranges are validated before
        # any run is claimed (see ``_validate_lifecycle_options``).
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=_DEFAULT_MAX_JOBS,
            help=(
                "Maximum jobs processed before a controlled browser restart "
                f"(default: {_DEFAULT_MAX_JOBS}). Must be positive."
            ),
        )
        parser.add_argument(
            "--max-lifetime-seconds",
            type=int,
            default=_DEFAULT_MAX_LIFETIME_SECONDS,
            help=(
                "Maximum browser lifetime in seconds before a controlled "
                f"restart (default: {_DEFAULT_MAX_LIFETIME_SECONDS}). "
                "Must be positive."
            ),
        )
        parser.add_argument(
            "--max-consecutive-failures",
            type=int,
            default=_DEFAULT_MAX_CONSECUTIVE_FAILURES,
            help=(
                "Maximum consecutive session/login/cleanup failures before a "
                f"controlled restart (default: {_DEFAULT_MAX_CONSECUTIVE_FAILURES})."
                " Must be positive."
            ),
        )
        parser.add_argument(
            "--renewal-threshold-seconds",
            type=int,
            default=_DEFAULT_RENEWAL_THRESHOLD_SECONDS,
            help=(
                "Proactively renew the legacy session when remaining time "
                "falls below this many seconds "
                f"(default: {_DEFAULT_RENEWAL_THRESHOLD_SECONDS}). Must be positive."
            ),
        )
        parser.add_argument(
            "--headless",
            action=argparse.BooleanOptionalAction,
            default=_DEFAULT_HEADLESS,
            help=(
                "Run Chromium headless (--headless) or headed (--no-headless). "
                f"Default: {'headless' if _DEFAULT_HEADLESS else 'headed'}."
            ),
        )
        # PSW-S24-PRE: closed real-handle CLI mode matrix options. These two
        # options, together with --real-handle/--run-id/--max-runs/--loop, form
        # the four closed modes validated in ``_validate_cli_mode`` before any
        # adapter/browser creation or run mutation.
        parser.add_argument(
            "--validation-run-id",
            type=int,
            action="append",
            default=None,
            help=(
                "Operator-selected queued IngestionRun id for bounded live "
                "validation. Requires --real-handle. Repeat two through four "
                "times in operator order; pair with --max-runs equal to the "
                "count. Forbids --loop, --run-id, and --enable-real-queue."
            ),
        )
        parser.add_argument(
            "--enable-real-queue",
            action="store_true",
            default=False,
            help=(
                "Opt in to the existing continuous real queue loop. Requires "
                "both --real-handle and --loop; forbids --run-id, "
                "--validation-run-id, and --max-runs. Default is off; the real "
                "queue worker is NOT production rollout-ready."
            ),
        )

    def handle(self, *args, **options):
        self._loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]
        self._use_real_handle: bool = options["real_handle"]
        self._run_id: int | None = options.get("run_id")
        self._max_runs: int | None = options.get("max_runs")
        self._processed_count: int = 0
        # PSW-S19 R6: lifecycle/headless configuration from the closed CLI set.
        self._max_jobs: int = options["max_jobs"]
        self._max_lifetime_seconds: int = options["max_lifetime_seconds"]
        self._max_consecutive_failures: int = options["max_consecutive_failures"]
        self._renewal_threshold_seconds: int = options["renewal_threshold_seconds"]
        self._headless: bool = options["headless"]
        # PSW-S24-PRE: closed real-handle CLI mode matrix options.
        self._validation_run_ids: list[int] = list(
            options.get("validation_run_id") or []
        )
        self._enable_real_queue: bool = options["enable_real_queue"]
        # PSW-S24-PRE-C1 R3: 1-based ordinal of the bounded row currently
        # being processed, used to label bounded output without run PKs.
        self._bounded_ordinal: int = 0

        # PSW-S19 R6: validate positive ranges before any claim (no browser,
        # no adapter, no run mutated). Invalid thresholds fail fast here.
        self._validate_lifecycle_options()

        # PSW-S24-PRE R1: validate the closed CLI mode matrix and resolve
        # exactly one mode before any adapter/browser creation or run mutation.
        # Every combination outside the matrix fails here.
        self._validate_cli_mode()

        # All-or-nothing preflight for the bounded allow-list runs before one
        # adapter/bootstrap is created. A single selected run (--run-id),
        # whether on the stub path or the single real smoke, is preflichted
        # before any adapter/browser creation (unchanged behavior).
        if self._mode == _MODE_BOUNDED:
            if not self._preflight_bounded_runs():
                return
        elif self._run_id is not None:
            if not self._preflight_selected_run():
                return

        guard_was_set = _DJANGO_ALLOW_ASYNC_UNSAFE_ENV in os.environ
        guard_previous = os.environ.get(_DJANGO_ALLOW_ASYNC_UNSAFE_ENV)
        if self._use_real_handle:
            # Playwright's synchronous API keeps an asyncio dispatcher loop
            # active on this dedicated command thread. Django therefore
            # classifies otherwise synchronous ORM calls as async-unsafe.
            # This command executes no concurrent async ORM work. Enable
            # Django's documented escape hatch only while the explicit real
            # handle, its synchronous ORM work, and its teardown are active.
            os.environ[_DJANGO_ALLOW_ASYNC_UNSAFE_ENV] = "true"

        adapter: PersistentExtractionAdapter | None = None
        try:
            # The adapter (and its persistent browser/session) is created ONCE
            # at startup and reused across all claimed runs. This is the core
            # persistence guarantee of this worker (see design Decision 2 /
            # spec "Browser and session reuse").
            adapter = self._create_adapter()
            if self._mode == _MODE_BOUNDED:
                self._process_bounded_sequence(adapter)
            elif self._loop:
                # Stub continuous loop or the opted-in continuous real queue.
                self._run_loop(adapter, sleep_seconds=sleep_seconds)
            else:
                self._process_once(adapter)
        finally:
            if adapter is not None:
                self._shutdown_adapter(adapter)
            if self._use_real_handle:
                if guard_was_set:
                    assert guard_previous is not None
                    os.environ[_DJANGO_ALLOW_ASYNC_UNSAFE_ENV] = guard_previous
                else:
                    os.environ.pop(_DJANGO_ALLOW_ASYNC_UNSAFE_ENV, None)

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
        except Exception:  # noqa: BLE001 - best-effort teardown logging
            self.stderr.write(
                self.style.WARNING(_TEARDOWN_FAILURE_MESSAGE)
            )

    # ------------------------------------------------------------------
    # Adapter creation (overridable for tests)
    # ------------------------------------------------------------------

    def _validate_lifecycle_options(self) -> None:
        """Validate the closed lifecycle configuration set (PSW-S19 R6).

        Raises a sanitized ``CommandError`` before any run is claimed when a
        threshold is not a positive integer. The ``SessionControllerConfig``
        constructor re-validates defensively, but this layer surfaces a clean
        command-level error and guarantees no browser/adapter is created and no
        run is mutated on invalid input.
        """
        thresholds = (
            ("--max-jobs", self._max_jobs),
            ("--max-lifetime-seconds", self._max_lifetime_seconds),
            ("--max-consecutive-failures", self._max_consecutive_failures),
            ("--renewal-threshold-seconds", self._renewal_threshold_seconds),
        )
        for _flag, value in thresholds:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise CommandError(_INVALID_LIFELIFE_CONFIG_MESSAGE)

    def _validate_cli_mode(self) -> None:
        """Validate the closed real-handle CLI mode matrix (PSW-S24-PRE R1).

        Resolves exactly one of four modes and raises a sanitized
        ``CommandError`` for any combination outside the matrix:

        - stub: no ``--real-handle`` (existing behavior unchanged);
        - single real smoke: ``--real-handle --run-id ID --max-runs 1``;
        - bounded validation: repeatable ``--validation-run-id`` of two
          through four distinct positive IDs in operator order WITH
          ``--real-handle`` and ``--max-runs`` equal to the count.
        - continuous real queue: ``--real-handle --loop --enable-real-queue``.

        Every other combination fails before ``_create_adapter()`` and before
        any run mutation. Sets ``self._mode`` for dispatch.
        """
        real = bool(getattr(self, "_use_real_handle", False))
        loop = bool(getattr(self, "_loop", False))
        run_id = getattr(self, "_run_id", None)
        max_runs = getattr(self, "_max_runs", None)
        validation_ids = list(getattr(self, "_validation_run_ids", None) or [])
        enable_real_queue = bool(getattr(self, "_enable_real_queue", False))

        if enable_real_queue:
            if not (real and loop):
                raise CommandError(_ENABLE_REAL_QUEUE_REQUIRES_REAL_AND_LOOP)
            if run_id is not None or validation_ids or max_runs is not None:
                raise CommandError(_ENABLE_REAL_QUEUE_FORBIDS_SELECTION)
            self._mode = _MODE_CONTINUOUS_REAL
            return

        if validation_ids:
            if not real:
                raise CommandError(_BOUNDED_REQUIRES_REAL_HANDLE_MESSAGE)
            if loop or run_id is not None:
                raise CommandError(_BOUNDED_FORBIDS_LOOP_RUN_ID)
            if len(validation_ids) < 2 or len(validation_ids) > 4:
                raise CommandError(_BOUNDED_SIZE_MESSAGE)
            if len(set(validation_ids)) != len(validation_ids):
                raise CommandError(_BOUNDED_DISTINCT_MESSAGE)
            if any(_id <= 0 for _id in validation_ids):
                raise CommandError(_BOUNDED_POSITIVE_MESSAGE)
            if max_runs is None:
                raise CommandError(_BOUNDED_REQUIRES_MAX_RUNS)
            if max_runs != len(validation_ids):
                raise CommandError(_BOUNDED_MAX_RUNS_MISMATCH)
            self._mode = _MODE_BOUNDED
            return

        if real and loop:
            # --real-handle --loop without the explicit opt-in still fails
            # before adapter/browser creation and before a claim.
            raise CommandError(_REAL_LOOP_REQUIRES_ENABLE_REAL_QUEUE)

        if real:
            # Single real smoke: exactly one --run-id and --max-runs 1.
            if run_id is None:
                raise CommandError(_REAL_HANDLE_REQUIRES_RUN_ID)
            if max_runs != 1:
                raise CommandError(_REAL_HANDLE_REQUIRES_MAX_RUNS_ONE)
            self._mode = _MODE_SINGLE_SMOKE
            return

        self._mode = _MODE_STUB

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
                max_jobs_per_session=getattr(self, "_max_jobs", _DEFAULT_MAX_JOBS),
                max_lifetime_seconds=getattr(
                    self, "_max_lifetime_seconds", _DEFAULT_MAX_LIFETIME_SECONDS
                ),
                max_consecutive_failures=getattr(
                    self,
                    "_max_consecutive_failures",
                    _DEFAULT_MAX_CONSECUTIVE_FAILURES,
                ),
                renewal_threshold_seconds=getattr(
                    self,
                    "_renewal_threshold_seconds",
                    _DEFAULT_RENEWAL_THRESHOLD_SECONDS,
                ),
            )
        else:
            session = self._create_session_handle()
            config = SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}",
                max_jobs_per_session=getattr(self, "_max_jobs", _DEFAULT_MAX_JOBS),
                max_lifetime_seconds=getattr(
                    self, "_max_lifetime_seconds", _DEFAULT_MAX_LIFETIME_SECONDS
                ),
                max_consecutive_failures=getattr(
                    self,
                    "_max_consecutive_failures",
                    _DEFAULT_MAX_CONSECUTIVE_FAILURES,
                ),
                renewal_threshold_seconds=getattr(
                    self,
                    "_renewal_threshold_seconds",
                    _DEFAULT_RENEWAL_THRESHOLD_SECONDS,
                ),
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
        # PSW-S17 post-cbf50c1 (D18/R2): surface a CONSTANT CommandError
        # with NO cause/context chain. The raise happens OUTSIDE the
        # ``except`` handler so Python does not auto-link the raw exception
        # as ``__context__`` (``from None`` only suppresses the *display* of
        # ``__context__``; it does not clear the reference, which would still
        # carry the raw exception text).
        credential_resolution_failed = False
        try:
            credentials = resolve_source_credentials()
        except ValueError:
            credential_resolution_failed = True
        if credential_resolution_failed:
            raise CommandError(_CREDENTIAL_RESOLUTION_MESSAGE)

        profile = ExclusiveBrowserProfile(label="persistent-worker")
        # PSW-S19 R6: the --headless/--no-headless CLI value reaches the
        # concrete Playwright handle.
        handle = PlaywrightSessionHandle(
            profile=profile, headless=getattr(self, "_headless", _DEFAULT_HEADLESS)
        )
        handle.start()
        # PSW-S19 R3: the bridge owns the sanitized bootstrap boundary so the
        # same login + #tempoSessao readiness can be re-run after every restart.
        bridge = RealHandleBridge(
            handle,
            credentials=credentials,
            login_timeout=_LOGIN_TIMEOUT_SECONDS,
        )
        # Same no-context-chain pattern for bootstrap failures (see above).
        bootstrap_failed = False
        try:
            # Bootstrap the authenticated legacy session on the root page via
            # the bridge boundary (reused verbatim on restart+rebootstrap).
            bridge.bootstrap()
        except LegacyBootstrapError:
            # Best-effort teardown; the sanitized CommandError is raised
            # outside this handler to avoid linking the raw chain.
            try:
                handle.shutdown()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            bootstrap_failed = True
        except CommandError:
            try:
                handle.shutdown()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            raise
        if bootstrap_failed:
            raise CommandError(_BOOTSTRAP_FAILURE_MESSAGE)

        return bridge

    def _require_real_handle_config(self) -> None:
        """Raise a sanitized CommandError if required real config is missing.

        PSW-S12: ``SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE`` and
        ``SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE`` are no longer required —
        the real legacy system uses action-based UI navigation
        (``navigate_to_admissions``), not reloadable deep-link URL templates.

        ``SOURCE_SYSTEM_SAFE_RENEWAL_URL`` is optional; when not configured,
        proactive renewal is not available but the manual smoke path still
        works.

        Checked before the browser is launched and before any run is claimed.
        """
        # Only SOURCE_SYSTEM_URL, USERNAME, and PASSWORD are required.
        # URL templates are no longer required (PSW-S12 action navigation).
        pass

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
    def _eligible_work_filter():
        """Return a Q expression for eligible persistent-worker work.

        A run is eligible when:
        - status=queued
        - intent is one of the enabled intents
        - next_retry_at IS NULL OR next_retry_at <= now

        Reused by both the polling loop and the claiming method so their
        eligibility rules are identical.
        """
        from django.db.models import Q

        return (
            Q(status="queued")
            & Q(intent__in=_ENABLED_INTENTS)
            & (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now()))
        )

    @staticmethod
    def _claim_eligible_run(run_id: int | None = None) -> IngestionRun | None:
        """Claim the next eligible queued run respecting next_retry_at.

        Uses ``select_for_update(skip_locked=True)`` for safe concurrent
        access.

        During normal polling (``run_id`` is None), only runs with an
        enabled intent are eligible (see ``_eligible_work_filter()``).
        ``demographics_only``, empty, and unknown intents are NOT claimed.

        When ``--run-id`` is provided, the caller must have validated the
        run via ``_preflight_selected_run()`` before reaching this method.
        The intent and retry filters are not applied so the specific PK
        can be claimed under the preflight check.

        Args:
            run_id: When provided, claim only that run (still requiring it to
                be queued). Used by the manual smoke ``--run-id`` control.
        """

        if run_id is not None:
            # --run-id path: preflight already validated. Claim by PK only.
            return (
                IngestionRun.objects
                .select_for_update(skip_locked=True)
                .filter(pk=run_id, status="queued")
                .order_by("pk")
                .first()
            )

        # Normal polling: use the shared eligibility filter.
        return (
            IngestionRun.objects
            .select_for_update(skip_locked=True)
            .filter(Command._eligible_work_filter())
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
            if self._max_runs_reached():
                self.stdout.write(
                    f"Reached --max-runs limit ({self._max_runs}); exiting loop."
                )
                break
            try:
                close_old_connections()
                count = IngestionRun.objects.filter(
                    self._eligible_work_filter()
                ).count()
            except (OperationalError, ProgrammingError):
                self.stderr.write(
                    self.style.WARNING(
                        f"[{timezone.now():%H:%M:%S}] {_STARTUP_DB_RETRY_MESSAGE} "
                        f"Retrying in {sleep_seconds}s..."
                    )
                )
                close_old_connections()
                time.sleep(sleep_seconds)
                continue

            if count == 0:
                self.stdout.write(
                    f"[{timezone.now():%H:%M:%S}] No eligible persistent work, "
                    f"sleeping {sleep_seconds}s..."
                )
                time.sleep(sleep_seconds)
                continue

            self.stdout.write(
                f"[{timezone.now():%H:%M:%S}] Found {count} eligible run(s), "
                "processing..."
            )
            self._process_all_queued(adapter)

    # ------------------------------------------------------------------
    # Single-pass mode
    # ------------------------------------------------------------------

    def _process_once(self, adapter: PersistentExtractionAdapter) -> None:
        """Process all queued runs once and exit.

        Honors ``--max-runs`` (bound the number of processed runs).
        The ``--run-id`` preflight already ran before adapter creation
        (see ``handle()`` and ``_preflight_selected_run()``).
        """
        run_id = getattr(self, "_run_id", None)
        if run_id is not None:
            # Preflight already validated this run. Process it directly.
            self.stdout.write(f"Processing selected run #{run_id}...")
            self._process_all_queued(adapter)
            self.stdout.write(self.style.SUCCESS("Done."))
            return

        count = IngestionRun.objects.filter(
            self._eligible_work_filter()
        ).count()
        if count == 0:
            self.stdout.write("No eligible runs to process.")
            return
        self.stdout.write(f"Processing {count} eligible run(s)...")
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
                # Validate intent before marking as running. During normal
                # polling the claim filter already excludes unsupported intents,
                # but when ``--run-id`` selects a specific run, we must check
                # here before mutating the run.
                if not self._validate_run_intent(run):
                    self._reject_unsupported_intent(run, run.intent)
                    break
                run.status = "running"
                run.save(update_fields=["status"])

            self._process_run(run, adapter)
            self._processed_count += 1

            # Conservative health gate between jobs: if the shared session
            # has degraded past a threshold, restart AND re-bootstrap it before
            # the next claim rather than carrying a sick or unauthenticated
            # browser into the next run. PSW-S19 R2/R3: the adapter is the
            # single lifecycle owner of restart + sanitized rebootstrap; a
            # connected-but-unauthenticated page after restart is NOT ready.
            if adapter.controller.restart_required():
                adapter.restart_and_rebootstrap()

    def _preflight_bounded_runs(self) -> bool:
        """All-or-nothing preflight for the bounded allow-list (PSW-S24-PRE R3).

        Validates every listed row for existence, queued state, retry due
        time, and supported/enabled intent (with model/JSON agreement) BEFORE
        any adapter/bootstrap is created. On any failure emits a sanitized
        warning and returns False; no run is mutated and no adapter is built.
        """
        now = timezone.now()
        for run_id in self._validation_run_ids:
            try:
                run = IngestionRun.objects.get(pk=run_id)
            except IngestionRun.DoesNotExist:
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_ROW_MISSING_MESSAGE)
                )
                return False
            if run.status != "queued":
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_ROW_NOT_QUEUED_MESSAGE)
                )
                return False
            if run.next_retry_at is not None and run.next_retry_at > now:
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_ROW_RETRY_NOT_DUE_MESSAGE)
                )
                return False
            if not self._validate_run_intent(run):
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_ROW_UNSUPPORTED_INTENT_MESSAGE)
                )
                return False
        return True

    @staticmethod
    def _claim_listed_run(run_id: int) -> IngestionRun | None:
        """Claim one operator-listed ID under row-lock (PSW-S24-PRE R4).

        Bounded validation mode only: claims the exact listed primary key when
        it is still queued, using the same
        ``select_for_update(skip_locked=True)`` discipline as the normal claim.
        It NEVER falls through to a generic or unlisted eligible row.
        """
        return (
            IngestionRun.objects
            .select_for_update(skip_locked=True)
            .filter(pk=run_id, status="queued")
            .first()
        )

    def _run_label(
        self, run: IngestionRun, *, followup: bool = False
    ) -> str:
        """Return a mode-safe run reference for command output.

        Bounded and continuous real modes never emit a primary key. Bounded
        selected runs use an ordinal; continuous runs use a fixed label; and
        both modes use a fixed follow-up phrase. Stub and explicitly selected
        single-smoke diagnostics preserve their historical operational ID.
        """
        mode = getattr(self, "_mode", _MODE_STUB)
        if mode in {_MODE_BOUNDED, _MODE_CONTINUOUS_REAL}:
            if followup:
                return "follow-up"
            if mode == _MODE_CONTINUOUS_REAL:
                return "Continuous run"
            ordinal = getattr(self, "_bounded_ordinal", 0)
            return f"Validation row {ordinal}" if ordinal else "Validation row"
        return f"run #{run.pk}" if followup else f"Run #{run.pk}"

    def _process_bounded_sequence(
        self, adapter: PersistentExtractionAdapter
    ) -> None:
        """Process the operator-ordered bounded allow-list (PSW-S24-PRE).

        Reuses the persistent adapter/session across consecutive selected jobs
        (one bootstrap). Claims only the next listed ID under row-lock, never
        falling through to a generic/unlisted queue row. Stops — leaving every
        later selected row untouched — when the cap is reached, the session is
        not ready, a selected row becomes unclaimable, a restart/rebootstrap
        fails, or a processed run does not finish as succeeded. Output uses
        only ordinal/count information and sanitized lifecycle messages (no
        run IDs or source data).
        """
        ids = list(self._validation_run_ids)
        total = len(ids)
        processed = 0
        index = 0
        while index < total:
            if self._max_runs_reached():
                break
            if not adapter.ensure_session_ready():
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_SESSION_NOT_READY_MESSAGE)
                )
                break
            selected_id = ids[index]
            self._bounded_ordinal = index + 1
            with transaction.atomic():
                run = self._claim_listed_run(selected_id)
                if run is None:
                    self.stderr.write(
                        self.style.WARNING(_BOUNDED_ROW_UNCLAIMABLE_MESSAGE)
                    )
                    break
                if not self._validate_run_intent(run):
                    self._reject_unsupported_intent(run, run.intent)
                    break
                run.status = "running"
                run.save(update_fields=["status"])

            self._process_run(run, adapter)
            self._processed_count += 1
            processed += 1

            run.refresh_from_db()
            if run.status != "succeeded":
                self.stderr.write(
                    self.style.WARNING(_BOUNDED_ROW_NOT_SUCCEEDED_MESSAGE)
                )
                break

            index += 1
            # Restart plus rebootstrap at a safe point before the next claim,
            # reusing the single adapter lifecycle boundary. A restart failure
            # leaves every later selected row queued and untouched.
            if index < total and adapter.controller.restart_required():
                if not adapter.restart_and_rebootstrap():
                    self.stderr.write(
                        self.style.WARNING(_BOUNDED_RESTART_FAILED_MESSAGE)
                    )
                    break

        self.stdout.write(
            self.style.SUCCESS(
                f"Bounded validation processed {processed} of {total} "
                f"selected row(s)."
            )
        )

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

    def _preflight_selected_run(self) -> bool:
        """Validate a selected (--run-id) run before adapter/browser creation.

        Checks: existence, queued status, retry eligibility, intent validity,
        and model/JSON intent consistency. On failure, emits a warning and
        returns False WITHOUT starting a browser, session, login, or adapter.

        Returns:
            True if the run passes all preflight checks and may proceed.

        Side effects when returning False:
            No adapter/session/browser created. No run state mutated.
        """
        run_id = getattr(self, "_run_id", None)
        if run_id is None:
            return True

        now = timezone.now()

        try:
            run = IngestionRun.objects.get(pk=run_id)
        except IngestionRun.DoesNotExist:
            self.stderr.write(
                self.style.WARNING(
                    f"Run #{run_id} does not exist; nothing processed."
                )
            )
            return False

        if run.status != "queued":
            self.stderr.write(
                self.style.WARNING(
                    f"Run #{run_id} is not queued (status={run.status}); "
                    "nothing processed."
                )
            )
            return False

        # Check retry eligibility
        if run.next_retry_at is not None and run.next_retry_at > now:
            self.stderr.write(
                self.style.WARNING(
                    f"Run #{run_id} retry not yet due "
                    f"(next_retry_at={run.next_retry_at}); "
                    "nothing processed."
                )
            )
            return False

        # Validate intent (model authoritative, JSON must agree)
        if not self._validate_run_intent(run):
            params = run.parameters_json or {}
            json_intent = params.get("intent", "")
            model_intent = run.intent or ""
            if model_intent and json_intent and model_intent != json_intent:
                msg = (
                    f"Run #{run_id}: conflicting intents "
                    f"(model={model_intent!r}, JSON={json_intent!r}); "
                    f"persistent worker rejects."
                )
            else:
                effective = model_intent or json_intent or "(empty)"
                msg = (
                    f"Run #{run_id}: unsupported intent {effective!r} — "
                    f"persistent worker rejects. "
                    f"Keeping run queued for current worker."
                )
            self.stderr.write(self.style.WARNING(msg))
            return False

        return True

    @staticmethod
    def _validate_run_intent(run: IngestionRun) -> bool:
        """Validate that this run has a supported explicit intent.

        During normal polling, unsupported intents are filtered by
        ``_claim_eligible_run``. This method is used when ``--run-id``
        selects a specific run that may have a non-enabled intent.

        The canonical effective-intent rule: ``IngestionRun.intent`` is
        authoritative for queue ownership. When ``parameters_json.intent``
        is non-empty it must match ``run.intent``, otherwise the row is
        rejected without source actions.

        Returns:
            True if the intent is supported and enabled, and the model
            field agrees with the JSON parameter when both are non-empty.

        Side effects when returning False:
            The run is NOT mutated — no status change, no attempt
            increment, no stage metrics, no clinical data, no source-
            session actions.
        """
        params = run.parameters_json or {}
        json_intent = params.get("intent", "")
        model_intent = run.intent or ""

        # The model field is authoritative for queue ownership.
        effective_intent = model_intent or json_intent

        # When both are non-empty they must agree.
        if model_intent and json_intent and model_intent != json_intent:
            return False

        return effective_intent in _ENABLED_INTENTS and effective_intent in _DISPATCH_MAP

    def _process_run(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process a single IngestionRun through the persistent adapter.

        Dispatches through an explicit intent mapping. ``full_admission_sync``
        is dispatched to the full-sync path via ``_DISPATCH_MAP``.
        Empty, unknown, or not-yet-enabled intents are validated and rejected
        WITHOUT changing run status, attempts, stages, clinical data, or
        source-session state.

        Heartbeat is refreshed via ``WorkerHeartbeat`` context manager.
        """
        params = run.parameters_json or {}
        intent = params.get("intent", "") or run.intent

        # Validate intent. During normal polling this is redundant (the claim
        # filter already excludes unsupported intents), but when ``--run-id``
        # selects a specific run, this guards against unsupported intents.
        if not self._validate_run_intent(run):
            self._reject_unsupported_intent(run, intent)
            return

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

        # Strict lookup: validation guarantees intent is in _DISPATCH_MAP.
        # No fallback — an unknown intent must never reach full-sync.
        dispatch_action = _DISPATCH_MAP[intent]
        with WorkerHeartbeat(run, interval_seconds=60):
            if dispatch_action == "admissions_only":
                self._process_admissions_only(run, adapter)
            elif dispatch_action == "full_sync":
                self._process_full_sync(run, adapter)
            elif dispatch_action == "demographics_only":
                self._process_demographics_only(run, adapter)

    def _reject_unsupported_intent(self, run: IngestionRun, intent: str) -> None:
        """Reject a run with unsupported intent without side effects.

        The run is NOT mutated — no status change, no attempt increment,
        no stage metrics, no clinical data, no source-session actions.
        A warning is logged to stderr so the operator can inspect the
        situation.

        This only applies to explicit ``--run-id`` selection. During
        normal polling, the claim filter prevents unsupported runs from
        being claimed.
        """
        # Intentionally blank: no DB mutations, no adapter calls.
        # The run remains queued for the current worker.
        self.stderr.write(
            f"  {self._run_label(run)}: unsupported intent {intent!r} — "
            f"persistent worker rejects. "
            f"Keeping run queued for current worker."
        )

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
            # RPAP-S2: a batch-bound empty capture is an invalid payload, not
            # a success. Raised inside this try so the existing data-failure
            # path (stage failed + tab cleanup + retry) applies before any
            # persistence or success bookkeeping.
            ensure_nonempty_batch_admissions(run.batch_id, result)
        except EmptyAdmissionsSnapshotError as exc:
            # Data-level failure: a job tab was opened, so cleanup is required
            # before claiming another run.
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during admissions capture "
                f"(empty admissions snapshot for batch-bound run, "
                f"reason={self._classify_failure_reason(exc)[0]})"
            )
            return
        except InvalidJsonError as exc:
            # Data failure — tab was opened, need cleanup
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during admissions capture "
                f"(invalid JSON from persistent session, "
                f"reason={self._classify_failure_reason(exc)[0]})"
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
                f"  {self._run_label(run)} failed during admissions capture "
                f"(snapshot data missing from persistent session, "
                f"reason={self._classify_failure_reason(exc)[0]})"
            )
            return
        except ExtractionError as exc:
            # PSW-S18-C1 (gap 3): recoverable ExtractionError. Do not infer
            # tab-open from the exception type; run safe cleanup (root-only
            # does not click; ambiguous/unsafe cleanup forces recovery).
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during admissions capture "
                f"(persistent session, reason={self._classify_failure_reason(exc)[0]})"
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

        # Success — adapter already handled tab cleanup and mark_job_processed.
        # Persist the snapshot through the canonical services shared with the
        # current worker (Patient/Admission rows, ward/bed backfill, and
        # database-derived seen/created/updated counters).
        try:
            patient, adm_metrics = persist_admissions_snapshot(
                patient_source_key=patient_record,
                admissions_snapshot=result,
            )
        except Exception as exc:
            self._record_stage(
                run, "admissions_capture", "failed", stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during admissions persistence "
                f"(reason={self._classify_failure_reason(exc)[0]})"
            )
            return

        self._record_stage(
            run, "admissions_capture", "succeeded", stage_start,
        )

        # Persist metrics (counters come from database outcomes, never list
        # length) and mark succeeded.
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

        # Mark attempt as succeeded
        self._mark_latest_attempt_succeeded(run)

        # Enqueue follow-ups under the same conditions as the current worker:
        # demographics_only (detached from the batch so it can close
        # independently) and the most-recent-admission full_sync (attached to
        # the same batch as this run).
        if patient is not None:
            demo_run = queue_demographics_only_run(
                patient_record=patient.patient_source_key,
                batch=None,
            )
            self.stdout.write(
                f"  Auto-enqueued demographics_only {self._run_label(demo_run, followup=True)} "
                f"for the captured patient."
            )
            full_sync_run = enqueue_most_recent_admission_full_sync(
                patient, batch=run.batch,
            )
            if full_sync_run is not None:
                self.stdout.write(
                    f"  Auto-enqueued full_sync {self._run_label(full_sync_run, followup=True)} "
                    f"for most recent admission"
                )

        # Close batch if all runs drained
        self._try_close_batch(run.batch)

        self.stdout.write(
            f"  {self._run_label(run)} admissions-only succeeded (persistent session) "
            f"(admissions_seen={adm_metrics['seen']}, "
            f"admissions_created={adm_metrics['created']}, "
            f"admissions_updated={adm_metrics['updated']})"
        )

    # ------------------------------------------------------------------
    # Demographics-only processing via persistent adapter (PSW-S16)
    # ------------------------------------------------------------------

    def _process_demographics_only(
        self,
        run: IngestionRun,
        adapter: PersistentExtractionAdapter,
    ) -> None:
        """Process a demographics-only run through the persistent session.

        Navigates the already-authenticated page to ``Dados do Paciente``,
        reads every demographic field from ``frame_pol`` into memory, and
        persists via the canonical :func:`upsert_patient_demographics`
        service shared with the current worker.

        Lifecycle (matches the current worker's stages/metrics while
        replacing the subprocess with the persistent page/context):
        1. Validate ``patient_record`` (R6: fail before source actions).
        2. Stage ``demographics_extraction``: adapter.get_demographics().
        3. Stage ``demographics_persistence``: upsert_patient_demographics().
        4. Record ``demographics_fields_extracted`` metric.
        5. Mark succeeded, attempt succeeded, and close the batch.

        Never invokes subprocess, ``TemporaryDirectory``, JSON files,
        ``sync_playwright``, a new browser/context, or a second login.
        """
        params = run.parameters_json or {}
        patient_record = params.get("patient_record", "")

        # R6: Missing patient record fails validation before source actions.
        if not patient_record:
            self._mark_run_failed(
                run, ValueError("Missing patient_record in parameters")
            )
            return

        # ------------------------------------------------------------------
        # Stage: demographics_extraction (persistent session)
        # ------------------------------------------------------------------
        ext_stage_start = timezone.now()
        try:
            demographics = adapter.get_demographics(
                patient_record=patient_record,
                timeout=_DEMOGRAPHICS_TIMEOUT,
            )
        except (InvalidJsonError, SnapshotContainerMissingError) as exc:
            # Data-level failure: a job tab was opened (stub path) or the
            # page rendered without the expected container, so cleanup runs
            # before the next claim. Tab close is cleanup only.
            self._record_stage(
                run, "demographics_extraction", "failed", ext_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during demographics capture "
                f"(persistent session, reason={self._classify_failure_reason(exc)[0]})"
            )
            return
        except ExtractionError as exc:
            # PSW-S18-C1 (gap 3): recoverable ExtractionError. Do not infer
            # tab-open from the exception type; run safe cleanup.
            self._record_stage(
                run, "demographics_extraction", "failed", ext_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during demographics capture "
                f"(persistent session, reason={self._classify_failure_reason(exc)[0]})"
            )
            return
        except Exception as exc:
            # Unexpected error — treat as session/infra failure (no cleanup).
            self._record_stage(
                run, "demographics_extraction", "failed", ext_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        # R3 command-level defense: even a mocked/regressed adapter cannot
        # turn an empty or mismatched payload into persistence success. This
        # mirrors the adapter identity boundary so the invariant holds end to
        # end. A failure here is a SOURCE extraction failure (not persistence)
        # and follows the existing retry/attempt/stage lifecycle.
        if not demographics_identity_matches(
            requested_patient_record=patient_record,
            demographics=demographics,
        ):
            identity_exc = ExtractionError(DEMOGRAPHICS_IDENTITY_MESSAGE)
            self._record_stage(
                run, "demographics_extraction", "failed", ext_stage_start,
                details_json=self._stage_error_details(identity_exc),
            )
            self._mark_run_failed(run, identity_exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during demographics capture "
                f"(identity mismatch, reason={self._classify_failure_reason(identity_exc)[0]})"
            )
            return

        self._record_stage(
            run, "demographics_extraction", "succeeded", ext_stage_start,
        )

        # ------------------------------------------------------------------
        # Stage: demographics_persistence (canonical upsert)
        # ------------------------------------------------------------------
        persist_stage_start = timezone.now()
        try:
            patient = upsert_patient_demographics(
                patient_source_key=patient_record,
                source_system="tasy",
                demographics=demographics,
                run=run,
            )
        except Exception as exc:
            self._record_stage(
                run, "demographics_persistence", "failed", persist_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            self.stderr.write(
                f"  {self._run_label(run)} failed during demographics persistence "
                f"(reason={self._classify_failure_reason(exc)[0]})"
            )
            return

        self._record_stage(
            run, "demographics_persistence", "succeeded", persist_stage_start,
        )

        # Field-count metric: identical field list as the current worker.
        fields_populated = sum(
            1
            for field_name in _DEMOGRAPHICS_FIELD_COUNT_FIELDS
            if getattr(patient, field_name, None)
        )

        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.failure_reason = ""
        run.timed_out = False
        run.parameters_json = {
            **params,
            "demographics_fields_extracted": fields_populated,
        }
        run.save()

        self._mark_latest_attempt_succeeded(run)
        self._try_close_batch(run.batch)

        self.stdout.write(
            f"  {self._run_label(run)} demographics-only succeeded "
            f"(persistent session) "
            f"(fields_populated={fields_populated})"
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
            # RPAP-S2: the mandatory admissions capture preceding full-sync
            # also fails closed for an empty batch-bound snapshot — before
            # gap planning, persistence, or any follow-up.
            ensure_nonempty_batch_admissions(run.batch_id, admissions_data)
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
            # PSW-S18-C1 (gap 3): recoverable ExtractionError in full-sync
            # admissions capture. Do not infer tab-open from the exception
            # type; run safe cleanup.
            self._record_stage(
                run, "admissions_capture", "failed", adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
            self._mark_run_failed(run, exc)
            return
        except Exception as exc:
            self._record_stage(
                run, "admissions_capture", "failed", adm_stage_start,
                details_json=self._stage_error_details(exc),
            )
            self._mark_run_failed(run, exc)
            return

        # Persist through the canonical shared service so admissions-only and
        # full-sync share one persistence path (Patient/Admission rows,
        # ward/bed backfill, database-derived counters). Source extraction
        # (the adapter call above) stays in this command.
        patient, adm_metrics = persist_admissions_snapshot(
            patient_source_key=patient_record,
            admissions_snapshot=admissions_data,
        )

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
                f"  {self._run_label(run)} full-sync succeeded (persistent session) — "
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
            # PSW-S18-C1 (gap 3): recoverable ExtractionError in full-sync
            # evolution extraction. Run safe cleanup before another claim.
            self._record_stage(
                run, "evolution_extraction", "failed", ev_stage_start,
                details_json=self._stage_error_details(exc),
            )
            adapter.cleanup_after_failure()
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
            f"  {self._run_label(run)} full-sync succeeded (persistent session) "
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
        """Classify an exception into normalized failure taxonomy.

        Delegates to the shared
        :func:`apps.ingestion.run_lifecycle.classify_failure_reason` so the
        persistent-session and current workers cannot drift apart
        (PSW-S17). The shared classifier recognizes every TYPED domain
        timeout (``ExtractionTimeoutError``, ``SubprocessTimeoutError``,
        persistent ``NavigationTimeoutError``/``EvolutionPdfTimeoutError``).
        It does NOT walk the cause/context chain — persistent source
        boundaries are responsible for raising typed outer exceptions
        (PSW-S17 R2/R3 correction).
        """
        from apps.ingestion.run_lifecycle import classify_failure_reason

        return classify_failure_reason(exc)

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
        """Build normalized stage-level error details payload.

        PSW-S17 R4 (second corrective closure): typed domain exceptions
        carry sanitized constant messages and keep their class name;
        unexpected exceptions use the stable category-specific text and
        label so no arbitrary ``str(exc)`` reaches stage details.
        """
        from apps.ingestion.run_lifecycle import (
            classify_failure_reason,
            safe_error_message,
            safe_error_type,
        )

        reason, _ = classify_failure_reason(exc)
        return {
            "error_type": safe_error_type(exc, reason),
            "error_message": safe_error_message(exc, reason),
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

        # PSW-S17 R4 (final closure): strict normalized error_message
        # derived solely from the failure category constant. No str(exc)
        # is persisted for any exception class.
        from apps.ingestion.run_lifecycle import safe_error_message

        safe_msg = safe_error_message(exc, failure_reason)

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
            attempt.error_message = safe_msg
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
            run.error_message = safe_msg
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
                f"  {self._run_label(run)} failed (attempt {run.attempt_count}/"
                f"{run.max_attempts}), requeued at {run.next_retry_at}"
            )
        else:
            run.status = "failed"
            run.error_message = safe_msg
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
            # PSW-S17 R5: record the terminal FinalRunFailure row through
            # the shared helper so the current and persistent workers create
            # it under the same conditions and with the same fields (and
            # remain idempotent under retry recovery).
            from apps.ingestion.run_lifecycle import record_final_run_failure

            record_final_run_failure(run)
            self._try_close_batch(run.batch)
            self.stderr.write(
                f"  {self._run_label(run)} failed permanently "
                f"(attempt {run.attempt_count}/{run.max_attempts}, "
                f"reason={failure_reason})"
            )
