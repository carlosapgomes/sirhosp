"""Unit tests for the quiet-window D-1 exit recovery step (SLICE-ODER-S1).

Covers the in-process previous-day exit-reconciliation step added to the
adaptive census orchestrator loop (ADR-0010): eligibility plus quiet
window ``[01:00, 05:00) America/Bahia`` plus at most one attempt per
local Bahia date, failure isolation from the census cycle, and the
Bahia-literal window boundaries (never the host timezone).
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

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


def _utc(hour: int) -> datetime:
    """Aware UTC datetime (Bahia = UTC-3, no DST)."""
    return datetime(2026, 9, 6, hour, 0, tzinfo=dt_timezone.utc)


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


def _d1_calls(cc_mock: mock.Mock) -> list[object]:
    """Return only the call_command invocations for the quiet-window D-1 step.

    The orchestrator also issues intraday hourly recovery invocations through
    the same patched ``call_command`` (SLICE-OIDR-S1), so D-1 assertions
    filter the shared mock by mode instead of asserting on its total call
    count.
    """
    return [
        call
        for call in cc_mock.call_args_list
        if call.args == ("run_exit_reconciliation_runtime", "--mode", "d1")
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_eligible_in_quiet_window_runs_d1_before_cycle():
    """02:30 Bahia eligible: D-1 runs once, before hourly and the cycle."""
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
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    cycle_mock.assert_called_once()


def test_outside_quiet_window_skips_d1():
    """00:59, 05:00 and 14:00 Bahia: cycle runs, D-1 never invoked."""
    for now in (_bahia(0, 59), _bahia(5, 0), _bahia(14, 0)):
        cc_mock, cycle_mock = _run_loop(now)
        assert _d1_calls(cc_mock) == []
        cycle_mock.assert_called_once()


def test_at_most_one_attempt_per_local_date():
    """Two eligible iterations on the same local date run D-1 only once."""
    cc_mock, cycle_mock = _run_loop(_bahia(2, 0), iterations=2)
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    assert cycle_mock.call_count == 2


def test_d1_failure_logs_and_does_not_block_cycle(caplog):
    """A RuntimeError from the D-1 step is logged and the cycle proceeds."""
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(_bahia(3, 0), call_side_effect=boom)
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    cycle_mock.assert_called_once()
    assert any(
        "quiet-window D-1 recovery failed: RuntimeError" in r.message
        for r in caplog.records
        if r.levelno >= logging.ERROR
    )


def test_d1_system_exit_never_aborts_loop():
    """Even an exit-75 contention race (SystemExit) must not abort the loop."""
    def exit_75(*args, **kwargs):
        raise SystemExit(75)

    cc_mock, cycle_mock = _run_loop(_bahia(3, 0), call_side_effect=exit_75)
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    cycle_mock.assert_called_once()


def test_blocked_loop_never_runs_d1():
    """02:30 Bahia blocked by active runs: neither D-1 nor the cycle runs."""
    cc_mock, cycle_mock = _run_loop(_bahia(2, 30), eligible=False)
    cc_mock.assert_not_called()
    cycle_mock.assert_not_called()


@pytest.mark.parametrize(
    ("now", "should_run"),
    [
        (_bahia(0, 59), False),  # one minute before the window
        (_bahia(1, 0), True),    # window opens
        (_bahia(4, 59), True),   # window still open
        (_bahia(5, 0), False),   # window closed
        (_utc(4), True),         # UTC 04:00 == Bahia 01:00 (opens)
        (_utc(8), False),        # UTC 08:00 == Bahia 05:00 (closed)
    ],
)
def test_quiet_window_boundaries_use_bahia_literal(now, should_run):
    """The window is evaluated in America/Bahia, never the host timezone."""
    cc_mock, cycle_mock = _run_loop(now)
    if should_run:
        assert _d1_calls(cc_mock) == [
            mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
        ]
    else:
        assert _d1_calls(cc_mock) == []
    cycle_mock.assert_called_once()


def test_loop_exits_before_iteration_never_runs_d1():
    """should_stop=True up front: loop returns with no D-1 and no cycle."""
    with (
        mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=_eligible(),
        ),
        mock.patch(
            "apps.census.orchestration.run_single_cycle",
            return_value=dict(_SUCCESS),
        ) as cycle_mock,
        mock.patch(
            "apps.census.orchestration.call_command",
        ) as cc_mock,
        mock.MagicMock() as sleep_mock,
    ):
        run_loop(
            enable_stale_recovery=False,
            sleep_seconds=5,
            sleep_fn=sleep_mock,
            should_stop=lambda: True,
            now_fn=lambda: _bahia(2, 30),
        )
    cc_mock.assert_not_called()
    cycle_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Fix-cycle round 1 additions (P1-1, P1-2, P1-3 review gaps)
# ---------------------------------------------------------------------------


def test_two_distinct_bahia_dates_run_d1_twice_across_utc_midnight():
    """One D-1 per local Bahia date across consecutive UTC dates.

    A once-per-process flag (never reset across dates) would run D-1 only
    once; the correct per-local-date flag runs it once for each of the two
    dates below (UTC 05:00 == Bahia 02:00 on both days, in-window).
    """
    cc_mock, cycle_mock = _run_loop(
        now_sequence=[
            datetime(2026, 9, 7, 5, 0, tzinfo=dt_timezone.utc),  # Bahia 09-07 02:00
            datetime(2026, 9, 8, 5, 0, tzinfo=dt_timezone.utc),  # Bahia 09-08 02:00
        ],
        iterations=2,
    )
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1"),
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1"),
    ]
    assert cycle_mock.call_count == 2


def test_same_bahia_date_late_window_does_not_third_call():
    """A second in-window iteration on the same Bahia date adds no call.

    First iteration at UTC 09-07 05:00 (Bahia 09-07 02:00) runs D-1; a
    later iteration at UTC 09-07 07:59 (Bahia 09-07 04:59, still inside
    the window on the same local date) must not run it a second time.
    """
    cc_mock, cycle_mock = _run_loop(
        now_sequence=[
            datetime(2026, 9, 7, 5, 0, tzinfo=dt_timezone.utc),
            datetime(2026, 9, 7, 7, 59, tzinfo=dt_timezone.utc),
        ],
        iterations=2,
    )
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    assert cycle_mock.call_count == 2


def test_rollover_flag_tracks_bahia_local_date_across_utc_midnight(caplog):
    """The once-per-date flag follows Bahia local dates, not wall events.

    Iteration 2 happens at UTC 09-08 02:30 == Bahia 09-07 23:30 (outside
    the window): the correct implementation neither calls D-1 nor advances
    the flag. Iteration 3 at UTC 09-08 04:30 == Bahia 09-08 01:30 is a new
    in-window Bahia date and runs D-1 a second time. An implementation
    that advances its date key outside the window (or keys on the UTC
    date, on which iteration 2 already reads 09-08) would suppress that
    second call.

    Mutation-resistance note (round-2 review): a UTC-date key that only
    advances inside the window is behaviorally EQUIVALENT here — the
    quiet window [01:00, 05:00) America/Bahia maps to a fixed
    [04:00, 08:00) UTC (fixed -3 offset, no DST since 2019), where UTC
    and Bahia calendar dates always coincide, so no timestamp sequence
    inside the contract can separate the two. The log-date assertions
    below still pin the Bahia-local dates that actually reach the
    operator-visible aggregate logs.
    """
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")
    cc_mock, cycle_mock = _run_loop(
        now_sequence=[
            datetime(2026, 9, 7, 6, 0, tzinfo=dt_timezone.utc),  # Bahia 09-07 03:00
            datetime(2026, 9, 8, 2, 30, tzinfo=dt_timezone.utc),  # Bahia 09-07 23:30
            datetime(2026, 9, 8, 4, 30, tzinfo=dt_timezone.utc),  # Bahia 09-08 01:30
        ],
        iterations=3,
    )
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1"),
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1"),
    ]
    assert cycle_mock.call_count == 3
    start_dates = sorted(
        {
            r.message.split("local date ")[1][:10]
            for r in caplog.records
            if "Quiet-window D-1 recovery start" in r.message
        }
    )
    assert start_dates == ["2026-09-07", "2026-09-08"]


def test_failure_still_consumes_the_single_daily_attempt():
    """A failed D-1 attempt still counts as the day's one attempt.

    The flag is advanced before the call, so after a RuntimeError on the
    first in-window iteration, a second eligible iteration on the same
    Bahia date must NOT call D-1 again while the census cycle runs twice.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(
        now_sequence=[_bahia(2, 0), _bahia(3, 0)],  # same date 2026-09-06
        iterations=2,
        call_side_effect=boom,
    )
    assert _d1_calls(cc_mock) == [
        mock.call("run_exit_reconciliation_runtime", "--mode", "d1")
    ]
    assert cycle_mock.call_count == 2


def test_success_emits_aggregate_start_and_finish_logs(caplog):
    """A successful quiet-window step logs aggregate start and finish."""
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")
    cc_mock, cycle_mock = _run_loop(_bahia(2, 30))

    messages = [r.message for r in caplog.records]
    start = next(
        (m for m in messages if "Quiet-window D-1 recovery start" in m), None
    )
    finish = next(
        (m for m in messages if "Quiet-window D-1 recovery finished" in m),
        None,
    )
    assert start is not None
    assert "2026-09-06" in start
    assert finish is not None
    assert "2026-09-06" in finish
    assert len(_d1_calls(cc_mock)) == 1
    cycle_mock.assert_called_once()


def test_failure_path_logs_start_finish_and_exception_type(caplog):
    """The failure path logs start, exception type and finish (aggregate)."""
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(_bahia(3, 0), call_side_effect=boom)

    messages = [r.message for r in caplog.records]
    assert any("Quiet-window D-1 recovery start" in m for m in messages)
    assert any(
        "quiet-window D-1 recovery failed: RuntimeError" in m for m in messages
    )
    assert any("Quiet-window D-1 recovery finished" in m for m in messages)
    assert len(_d1_calls(cc_mock)) == 1
    cycle_mock.assert_called_once()
