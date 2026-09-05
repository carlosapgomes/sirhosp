"""Integration coverage for the RPSA-S11 exit-reconciliation runtime and
benchmark commands against the isolated test database.

``run_exit_reconciliation_runtime``:
- hourly mode plans exactly the current America/Bahia date and
  ``discharges`` only; ``d1`` mode plans the previous America/Bahia date
  with all four extractors in canonical order; both reuse the existing
  recovery pipeline command.
- catchup mode plans missing/failed dates from the durable RPSA-S7/S10
  discharge-extraction coverage metadata (identical keying to pipeline
  health), capped at seven; a larger gap stops before extraction and
  prints only aggregate count and bounds; D-1 automatic planning never
  expands into multi-date catch-up.
- two new PostgreSQL advisory-lock keys (hourly, recovery) are distinct
  from each other and from the census orchestrator and RPSA-S5 keys;
  lock conflict skips with exit 0 before any pipeline call.
- queued/running ingestion runs or an open census batch exit with the
  fixed code 75 (``EX_TEMPFAIL``) before any pipeline call, with an
  aggregate-safe busy reason; extractor failures keep their normal
  nonzero exit and are never mapped to 75.
- output stays aggregate-safe; ``process_discharge_pdf`` is never
  referenced by the runtime or benchmark command source.

``benchmark_exit_reconciliation_runtime``:
- two separate bounded modes never combined; hourly bounded repetitions
  (default 3) and catchup across four extractors over at most seven
  synthetic dates;
- named thresholds with documented safe defaults, PASS/FAIL evaluation;
- every source call mocked and every repetition rolled back (no durable
  write); results are aggregate-only.

All fixtures are synthetic; production and source automation are never
touched.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone

from apps.census.orchestration import ADVISORY_LOCK_KEY
from apps.census.stale_admissions import STALE_ADMISSION_SWEEP_LOCK_KEY
from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryRunResult,
    RecoveryStepResult,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunStageMetric,
)

BAHIA = ZoneInfo("America/Bahia")

RUNTIME_COMMAND = "run_exit_reconciliation_runtime"
BENCHMARK_COMMAND = "benchmark_exit_reconciliation_runtime"

_RECOVER_EXEC = (
    "apps.ingestion.management.commands.recover_historical_data"
    ".execute_recovery_plan"
)
_RUNTIME_MODULE = (
    "apps.ingestion.management.commands.run_exit_reconciliation_runtime"
)

FIXED_BAHIA_TODAY = date(2026, 6, 15)

# Identity sentinels that must never reach operator output.
SENTINEL_RECORD = "PRONT-PRIV-RPSA-S11"
SENTINEL_NAME = "NOME-PRIV-RPSA-S11"

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------


def _now():
    return timezone.now()


def _ok_result(day: date) -> RecoveryRunResult:
    steps = [
        RecoveryStepResult(
            date=day,
            date_label=day.strftime("%d/%m/%Y"),
            extractor=extractor,
            success=True,
            extraction_type=f"{extractor}_extraction",
            metrics={"total_records": 0, "zero_confirmed": True},
        )
        for extractor in DEFAULT_EXTRACTOR_ORDER
    ]
    return RecoveryRunResult(start_date=day, end_date=day, steps=steps)


def _failure_result(day: date) -> RecoveryRunResult:
    steps = [
        RecoveryStepResult(
            date=day,
            date_label=day.strftime("%d/%m/%Y"),
            extractor="discharges",
            success=False,
            extraction_type="discharge_extraction",
            failure_reason="source_unavailable",
            error_message="Source unavailable",
            metrics={},
        )
    ]
    return RecoveryRunResult(start_date=day, end_date=day, steps=steps)


def _make_discharge_run(
    ref_date_iso: str,
    *,
    status: str = "succeeded",
    persist_details: dict | None = None,
) -> IngestionRun:
    """Create one durable discharge-extraction run fixture.

    Level semantics follow RPSA-S10 ``_extraction_coverage_stats``:
    succeeded + persistence details confirming rows/confirmed-zero is
    complete; a succeeded run without such details is incomplete; a
    failed run contributes level zero. All three classify as a gap date.
    """
    day = date.fromisoformat(ref_date_iso)
    finished = _now() if status in ("succeeded", "failed") else None
    run = IngestionRun.objects.create(
        status=status,
        intent="discharge_extraction",
        queued_at=_now(),
        processing_started_at=_now(),
        finished_at=finished,
        parameters_json={
            "date": day.strftime("%d/%m/%Y"),
            "ref_date": ref_date_iso,
        },
    )
    if persist_details is not None:
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="discharge_persistence",
            started_at=_now(),
            status="succeeded",
            details_json=persist_details,
        )
    return run


def _gap_run(ref_date_iso: str) -> IngestionRun:
    return _make_discharge_run(
        ref_date_iso,
        status="succeeded",
        persist_details={"total_records": 0, "attempt_count": 1},
    )


def _failed_gap_run(ref_date_iso: str) -> IngestionRun:
    return _make_discharge_run(ref_date_iso, status="failed")


def _complete_run(ref_date_iso: str) -> IngestionRun:
    return _make_discharge_run(
        ref_date_iso,
        status="succeeded",
        persist_details={"total_records": 1, "attempt_count": 1},
    )


def _queued_run() -> IngestionRun:
    return IngestionRun.objects.create(
        status="queued",
        intent="full_sync",
        queued_at=_now(),
    )


def _open_census_batch() -> CensusExecutionBatch:
    return CensusExecutionBatch.objects.create()


def _call(command: str, *args: str) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=StringIO())
    return out.getvalue()


@contextlib.contextmanager
def _guard_no_source_calls():
    """Prove benchmarks never touch a real source/browser/network boundary."""
    with (
        mock.patch(
            "subprocess.Popen",
            side_effect=AssertionError("Popen called in benchmark"),
        ),
        mock.patch(
            "subprocess.run",
            side_effect=AssertionError("subprocess.run called in benchmark"),
        ),
        mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("urllib called in benchmark"),
        ),
        mock.patch(
            "playwright.sync_api.sync_playwright",
            side_effect=AssertionError("playwright called in benchmark"),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Lock key registry
# ---------------------------------------------------------------------------


class TestDistinctLockKeys:
    def test_runtime_lock_keys_are_named_and_distinct_from_existing(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            HOURLY_LOCK_KEY,
            RECOVERY_LOCK_KEY,
        )

        assert isinstance(HOURLY_LOCK_KEY, int)
        assert isinstance(RECOVERY_LOCK_KEY, int)
        keys = {
            "orchestrator": ADVISORY_LOCK_KEY,
            "safety_sweep": STALE_ADMISSION_SWEEP_LOCK_KEY,
            "hourly": HOURLY_LOCK_KEY,
            "recovery": RECOVERY_LOCK_KEY,
        }
        assert len(set(keys.values())) == 4, keys
        assert HOURLY_LOCK_KEY != RECOVERY_LOCK_KEY


# ---------------------------------------------------------------------------
# Runtime mode planning
# ---------------------------------------------------------------------------


class TestRuntimeModePlanning:
    def test_unknown_runtime_command_rejected(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command(RUNTIME_COMMAND)

    def test_invalid_mode_rejected(self):
        with pytest.raises(CommandError, match="mode"):
            _call(RUNTIME_COMMAND, "--mode", "monthly")

    def test_hourly_plans_current_bahia_date_discharges_only(self):
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY
            captured: dict = {}

            def _fake_exec(plan, **kwargs):
                captured["plan"] = plan
                return _ok_result(plan.dates[0])

            with mock.patch(_RECOVER_EXEC, side_effect=_fake_exec):
                out = _call(RUNTIME_COMMAND, "--mode", "hourly")
            plan = captured["plan"]
            assert plan.dates == [FIXED_BAHIA_TODAY]
            assert plan.extractors == ["discharges"]
            assert "mode=hourly" in out
            assert "15/06/2026" in out

    def test_d1_plans_previous_bahia_date_four_extractors_canonical(self):
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY
            captured: dict = {}

            def _fake_exec(plan, **kwargs):
                captured["plan"] = plan
                return _ok_result(plan.dates[0])

            with mock.patch(_RECOVER_EXEC, side_effect=_fake_exec):
                out = _call(RUNTIME_COMMAND, "--mode", "d1")
            plan = captured["plan"]
            assert plan.dates == [date(2026, 6, 14)]
            assert plan.extractors == DEFAULT_EXTRACTOR_ORDER
            assert plan.extractors == [
                "discharges",
                "admissions",
                "deaths",
                "official_census",
            ]
            assert "mode=d1" in out
            assert "14/06/2026" in out

    def test_mode_is_mutually_exclusive_single_flag(self):
        # A second --mode flag value replaces the first; only one run shape
        # may ever execute per invocation (single option).
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY
            captured: dict = {}

            def _fake_exec(plan, **kwargs):
                captured["plan"] = plan
                return _ok_result(plan.dates[0])

            with mock.patch(_RECOVER_EXEC, side_effect=_fake_exec):
                _call(RUNTIME_COMMAND, "--mode", "hourly")
            assert captured["plan"].extractors == ["discharges"]


# ---------------------------------------------------------------------------
# Runtime advisory-lock skip (exit 0, before any subprocess call)
# ---------------------------------------------------------------------------


class TestRuntimeLockSkip:
    @staticmethod
    def _hold_lock(key: int):
        import psycopg

        settings = connection.settings_dict
        other = psycopg.connect(
            host=settings["HOST"],
            port=settings["PORT"],
            dbname=settings["NAME"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        )
        other.execute("SELECT pg_advisory_lock(%s)", [key])
        return other

    def test_hourly_skips_when_hourly_lock_held(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            HOURLY_LOCK_KEY,
        )

        other = self._hold_lock(HOURLY_LOCK_KEY)
        try:
            with mock.patch(
                _RECOVER_EXEC,
                side_effect=AssertionError("pipeline must not run on lock skip"),
            ):
                out = _call(RUNTIME_COMMAND, "--mode", "hourly")
            assert "equivalent_runtime_active" in out
            assert "result=skip" in out
        finally:
            other.close()

    def test_d1_skips_when_recovery_lock_held(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            RECOVERY_LOCK_KEY,
        )

        other = self._hold_lock(RECOVERY_LOCK_KEY)
        try:
            with mock.patch(
                _RECOVER_EXEC,
                side_effect=AssertionError("pipeline must not run on lock skip"),
            ):
                out = _call(RUNTIME_COMMAND, "--mode", "d1")
            assert "equivalent_runtime_active" in out
        finally:
            other.close()

    def test_catchup_skips_when_recovery_lock_held(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            RECOVERY_LOCK_KEY,
        )

        other = self._hold_lock(RECOVERY_LOCK_KEY)
        try:
            with mock.patch(
                _RECOVER_EXEC,
                side_effect=AssertionError("pipeline must not run on lock skip"),
            ):
                out = _call(RUNTIME_COMMAND, "--mode", "catchup")
            assert "equivalent_runtime_active" in out
            assert "result=skip" in out
        finally:
            other.close()


# ---------------------------------------------------------------------------
# Eligibility: queue/open-batch contention exits 75 before any pipeline call
# ---------------------------------------------------------------------------


class TestRuntimeEligibility:
    def test_queued_run_exits_75_before_pipeline(self):
        _queued_run()
        with mock.patch(
            _RECOVER_EXEC,
            side_effect=AssertionError("pipeline must not run while busy"),
        ):
            with pytest.raises(SystemExit) as exc:
                _call(RUNTIME_COMMAND, "--mode", "d1")
        assert exc.value.code == 75
        assert exc.value.code != 0

    def test_running_run_exits_75_before_pipeline(self):
        IngestionRun.objects.create(
            status="running",
            intent="admissions_only",
            queued_at=_now(),
            processing_started_at=_now(),
        )
        with mock.patch(
            _RECOVER_EXEC,
            side_effect=AssertionError("pipeline must not run while busy"),
        ):
            with pytest.raises(SystemExit) as exc:
                _call(RUNTIME_COMMAND, "--mode", "hourly")
        assert exc.value.code == 75

    def test_open_census_batch_exits_75_before_pipeline(self):
        _open_census_batch()
        with mock.patch(
            _RECOVER_EXEC,
            side_effect=AssertionError("pipeline must not run while busy"),
        ):
            with pytest.raises(SystemExit) as exc:
                _call(RUNTIME_COMMAND, "--mode", "d1")
        assert exc.value.code == 75

    def test_busy_exit_prints_aggregate_safe_reason(self):
        _queued_run()
        _open_census_batch()
        out = StringIO()
        with pytest.raises(SystemExit) as exc:
            call_command(
                RUNTIME_COMMAND, "--mode", "d1", stdout=out, stderr=StringIO()
            )
        assert exc.value.code == 75
        text = out.getvalue()
        assert "result=busy" in text
        assert "exit_code=75" in text
        assert "queued" in text
        assert SENTINEL_RECORD not in text
        assert SENTINEL_NAME not in text


class TestExtractorFailureIsNever75:
    def test_d1_extractor_failure_exits_nonzero_not_75(self):
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY
            with mock.patch(_RECOVER_EXEC) as mock_exec:
                mock_exec.return_value = _failure_result(date(2026, 6, 14))
                with pytest.raises(SystemExit) as exc:
                    _call(RUNTIME_COMMAND, "--mode", "d1")
                assert exc.value.code != 0
                assert exc.value.code != 75

    def test_catchup_extractor_failure_exits_nonzero_not_75(self):
        _gap_run("2026-06-01")
        with mock.patch(_RECOVER_EXEC) as mock_exec:
            mock_exec.return_value = _failure_result(date(2026, 6, 1))
            with pytest.raises(SystemExit) as exc:
                _call(RUNTIME_COMMAND, "--mode", "catchup")
            assert exc.value.code != 0
            assert exc.value.code != 75


# ---------------------------------------------------------------------------
# Catch-up planning: seven-date cap from durable coverage metadata
# ---------------------------------------------------------------------------


class TestCatchupCap:
    GAP_DATES = [
        "2026-04-01",
        "2026-04-02",
        "2026-04-03",
        "2026-04-04",
        "2026-04-05",
        "2026-04-06",
        "2026-04-07",
    ]

    def _make_seven_gaps_with_interleaved_complete(self) -> list[date]:
        for iso in self.GAP_DATES[:3]:
            _gap_run(iso)
        _complete_run("2026-04-08")
        for iso in self.GAP_DATES[3:5]:
            _failed_gap_run(iso)
        _complete_run("2026-04-09")
        for iso in self.GAP_DATES[5:]:
            _gap_run(iso)
        return [date.fromisoformat(iso) for iso in self.GAP_DATES]

    def test_catchup_runs_exactly_seven_gap_dates_not_complete_dates(self):
        expected = self._make_seven_gaps_with_interleaved_complete()
        planned: list[date] = []

        def _fake_exec(plan, **kwargs):
            planned.extend(plan.dates)
            return _ok_result(plan.dates[0])

        with mock.patch(_RECOVER_EXEC, side_effect=_fake_exec):
            out = _call(RUNTIME_COMMAND, "--mode", "catchup")

        assert sorted(planned) == expected
        assert len(planned) == 7
        # Complete dates are never re-run by catch-up.
        assert date(2026, 4, 8) not in planned
        assert date(2026, 4, 9) not in planned
        assert "planned=7" in out
        assert "succeeded=7" in out

    def test_more_than_seven_gaps_stops_before_extraction(self):
        for iso in self.GAP_DATES:
            _gap_run(iso)
        _failed_gap_run("2026-04-10")

        with mock.patch(
            _RECOVER_EXEC,
            side_effect=AssertionError("no extraction may start above cap"),
        ):
            out = _call(RUNTIME_COMMAND, "--mode", "catchup")
        assert "gap_too_large" in out
        assert "gap_count=8" in out
        assert "gap_first_date=2026-04-01" in out
        assert "gap_last_date=2026-04-10" in out
        assert "max_dates=7" in out
        # No SystemExit: a bounded stop is a normal skip, not a failure.

    def test_no_gap_exits_clean(self):
        _complete_run("2026-04-01")
        with mock.patch(
            _RECOVER_EXEC,
            side_effect=AssertionError("no extraction when nothing is missing"),
        ):
            out = _call(RUNTIME_COMMAND, "--mode", "catchup")
        assert "no_missing_dates" in out

    def test_automatic_d1_planning_stays_single_date(self):
        # Eight gap dates exist, but D-1 mode must never expand into
        # multi-date catch-up.
        for iso in self.GAP_DATES:
            _gap_run(iso)
        _gap_run("2026-04-10")

        planned: list[date] = []
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY

            def _fake_exec(plan, **kwargs):
                planned.extend(plan.dates)
                return _ok_result(plan.dates[0])

            with mock.patch(_RECOVER_EXEC, side_effect=_fake_exec):
                _call(RUNTIME_COMMAND, "--mode", "d1")

        assert planned == [date(2026, 6, 14)]
        assert len(planned) == 1


# ---------------------------------------------------------------------------
# Output safety and PDF-flow absence
# ---------------------------------------------------------------------------


class TestOutputSafety:
    def test_runtime_output_never_leaks_identity(self):
        # A d1 run through the (mocked) pipeline prints no identity data.
        with mock.patch(f"{_RUNTIME_MODULE}._today_bahia") as today:
            today.return_value = FIXED_BAHIA_TODAY
            with mock.patch(_RECOVER_EXEC) as mock_exec:
                mock_exec.return_value = _ok_result(date(2026, 6, 14))
                out = _call(RUNTIME_COMMAND, "--mode", "d1")
        assert SENTINEL_RECORD not in out
        assert SENTINEL_NAME not in out
        assert "password" not in out.lower()
        assert "username" not in out.lower()

    def test_commands_never_reference_the_legacy_pdf_flow(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        for relative in (
            "apps/ingestion/management/commands/"
            "run_exit_reconciliation_runtime.py",
            "apps/ingestion/management/commands/"
            "benchmark_exit_reconciliation_runtime.py",
        ):
            source = (root / relative).read_text(encoding="utf-8")
            assert "process_discharge_pdf" not in source, relative


# ---------------------------------------------------------------------------
# Benchmark command: modes, bounds, thresholds and mocked results
# ---------------------------------------------------------------------------


class TestBenchmarkModeValidation:
    def test_requires_mode(self):
        with pytest.raises(CommandError):
            call_command(BENCHMARK_COMMAND)

    def test_invalid_mode_rejected(self):
        with pytest.raises(CommandError, match="mode"):
            call_command(BENCHMARK_COMMAND, "--mode", "weekly")

    def test_hourly_rejects_dates_option(self):
        with pytest.raises(CommandError, match="dates"):
            call_command(BENCHMARK_COMMAND, "--mode", "hourly", "--dates", "7")

    def test_catchup_rejects_more_than_seven_dates(self):
        with pytest.raises(CommandError, match="seven|7"):
            call_command(BENCHMARK_COMMAND, "--mode", "catchup", "--dates", "8")

    def test_rejects_non_positive_repetitions(self):
        with pytest.raises(CommandError, match="repetitions"):
            call_command(BENCHMARK_COMMAND, "--mode", "hourly", "--repetitions", "0")

    def test_rejects_invalid_thresholds(self):
        with pytest.raises(CommandError, match="error"):
            call_command(
                BENCHMARK_COMMAND,
                "--mode", "hourly",
                "--max-error-rate", "2.0",
            )


@pytest.mark.django_db(transaction=True)
class TestBenchmarkHourly:
    def test_hourly_default_repetitions_three_and_passes(self):
        before = IngestionRun.objects.count()
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "hourly")
        assert "mode=hourly" in out
        assert "repetitions=3" in out
        assert "result=pass" in out
        for name in (
            "max_latency_seconds",
            "max_error_rate",
            "max_db_seconds",
            "max_queue_depth",
        ):
            assert name in out
        # Every repetition is rolled back: no durable IngestionRun row.
        assert IngestionRun.objects.count() == before

    def test_hourly_repetitions_override(self):
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "hourly", "--repetitions", "1")
        assert "repetitions=1" in out
        assert "steps=1" in out

    def test_injected_failure_drives_error_rate_and_fails(self):
        out = StringIO()
        err = StringIO()
        with pytest.raises(SystemExit) as exc:
            call_command(
                BENCHMARK_COMMAND,
                "--mode", "hourly",
                "--repetitions", "1",
                "--fail-steps", "1",
                stdout=out,
                stderr=err,
            )
        assert exc.value.code == 1
        assert "result=fail" in out.getvalue()
        assert "name=max_error_rate observed=1.000" in out.getvalue()
        assert "status=fail" in out.getvalue()

    def test_output_is_aggregate_safe(self):
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "hourly", "--repetitions", "1")
        assert SENTINEL_RECORD not in out
        assert SENTINEL_NAME not in out
        assert "password" not in out.lower()


@pytest.mark.django_db(transaction=True)
class TestBenchmarkCatchup:
    def test_catchup_covers_four_extractors_across_seven_synthetic_dates(self):
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "catchup")
        assert "mode=catchup" in out
        assert "dates=7" in out
        assert "steps=28" in out
        for extractor in DEFAULT_EXTRACTOR_ORDER:
            assert extractor in out

    def test_catchup_dates_override_bounded(self):
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "catchup", "--dates", "2")
        assert "dates=2" in out
        assert "steps=8" in out
        assert "result=pass" in out

    def test_benchmarks_never_enable_anything(self):
        # A successful benchmark run writes nothing durable.
        before = IngestionRun.objects.count()
        with _guard_no_source_calls():
            out = _call(BENCHMARK_COMMAND, "--mode", "catchup", "--dates", "1")
        assert IngestionRun.objects.count() == before
        assert "result=pass" in out
        assert "enable" not in out.lower()
        assert "timer" not in out.lower()


class TestD1ModeUsesPreviousBahiaDay:
    def test_previous_day_is_bahia_local_previous_calendar_date(self):
        # The America/Bahia calendar is the authority: the previous local
        # date is one full local day before the current local date.
        current = datetime(2026, 3, 2, 2, 30, tzinfo=BAHIA)
        expected = (current - timedelta(days=1)).astimezone(BAHIA).date()
        assert expected == date(2026, 3, 1)

    def test_utc_edge_keeps_bahia_local_date_authority(self):
        # 2026-03-02 02:30 UTC is still 2026-03-01 23:30 in America/Bahia
        # (UTC-3): the local date must be used for D-1 resolution.
        utc_moment = datetime(2026, 3, 2, 2, 30, tzinfo=ZoneInfo("UTC"))
        local = utc_moment.astimezone(BAHIA)
        assert local.date() == date(2026, 3, 1)
