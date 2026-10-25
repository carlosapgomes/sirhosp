"""Profile-gated one-shot exit-reconciliation runtime (RPSA-S11).

Scheduled and operator entry point executed inside the
``compose.hospital.yml`` ``historical_recovery`` service (``recovery``
profile). Thin orchestration over the existing recovery pipeline
(``recover_historical_data``), never forking it:

- ``--mode hourly``: current America/Bahia date, ``discharges`` only.
- ``--mode d1``: previous America/Bahia date with all four extractors in
  canonical order (``discharges, admissions, deaths, official_census``),
  followed by the post-extraction date-only death step (ODR-S1): every
  ``DeathRecord`` of the recovered date is classified read-only first
  and only a closable match reaches the online death path,
  fail-closed per record, with an aggregate summary and a success
  marker.
- ``--mode catchup``: explicit operator multi-date catch-up. Plans
  missing/failed discharge-extraction dates from the durable RPSA-S7/S10
  coverage metadata (identical keying to pipeline health), capped at
  seven dates. A larger gap stops before extraction and reports only the
  aggregate gap count plus first/last bounds. Nothing here schedules
  catch-up: automatic planning stays D-1 only.

All three modes launch source automation, so every mode follows the same
ordering before any Playwright/subprocess launch:

1. a mode-specific PostgreSQL advisory lock (session-scoped) is tried
   first — on conflict the run exits 0 with an aggregate skip message;
2. the read-only orchestration eligibility semantics are reused — an
   active queued/running ``IngestionRun`` or an open census batch exits
   with the fixed code ``75`` (``EX_TEMPFAIL``) and an aggregate-safe
   busy reason.

Extractor failures keep their normal nonzero exit semantics and are
never mapped to 75.

Coordination keys are deliberately distinct from the census orchestrator
key and the RPSA-S5 stale-sweep key. Session-scoped locks mean process
exit always releases them; normal completion also releases them
explicitly.

Output is aggregate-safe: counters, statuses, dates and safe failure
reasons only.
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.census.orchestration import (
    D1_DEATHS_SUCCESS_MARKER,
    compute_orchestrator_state,
)
from apps.deaths.models import DeathRecord
from apps.deaths.services import build_death_exit_evidence, reconcile_death_record
from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    _date_to_str,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric
from apps.ingestion.pipeline_health import (
    DISCHARGE_PERSISTENCE_STAGE,
    _extraction_coverage_stats,
    _extraction_date,
    _stage_confirms_complete,
)
from apps.patients.models import (
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_RECONCILED,
)
from apps.patients.reconciliation import decide_discharge_match, runtime_provenance_payload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

EX_TEMPFAIL = 75
"""Fixed temporary-busy exit code reserved for queue/batch contention."""

MAX_CATCHUP_DATES = 7
"""Maximum catch-up dates planned from durable coverage metadata."""

BAHIA_TZ = ZoneInfo("America/Bahia")
"""Institutional local timezone for calendar-day decisions."""

HOURLY_LOCK_KEY = 31082026
"""Advisory-lock key for the hourly current-day discharge mode.

Distinct from the census orchestrator ``ADVISORY_LOCK_KEY``, the RPSA-S5
stale-sweep key and the recovery key below.
"""

RECOVERY_LOCK_KEY = 31082027
"""Advisory-lock key for historical recovery (D-1 and explicit catch-up).

Distinct from the census orchestrator ``ADVISORY_LOCK_KEY``, the RPSA-S5
stale-sweep key and the hourly key above.
"""

MODE_HOURLY = "hourly"
MODE_D1 = "d1"
MODE_CATCHUP = "catchup"
_SUPPORTED_MODES = (MODE_HOURLY, MODE_D1, MODE_CATCHUP)

_CANONICAL_EXTRACTORS = list(DEFAULT_EXTRACTOR_ORDER)
_DISCHARGE_INTENT = "discharge_extraction"


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------


def _today_bahia() -> date:
    """Current calendar date in America/Bahia (never host timezone)."""
    return timezone.now().astimezone(BAHIA_TZ).date()


def _previous_day(today: date) -> date:
    return today - timedelta(days=1)


# ---------------------------------------------------------------------------
# Advisory locks (session-scoped)
# ---------------------------------------------------------------------------


def _try_advisory_lock(key: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        (acquired,) = cursor.fetchone()
    return bool(acquired)


def _release_advisory_lock(key: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


# ---------------------------------------------------------------------------
# Eligibility (read-only reuse of the orchestration semantics)
# ---------------------------------------------------------------------------


def _contention_reason() -> str:
    """Aggregate-safe busy reason when queue/batch contention exists."""
    decision = compute_orchestrator_state()
    parts: list[str] = []
    if decision.active_queued:
        parts.append(f"{decision.active_queued} queued")
    if decision.active_running:
        parts.append(f"{decision.active_running} running")
    if decision.open_batch_exists:
        parts.append("open census batch")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Catch-up planning from durable coverage metadata (RPSA-S7/S10 keying)
# ---------------------------------------------------------------------------


def _materialize_gap_dates() -> list[date]:
    """Sorted dates whose durable discharge coverage is missing/failed.

    Uses exactly the RPSA-S10 keying and classification helpers: only
    ``discharge_extraction`` runs keyed by their durable parameters count;
    a date is a gap when its best run level is below complete (no
    successful run, or a success without the confirming persistence
    stage). Never reads in-memory extraction results.
    """
    persist_details: dict[int, list[Any]] = defaultdict(list)
    stage_rows = IngestionRunStageMetric.objects.filter(
        stage_name=DISCHARGE_PERSISTENCE_STAGE,
        run__intent=_DISCHARGE_INTENT,
    ).values_list("run_id", "details_json")
    for run_id, details_json in stage_rows:
        persist_details[run_id].append(details_json)

    best: dict[date, int] = {}
    runs = IngestionRun.objects.filter(intent=_DISCHARGE_INTENT).values_list(
        "pk", "status", "parameters_json"
    )
    for run_id, status, parameters_json in runs:
        extraction_date = _extraction_date(parameters_json)
        if extraction_date is None:
            continue
        level = 0
        if status == "succeeded":
            level = 1
            if any(
                _stage_confirms_complete(details)
                for details in persist_details.get(run_id, ())
            ):
                level = 2
        if level > best.get(extraction_date, -1):
            best[extraction_date] = level

    return sorted(day for day, level in best.items() if level < 2)


# ---------------------------------------------------------------------------
# D-1 post-extraction death step (ODR-S1)
# ---------------------------------------------------------------------------


def reconcile_d1_deaths(*, day: date) -> dict[str, int]:
    """Reconcile every ``DeathRecord`` of one recovered local date.

    Each record is first classified with the read-only
    ``decide_discharge_match`` decision over the same evidence the
    online path would use (date-only matching since rc.41). Only a
    ``reconciled`` decision reaches the online ``reconcile_death_record``
    writer, which closes the episode; any other outcome — ambiguous,
    patient/admission not found, already reconciled, pending or
    unparseable — performs no write at all (no evidence save, no audit
    event, no mirror-sync enqueue) and is only counted. Events created
    here carry the lightweight runtime provenance stamp
    (``{"mode": "d1"}``) recorded at creation time.

    Scope is strictly the given date — no history scan. An unexpected
    exception in one record is logged with the record primary key only
    and counted as failed; the remaining records still run. Only a
    total step failure (e.g. the date query itself) propagates, so the
    caller can contain it without aborting the recovery.

    Returns aggregate counts keyed by ``reconciled``,
    ``already_reconciled``, ``pending`` and ``failed``.
    """
    summary = {
        "reconciled": 0,
        "already_reconciled": 0,
        "pending": 0,
        "failed": 0,
    }
    records = list(DeathRecord.objects.filter(date=day).order_by("pk"))
    with runtime_provenance_payload({"mode": MODE_D1}):
        for record in records:
            try:
                evidence = build_death_exit_evidence(record=record)
                if evidence is None:
                    # Unparseable data_obito: no usable date exists at
                    # all. Count only — never touch the writer path.
                    summary["pending"] += 1
                    continue
                decision = decide_discharge_match(evidence=evidence)
                if decision.status == RECONCILIATION_STATUS_ALREADY_RECONCILED:
                    summary["already_reconciled"] += 1
                    continue
                if decision.status != RECONCILIATION_STATUS_RECONCILED:
                    # Ambiguous, patient/admission not found, or any
                    # other non-closable outcome: count only, without
                    # the evidence save, audit event or mirror-sync
                    # enqueue the online path would perform.
                    summary["pending"] += 1
                    continue
                status = reconcile_death_record(record=record)
            except Exception as exc:
                logger.error(
                    "d1 death step record failed: record_id=%s error=%s",
                    record.pk,
                    type(exc).__name__,
                )
                summary["failed"] += 1
                continue
            if status == RECONCILIATION_STATUS_RECONCILED:
                summary["reconciled"] += 1
            elif status == RECONCILIATION_STATUS_ALREADY_RECONCILED:
                summary["already_reconciled"] += 1
            else:
                summary["pending"] += 1
    return summary


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "One-shot exit-reconciliation runtime: hourly current-day "
        "discharge, previous-day recovery (discharges, admissions, deaths, "
        "official_census) or explicit seven-date-capped catch-up. "
        "Coordinates via advisory locks and exits 75 when the queue or a "
        "census batch is busy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            default=None,
            help="hourly | d1 | catchup (mutually exclusive).",
        )

    def handle(self, *args, **options):
        mode = options.get("mode")
        if mode not in _SUPPORTED_MODES:
            raise CommandError(
                "--mode is required and must be one of: "
                f"{', '.join(_SUPPORTED_MODES)}"
            )

        lock_key = HOURLY_LOCK_KEY if mode == MODE_HOURLY else RECOVERY_LOCK_KEY

        if not _try_advisory_lock(lock_key):
            self.stdout.write(
                "exit_reconciliation_runtime: "
                f"mode={mode} result=skip reason=equivalent_runtime_active"
            )
            return

        try:
            reason = _contention_reason()
            if reason:
                self.stdout.write(
                    "exit_reconciliation_runtime: "
                    f"mode={mode} result=busy reason={reason} exit_code=75"
                )
                sys.exit(EX_TEMPFAIL)

            if mode == MODE_HOURLY:
                self._dispatch_single_day(
                    mode, _today_bahia(), ["discharges"]
                )
            elif mode == MODE_D1:
                day = _previous_day(_today_bahia())
                self._dispatch_single_day(
                    mode, day, _CANONICAL_EXTRACTORS
                )
                self._reconcile_d1_deaths(day)
            else:
                self._handle_catchup()
        finally:
            _release_advisory_lock(lock_key)

    # ------------------------------------------------------------------
    # Single-date dispatch through the existing recovery pipeline
    # ------------------------------------------------------------------

    def _dispatch_single_day(
        self, mode: str, day: date, extractors: list[str]
    ) -> None:
        label = _date_to_str(day)
        self.stdout.write(
            "exit_reconciliation_runtime: "
            f"mode={mode} date={label} extractors={','.join(extractors)}"
        )
        self._run_recovery_command(day, extractors)

    def _run_recovery_command(self, day: date, extractors: list[str]) -> None:
        """Invoke the existing recovery pipeline for one date.

        The pipeline command owns per-step retry rounds, reconciliation
        counters and the normal nonzero exit on extractor failure.
        """
        call_command(
            "recover_historical_data",
            date=_date_to_str(day),
            extractors=list(extractors),
            stdout=self.stdout,
            stderr=self.stderr,
        )

    # ------------------------------------------------------------------
    # D-1 post-extraction death step (ODR-S1; d1 mode only)
    # ------------------------------------------------------------------

    def _reconcile_d1_deaths(self, day: date) -> None:
        """Run the date-only death step without ever aborting the recovery.

        A total step failure is reported as one aggregate failed line and
        never raises; the success marker is emitted only when the step
        completes, with aggregate counts.
        """
        label = _date_to_str(day)
        try:
            summary = reconcile_d1_deaths(day=day)
        except Exception as exc:
            logger.error(
                "d1 death step failed: date=%s error=%s",
                label,
                type(exc).__name__,
            )
            self.stdout.write(
                "exit_reconciliation_runtime: "
                f"mode=d1-deaths result=failed reason={type(exc).__name__} "
                f"date={label}"
            )
            return
        self.stdout.write(
            "exit_reconciliation_runtime: "
            f"{D1_DEATHS_SUCCESS_MARKER} date={label} "
            f"reconciled={summary['reconciled']} "
            f"already_reconciled={summary['already_reconciled']} "
            f"pending={summary['pending']} "
            f"failed={summary['failed']}"
        )

    # ------------------------------------------------------------------
    # Explicit catch-up (operator only; never scheduled)
    # ------------------------------------------------------------------

    def _handle_catchup(self) -> None:
        coverage = _extraction_coverage_stats()

        if coverage.gap_count == 0:
            self.stdout.write(
                "exit_reconciliation_runtime: "
                "mode=catchup result=noop reason=no_missing_dates"
            )
            return

        if coverage.gap_count > MAX_CATCHUP_DATES:
            # Stop before any extraction: aggregate gap count and bounds
            # only. Operator approval is required beyond seven dates.
            self.stdout.write(
                "exit_reconciliation_runtime: mode=catchup "
                "result=skipped reason=gap_too_large "
                f"gap_count={coverage.gap_count} "
                f"gap_first_date={_date_text(coverage.gap_first_date)} "
                f"gap_last_date={_date_text(coverage.gap_last_date)} "
                f"max_dates={MAX_CATCHUP_DATES}"
            )
            return

        gap_dates = _materialize_gap_dates()
        if len(gap_dates) != coverage.gap_count:
            raise CommandError(
                "durable coverage mismatch between aggregate and date "
                "materialization; catch-up aborted before extraction"
            )

        succeeded = 0
        failed = 0
        for day in gap_dates:
            label = _date_to_str(day)
            self.stdout.write(
                "exit_reconciliation_runtime: mode=catchup "
                f"date={label} extractors={','.join(_CANONICAL_EXTRACTORS)}"
            )
            try:
                self._run_recovery_command(day, _CANONICAL_EXTRACTORS)
            except SystemExit as exc:
                # The recovery pipeline exits nonzero when an extractor
                # remains failed; record it and keep processing the
                # remaining planned dates.
                if exc.code:
                    failed += 1
                else:
                    succeeded += 1
            else:
                succeeded += 1

        self.stdout.write(
            "exit_reconciliation_runtime: mode=catchup completed "
            f"planned={len(gap_dates)} succeeded={succeeded} failed={failed}"
        )
        if failed:
            sys.exit(1)


def _date_text(value: date | None) -> str:
    return "none" if value is None else value.isoformat()
