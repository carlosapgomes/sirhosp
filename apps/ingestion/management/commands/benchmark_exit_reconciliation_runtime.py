"""Bounded benchmark for the exit-reconciliation runtime (RPSA-S11).

Two SEPARATE modes, never combined in one invocation:

- ``--mode hourly``: ``--repetitions`` (default 3) bounded repetitions of
  the hourly single-date discharge shape (current America/Bahia date,
  ``discharges`` only).
- ``--mode catchup``: the four-extractor catch-up shape
  (``discharges, admissions, deaths, official_census``) across at most
  seven synthetic calendar dates (``--dates``, default 7).

Every source call is mocked by construction: each step executes against
a synthetic extractor registry that reproduces only the durable
``IngestionRun`` lifecycle of the real pipeline (no subprocess, no
browser, no network). Each repetition runs inside a PostgreSQL
transaction that is always rolled back, so the benchmark writes nothing
durable and enables nothing automatically.

Measured aggregates, evaluated against named thresholds whose safe
defaults are documented below (placeholder gates for a fully-mocked
workload; production calibration belongs to the deployment runbook):

- wall latency: worst per-repetition duration (``max_latency_seconds``);
- error rate: failed steps over total steps (``max_error_rate``);
- database duration: total measured SQL execution time across the run
  (``max_db_seconds``);
- queue impact: worst count of synthetic runs left queued/running at a
  repetition end (``max_queue_depth``; the lifecycle drains to zero).

Results are aggregate-only. A failed threshold exits nonzero with code 1
(never 75); PASS exits 0.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.ingestion.historical_extraction import (
    ExtractionResult,
    create_stage_metric,
    mark_run_succeeded,
)
from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryPlan,
    execute_recovery_plan,
)
from apps.ingestion.models import IngestionRun

# ---------------------------------------------------------------------------
# Modes and bounds
# ---------------------------------------------------------------------------

MODE_HOURLY = "hourly"
MODE_CATCHUP = "catchup"
_SUPPORTED_MODES = (MODE_HOURLY, MODE_CATCHUP)

DEFAULT_HOURLY_REPETITIONS = 3
DEFAULT_CATCHUP_REPETITIONS = 1
DEFAULT_CATCHUP_DATES = 7
MAX_CATCHUP_DATES = 7

BAHIA_TZ = ZoneInfo("America/Bahia")
"""Institutional local timezone for synthetic calendar dates."""

_HOURLY_EXTRACTORS = ["discharges"]
_CANONICAL_EXTRACTORS = list(DEFAULT_EXTRACTOR_ORDER)

# Synthetic run intent per extractor (only inside rolled-back rows).
_EXTRACTOR_INTENT = {
    "discharges": "discharge_extraction",
    "admissions": "admission_extraction",
    "deaths": "death_extraction",
    "official_census": "census_extraction",
}


# ---------------------------------------------------------------------------
# Named thresholds with documented safe defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkLimits:
    """Named benchmark thresholds with documented safe defaults.

    The defaults are conservative placeholder gates that a fully-mocked
    workload always passes; exact production limits must be calibrated
    independently and recorded in the deployment runbook before any
    automation is enabled.
    """

    max_latency_seconds: float
    max_error_rate: float
    max_db_seconds: float
    max_queue_depth: int


HOURLY_LIMITS = BenchmarkLimits(
    max_latency_seconds=30.0,
    max_error_rate=0.10,
    max_db_seconds=15.0,
    max_queue_depth=0,
)
"""Hourly shape: single date, discharges only."""

CATCHUP_LIMITS = BenchmarkLimits(
    max_latency_seconds=300.0,
    max_error_rate=0.10,
    max_db_seconds=180.0,
    max_queue_depth=0,
)
"""Catch-up shape: four extractors across at most seven dates."""


# ---------------------------------------------------------------------------
# Synthetic workload
# ---------------------------------------------------------------------------


def _today_bahia() -> date:
    return timezone.now().astimezone(BAHIA_TZ).date()


def _recent_dates(count: int) -> list[date]:
    """Deterministic synthetic calendar: the ``count`` most recent local
    dates ending today (America/Bahia)."""
    today = _today_bahia()
    return [today - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


@dataclass
class _SyntheticTape:
    """Per-repetition outcome bookkeeping for the synthetic registry."""

    fail_steps: int = 0
    total_steps: int = 0
    failed_steps: int = 0
    active_count: int = 0
    peak_active: int = 0
    residual_active: int = 0
    _failures_left: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._failures_left = self.fail_steps

    def wants_failure(self) -> bool:
        if self._failures_left > 0:
            self._failures_left -= 1
            return True
        return False

    def open_run(self) -> None:
        self.active_count += 1
        self.peak_active = max(self.peak_active, self.active_count)

    def close_run(self) -> None:
        self.active_count -= 1

    def snapshot(self) -> None:
        self.residual_active = max(self.residual_active, self.active_count)


def _make_synthetic_service(extractor: str, tape: _SyntheticTape):
    """Synthetic extractor: no source call, real rolled-back lifecycle."""
    intent = _EXTRACTOR_INTENT[extractor]

    def service(date_label: str, headless: bool = True) -> ExtractionResult:
        del headless
        tape.total_steps += 1
        day = datetime.strptime(date_label, "%d/%m/%Y").date()

        if tape.wants_failure():
            tape.failed_steps += 1
            return ExtractionResult(
                extraction_type=f"{extractor}_extraction",
                target_start=day,
                target_end=day,
                success=False,
                failure_reason="simulated_source_unavailable",
                error_message="Simulated source failure.",
                metrics={},
            )

        started = timezone.now()
        run = IngestionRun.objects.create(
            status="running",
            intent=intent,
            queued_at=started,
            processing_started_at=started,
            parameters_json={"date": date_label},
        )
        tape.open_run()
        try:
            create_stage_metric(
                run=run,
                stage_name=f"{extractor}_extraction",
                status="succeeded",
                started_at=started,
                details_json={"total_records": 0, "zero_confirmed": True},
            )
            mark_run_succeeded(run)
        finally:
            tape.close_run()

        return ExtractionResult(
            extraction_type=f"{extractor}_extraction",
            target_start=day,
            target_end=day,
            success=True,
            metrics={
                "total_records": 0,
                "zero_confirmed": True,
                "attempt_count": 2,
            },
            ingestion_run_id=run.pk,
        )

    return service


# ---------------------------------------------------------------------------
# Measurement engine
# ---------------------------------------------------------------------------


def _measure_repetition(
    dates: list[date],
    extractors: list[str],
    fail_steps: int,
) -> dict[str, float | int]:
    """Run one bounded synthetic repetition inside a rolled-back
    transaction and return its aggregate measurements."""
    tape = _SyntheticTape(fail_steps=fail_steps)
    registry = {
        extractor: _make_synthetic_service(extractor, tape)
        for extractor in extractors
    }
    plan = RecoveryPlan(
        dates=list(dates),
        extractors=list(extractors),
        dry_run=False,
        fail_fast=False,
        max_retries=0,
    )

    db_chunks: list[float] = []

    def _db_wrapper(execute, sql, params, many, context):
        start = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            db_chunks.append(perf_counter() - start)

    started = perf_counter()
    with connection.execute_wrapper(_db_wrapper):
        with transaction.atomic():
            result = execute_recovery_plan(
                plan, service_registry=registry, headless=True
            )
            tape.snapshot()
            transaction.set_rollback(True)

    return {
        "wall_seconds": perf_counter() - started,
        "db_seconds": sum(db_chunks),
        "total_steps": result.total_steps,
        "failed_steps": result.failed_steps,
        "residual_active": tape.residual_active,
        "peak_active": tape.peak_active,
    }


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Bounded benchmark for the exit-reconciliation runtime. Two "
        "separate modes: hourly (single-date discharges, default 3 "
        "repetitions) and catchup (four extractors across at most seven "
        "synthetic dates). All source calls are mocked; every repetition "
        "is rolled back; results are aggregate-only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            default=None,
            help="hourly | catchup (separate modes, never combined).",
        )
        parser.add_argument(
            "--repetitions",
            type=int,
            default=None,
            help="Bounded repetitions (hourly default 3; catchup default 1).",
        )
        parser.add_argument(
            "--dates",
            type=int,
            default=None,
            help="Catch-up synthetic dates (1..7, default 7). "
            "Rejected in hourly mode.",
        )
        parser.add_argument(
            "--fail-steps",
            type=int,
            default=None,
            help="Synthetic extractor failures per repetition (default 0).",
        )
        parser.add_argument(
            "--max-latency-seconds",
            type=float,
            default=None,
            dest="max_latency_seconds",
            help="Wall-latency threshold override.",
        )
        parser.add_argument(
            "--max-error-rate",
            type=float,
            default=None,
            dest="max_error_rate",
            help="Error-rate threshold override (0..1).",
        )
        parser.add_argument(
            "--max-db-seconds",
            type=float,
            default=None,
            dest="max_db_seconds",
            help="Database-duration threshold override.",
        )
        parser.add_argument(
            "--max-queue-depth",
            type=int,
            default=None,
            dest="max_queue_depth",
            help="Queue-impact threshold override.",
        )

    def handle(self, *args, **options):
        mode = options.get("mode")
        if mode not in _SUPPORTED_MODES:
            raise CommandError(
                "--mode is required and must be one of: "
                f"{', '.join(_SUPPORTED_MODES)}"
            )

        repetitions = self._resolve_int(
            options.get("repetitions"),
            default=(
                DEFAULT_HOURLY_REPETITIONS
                if mode == MODE_HOURLY
                else DEFAULT_CATCHUP_REPETITIONS
            ),
            option_name="repetitions",
            minimum=1,
        )

        if mode == MODE_HOURLY:
            dates_option = options.get("dates")
            if dates_option is not None:
                raise CommandError("--dates is only valid with --mode catchup")
            fail_steps = self._resolve_int(
                options.get("fail_steps"), default=0,
                option_name="fail_steps", minimum=0,
            )
            dates = [_today_bahia()]
            extractors = list(_HOURLY_EXTRACTORS)
            defaults = HOURLY_LIMITS
        else:
            dates_option = options.get("dates")
            dates_count = (
                DEFAULT_CATCHUP_DATES
                if dates_option is None
                else dates_option
            )
            if not 1 <= dates_count <= MAX_CATCHUP_DATES:
                raise CommandError(
                    "--dates must be between 1 and seven (inclusive)"
                )
            fail_steps = self._resolve_int(
                options.get("fail_steps"), default=0,
                option_name="fail_steps", minimum=0,
            )
            dates = _recent_dates(dates_count)
            extractors = list(_CANONICAL_EXTRACTORS)
            defaults = CATCHUP_LIMITS

        limits = BenchmarkLimits(
            max_latency_seconds=options.get("max_latency_seconds")
            if options.get("max_latency_seconds") is not None
            else defaults.max_latency_seconds,
            max_error_rate=options.get("max_error_rate")
            if options.get("max_error_rate") is not None
            else defaults.max_error_rate,
            max_db_seconds=options.get("max_db_seconds")
            if options.get("max_db_seconds") is not None
            else defaults.max_db_seconds,
            max_queue_depth=options.get("max_queue_depth")
            if options.get("max_queue_depth") is not None
            else defaults.max_queue_depth,
        )
        self._validate_limits(limits)

        planned_steps = repetitions * len(dates) * len(extractors)
        self.stdout.write(
            "benchmark_exit_reconciliation_runtime: "
            f"mode={mode} repetitions={repetitions} dates={len(dates)} "
            f"extractors={','.join(extractors)} steps={planned_steps}"
        )

        walls: list[float] = []
        db_total = 0.0
        total_steps = 0
        failed_steps = 0
        worst_residual = 0
        peak_active = 0
        for index in range(repetitions):
            measurement = _measure_repetition(
                dates, extractors, fail_steps=fail_steps
            )
            walls.append(float(measurement["wall_seconds"]))
            db_total += float(measurement["db_seconds"])
            total_steps += int(measurement["total_steps"])
            failed_steps += int(measurement["failed_steps"])
            worst_residual = max(
                worst_residual, int(measurement["residual_active"])
            )
            peak_active = max(peak_active, int(measurement["peak_active"]))
            self.stdout.write(
                f"benchmark_repetition: index={index + 1} "
                f"wall_seconds={float(measurement['wall_seconds']):.3f} "
                f"db_seconds={float(measurement['db_seconds']):.3f} "
                f"steps={measurement['total_steps']} "
                f"failed={measurement['failed_steps']} "
                f"peak_active={measurement['peak_active']}"
            )

        observed = {
            "max_latency_seconds": max(walls),
            "max_error_rate": (
                failed_steps / total_steps if total_steps else 0.0
            ),
            "max_db_seconds": db_total,
            "max_queue_depth": worst_residual,
        }
        limits_map = {
            "max_latency_seconds": limits.max_latency_seconds,
            "max_error_rate": limits.max_error_rate,
            "max_db_seconds": limits.max_db_seconds,
            "max_queue_depth": float(limits.max_queue_depth),
        }

        failed_any = False
        for name in ("max_latency_seconds", "max_error_rate",
                     "max_db_seconds", "max_queue_depth"):
            value = float(observed[name])
            limit = float(limits_map[name])
            status = "pass" if value <= limit else "fail"
            failed_any = failed_any or status == "fail"
            self.stdout.write(
                f"benchmark_metric: name={name} observed={value:.3f} "
                f"limit={limit:.3f} status={status}"
            )

        self.stdout.write(
            "benchmark_exit_reconciliation_runtime: "
            f"mode={mode} result={'pass' if not failed_any else 'fail'}"
        )
        self.stdout.write(
            "benchmark_aggregate: "
            f"total_steps={total_steps} failed_steps={failed_steps} "
            f"peak_active={peak_active} "
            f"total_wall_seconds={sum(walls):.3f} "
            f"total_db_seconds={db_total:.3f}"
        )
        if failed_any:
            sys.exit(1)

    # ------------------------------------------------------------------
    # Argument resolution and validation
    # ------------------------------------------------------------------

    def _resolve_int(
        self,
        raw_value: int | None,
        *,
        default: int,
        option_name: str,
        minimum: int,
    ) -> int:
        value = default if raw_value is None else raw_value
        if value < minimum:
            raise CommandError(
                f"--{option_name.replace('_', '-')} must be at least {minimum}"
            )
        return value

    def _validate_limits(self, limits: BenchmarkLimits) -> None:
        if limits.max_latency_seconds < 0:
            raise CommandError("--max-latency-seconds must be non-negative")
        if not 0.0 <= limits.max_error_rate <= 1.0:
            raise CommandError("--max-error-rate must be between 0 and 1")
        if limits.max_db_seconds < 0:
            raise CommandError("--max-db-seconds must be non-negative")
        if limits.max_queue_depth < 0:
            raise CommandError("--max-queue-depth must be non-negative")
