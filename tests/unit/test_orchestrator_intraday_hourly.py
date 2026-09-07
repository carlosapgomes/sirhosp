"""Unit tests for the throttled intraday hourly discharge-recovery step
(SLICE-OIDR-S1).

Covers the in-process current-day discharge-recovery step added to the
adaptive census orchestrator loop (design D1-D3): eligible iterations run
``run_exit_reconciliation_runtime --mode hourly`` at most once per local
America/Bahia hour per process, after the quiet-window D-1 step (when
both fire) and before the census cycle. Failure isolation mirrors the D-1
step (ADR-0010): an exception or SystemExit is logged in aggregate-safe
form and never blocks the census cycle; a blocked loop never runs the
step; and the once-per-hour flag is advanced before the attempt so a
failure still consumes the hour.
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from apps.census.orchestration import OrchestratorDecision, run_loop

BAHIA = ZoneInfo("America/Bahia")

_SUCCESS = {
    "cycle_executed": True,
    "outcome": "success",
    "extraction_run_id": 42,
    "batch_id": 99,
    "message": "Census cycle completed successfully.",
    "error": "",
    "blocked_reason": "",
}


def _bahia(hour: int, minute: int = 0) -> datetime:
    """Aware datetime at the given wall-clock time in America/Bahia."""
    return datetime(2026, 9, 6, hour, minute, tzinfo=BAHIA)


def _utc(hour: int, minute: int = 0) -> datetime:
    """Aware UTC datetime (Bahia = UTC-3, no DST since 2019)."""
    return datetime(2026, 9, 6, hour, minute, tzinfo=dt_timezone.utc)


def _eligible(eligible: bool = True) -> OrchestratorDecision:
    return OrchestratorDecision(
        eligible=eligible,
        blocked_reason="" if eligible else "Active runs: 1 queued.",
        active_queued=0 if eligible else 1,
    )


def _run_loop(
    now: datetime | None = None,
    *,
    iterations: int = 1,
    eligible: bool = True,
    call_side_effect: object | None = None,
    now_sequence: list[datetime] | None = None,
) -> tuple[mock.Mock, mock.Mock]:
    """Run ``run_loop`` and return (call_command, cycle) mocks.

    ``now`` freezes the clock for every iteration; ``now_sequence``
    supplies one aware datetime per iteration (index ``i - 1`` during the
    ``i``-th iteration) and takes precedence when given.
    """
    state = {"count": 0}

    def controlled_stop() -> bool:
        state["count"] += 1
        return state["count"] > iterations

    if now_sequence is not None:
        times = now_sequence
    else:
        assert now is not None, "now or now_sequence is required"
        times = [now] * iterations

    def time_provider() -> datetime:
        return times[max(0, min(state["count"] - 1, len(times) - 1))]

    with (
        mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=_eligible(eligible),
        ),
        mock.patch(
            "apps.census.orchestration.run_single_cycle",
            return_value=dict(_SUCCESS),
        ) as cycle_mock,
        mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=call_side_effect,
        ) as cc_mock,
        mock.MagicMock() as sleep_mock,
    ):
        run_loop(
            enable_stale_recovery=False,
            sleep_seconds=5,
            sleep_fn=sleep_mock,
            should_stop=controlled_stop,
            now_fn=time_provider,
        )
        return cc_mock, cycle_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_new_hour_runs_hourly_before_cycle(caplog):
    """14:00 Bahia eligible: hourly runs once, before the census cycle."""
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")
    order: list[str] = []

    def cc_effect(*args, **kwargs):
        order.append("hourly")

    def cycle_effect(*args, **kwargs):
        order.append("cycle")
        return dict(_SUCCESS)

    state = {"count": 0}

    def controlled_stop() -> bool:
        state["count"] += 1
        return state["count"] > 1

    with (
        mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=_eligible(),
        ),
        mock.patch(
            "apps.census.orchestration.run_single_cycle",
            side_effect=cycle_effect,
        ) as cycle_mock,
        mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=cc_effect,
        ) as cc_mock,
        mock.MagicMock() as sleep_mock,
    ):
        run_loop(
            enable_stale_recovery=False,
            sleep_seconds=5,
            sleep_fn=sleep_mock,
            should_stop=controlled_stop,
            now_fn=lambda: _bahia(14, 0),
        )

    assert order == ["hourly", "cycle"]
    cc_mock.assert_called_once_with(
        "run_exit_reconciliation_runtime", "--mode", "hourly"
    )
    cycle_mock.assert_called_once()

    messages = [r.message for r in caplog.records]
    start = next(
        (m for m in messages if "Intraday hourly recovery start" in m), None
    )
    finish = next(
        (m for m in messages if "Intraday hourly recovery finished" in m),
        None,
    )
    # R1: start and finish are logged at info level with the explicit
    # local Bahia hour and the duration.
    assert start is not None
    assert "2026-09-06 14:00:00" in start
    assert "America/Bahia" in start
    assert finish is not None
    assert "2026-09-06 14:00:00" in finish
    assert "duration" in finish
    assert "seconds" in finish


def test_same_hour_skips():
    """Two eligible iterations in the same Bahia hour run hourly once."""
    cc_mock, cycle_mock = _run_loop(_bahia(14, 0), iterations=2)
    cc_mock.assert_called_once_with(
        "run_exit_reconciliation_runtime", "--mode", "hourly"
    )
    assert cycle_mock.call_count == 2


def test_next_hour_runs_again():
    """The throttle is per hour, not per day: hour 15 runs again."""
    cc_mock, cycle_mock = _run_loop(
        now_sequence=[_bahia(14, 0), _bahia(15, 0)],
        iterations=2,
    )
    cc_mock.assert_has_calls(
        [
            mock.call("run_exit_reconciliation_runtime", "--mode", "hourly"),
            mock.call("run_exit_reconciliation_runtime", "--mode", "hourly"),
        ]
    )
    assert cc_mock.call_count == 2
    assert cycle_mock.call_count == 2


def test_hour_guard_uses_bahia_local_hour(caplog):
    """UTC 17:xx == Bahia 14:xx: one run; UTC 18:00 == Bahia 15:00: another.

    Pins the throttle to the America/Bahia local hour fed by the injected
    ``now_fn`` (design D5): three UTC-sequential eligible iterations map to
    Bahia hours 14, 14, 15 and produce exactly two hourly executions.
    """
    cc_mock, cycle_mock = _run_loop(
        now_sequence=[
            _utc(17, 0),   # Bahia 14:00
            _utc(17, 45),  # Bahia 14:45 — same local hour
            _utc(18, 0),   # Bahia 15:00 — next local hour
        ],
        iterations=3,
    )
    assert cc_mock.call_count == 2
    cc_mock.assert_has_calls(
        [
            mock.call("run_exit_reconciliation_runtime", "--mode", "hourly"),
            mock.call("run_exit_reconciliation_runtime", "--mode", "hourly"),
        ]
    )
    assert cycle_mock.call_count == 3


def test_failure_does_not_block_cycle(caplog):
    """A RuntimeError from the hourly step is logged and the cycle runs."""
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(
        _bahia(14, 0), iterations=2, call_side_effect=boom
    )
    cc_mock.assert_called_once_with(
        "run_exit_reconciliation_runtime", "--mode", "hourly"
    )
    assert cycle_mock.call_count == 2
    assert any(
        "intraday hourly recovery failed: RuntimeError" in r.message
        for r in caplog.records
        if r.levelno >= logging.ERROR
    )


def test_system_exit_isolated():
    """Even an exit-75 contention race (SystemExit) must not abort the loop."""
    def exit_75(*args, **kwargs):
        raise SystemExit(75)

    cc_mock, cycle_mock = _run_loop(
        _bahia(14, 0), iterations=2, call_side_effect=exit_75
    )
    cc_mock.assert_called_once_with(
        "run_exit_reconciliation_runtime", "--mode", "hourly"
    )
    assert cycle_mock.call_count == 2


def test_blocked_loop_never_runs_hourly():
    """14:00 Bahia blocked by active runs: neither hourly nor the cycle runs."""
    cc_mock, cycle_mock = _run_loop(_bahia(14, 0), iterations=2, eligible=False)
    cc_mock.assert_not_called()
    cycle_mock.assert_not_called()


def test_d1_runs_before_hourly_in_same_iteration():
    """In-window iteration with both guards satisfied: D-1, hourly, cycle."""
    order: list[str] = []

    def cc_effect(command, *args, **kwargs):
        assert args[0] == "--mode"
        order.append(args[1])

    def cycle_effect(*args, **kwargs):
        order.append("cycle")
        return dict(_SUCCESS)

    state = {"count": 0}

    def controlled_stop() -> bool:
        state["count"] += 1
        return state["count"] > 1

    with (
        mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=_eligible(),
        ),
        mock.patch(
            "apps.census.orchestration.run_single_cycle",
            side_effect=cycle_effect,
        ) as cycle_mock,
        mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=cc_effect,
        ) as cc_mock,
        mock.MagicMock() as sleep_mock,
    ):
        run_loop(
            enable_stale_recovery=False,
            sleep_seconds=5,
            sleep_fn=sleep_mock,
            should_stop=controlled_stop,
            now_fn=lambda: _bahia(2, 30),
        )

    assert order == ["d1", "hourly", "cycle"]
    cc_mock.assert_has_calls(
        [
            mock.call("run_exit_reconciliation_runtime", "--mode", "d1"),
            mock.call("run_exit_reconciliation_runtime", "--mode", "hourly"),
        ]
    )
    assert cc_mock.call_count == 2
    cycle_mock.assert_called_once()


def test_failure_still_consumes_the_hour():
    """A failed hourly attempt still counts as the hour's one attempt.

    The flag is advanced before the call, so after a RuntimeError on the
    first eligible iteration of hour 14, a second eligible iteration in
    the same hour must NOT call hourly again while the cycle runs twice.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(
        now_sequence=[_bahia(14, 0), _bahia(14, 30)],
        iterations=2,
        call_side_effect=boom,
    )
    cc_mock.assert_called_once_with(
        "run_exit_reconciliation_runtime", "--mode", "hourly"
    )
    assert cycle_mock.call_count == 2


def test_failure_path_logs_start_finish_and_exception_type(caplog):
    """The hourly failure path logs start, exception type and finish."""
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(_bahia(14, 30), call_side_effect=boom)

    messages = [r.message for r in caplog.records]
    assert any("Intraday hourly recovery start" in m for m in messages)
    assert any(
        "intraday hourly recovery failed: RuntimeError" in m for m in messages
    )
    assert any("Intraday hourly recovery finished" in m for m in messages)
    cc_mock.assert_called_once()
    cycle_mock.assert_called_once()
