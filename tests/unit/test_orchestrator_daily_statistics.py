"""Unit tests for the adaptive daily statistics finalization step (SLICE-OASF-S2).

Covers the in-process finalization of the previous ``America/Bahia`` local
date added to the adaptive census orchestrator loop (design D1, D2, D4 and
D5): the pending date captured after the once-per-day D-1 attempt, the
ordering ``d1 -> statistics -> hourly -> cycle``, the drain check that is
independent from the census cooldown, the post-05:00 restart recovery through
the durable absence of a ready revision, one attempt per process, aggregate-only
failure handling, the canonical preflight markers and the Compose delivery of
the statistics configuration.

All fixtures are synthetic; no clinical identity, credential or nominal
command output is used.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings

from apps.census.orchestration import OrchestratorDecision, run_loop

ROOT = Path(__file__).resolve().parents[2]
BAHIA = ZoneInfo("America/Bahia")

ACTIVATION = date(2026, 9, 1)
# Local date 2026-09-06 -> D-1 statistics target.
TARGET_DATE = "2026-09-05"
D1_WARNING = "d1_recovery_incomplete"
NOT_CONFIRMED_WARNING = "d1_recovery_not_confirmed"
D1_MARKER = "mode=d1-recovery result=success source=adaptive-orchestrator"
HOURLY_MARKER = (
    "mode=hourly-discharges result=success source=adaptive-orchestrator"
)

_D1_COMMAND = "run_exit_reconciliation_runtime"
_STATS_COMMAND = "materialize_daily_statistics"

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


def _eligible() -> OrchestratorDecision:
    return OrchestratorDecision(eligible=True, blocked_reason="")


def _busy() -> OrchestratorDecision:
    """A drained check must fail: an active run remains."""
    return OrchestratorDecision(
        eligible=False,
        blocked_reason="Active runs: 1 running.",
        active_running=1,
    )


def _cooldown_only() -> OrchestratorDecision:
    """Cooldown blocks a new census but the queue is fully drained."""
    return OrchestratorDecision(
        eligible=False,
        blocked_reason="Cooldown (10 min remaining).",
        cooldown_remaining_minutes=10.0,
    )


def _run_loop(
    *,
    times: list[datetime],
    decisions: list[OrchestratorDecision] | None = None,
    call_side_effect: object | None = None,
    report_ready: bool = False,
    activation: date | None = ACTIVATION,
    iterations: int | None = None,
    order: list[str] | None = None,
) -> tuple[mock.Mock, mock.Mock]:
    """Run ``run_loop`` against a fully mocked boundary.

    ``times`` supplies one aware datetime per loop iteration. ``decisions``
    optionally supplies one ``OrchestratorDecision`` per call to
    ``compute_orchestrator_state`` (top of iteration plus the post-D-1
    re-evaluation); otherwise a constant eligible decision is used. ``order``
    records the observed D-1 / statistics / hourly / cycle sequence.
    Returns the ``call_command`` and ``run_single_cycle`` mocks.
    """
    state = {"count": 0}
    if iterations is None:
        iterations = len(times)

    def controlled_stop() -> bool:
        state["count"] += 1
        return state["count"] > iterations

    def time_provider() -> datetime:
        return times[max(0, min(state["count"] - 1, len(times) - 1))]

    if decisions is None:
        decision_patch = mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            return_value=_eligible(),
        )
    else:
        pending_decisions = list(decisions)
        decision_patch = mock.patch(
            "apps.census.orchestration.compute_orchestrator_state",
            side_effect=lambda **kwargs: pending_decisions.pop(0),
        )

    if call_side_effect is None and order is not None:
        def _record(command, *args, **kwargs):
            if command == _D1_COMMAND:
                order.append(args[1])
            elif command == _STATS_COMMAND:
                order.append("statistics")

        side_effect: object | None = _record
    else:
        side_effect = call_side_effect

    def cycle_effect(*args, **kwargs):
        if order is not None:
            order.append("cycle")
        return dict(_SUCCESS)

    with (
        decision_patch,
        mock.patch(
            "apps.census.orchestration.run_single_cycle",
            side_effect=cycle_effect,
        ) as cycle_mock,
        mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=side_effect,
        ) as cc_mock,
        # ``create=True`` keeps the RED run behavioral: before the helper
        # exists the patch must not turn every scenario into a setup error.
        mock.patch(
            "apps.census.orchestration._daily_statistics_report_ready",
            return_value=report_ready,
            create=True,
        ),
        mock.MagicMock() as sleep_mock,
        override_settings(STATISTICS_ACTIVATION_DATE=activation),
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
    return [
        call
        for call in cc_mock.call_args_list
        if call.args
        and call.args[0] == _D1_COMMAND
        and call.args[1:3] == ("--mode", "d1")
    ]


def _stats_calls(cc_mock: mock.Mock) -> list[object]:
    return [
        call
        for call in cc_mock.call_args_list
        if call.args and call.args[0] == _STATS_COMMAND
    ]


# ---------------------------------------------------------------------------
# R1 — order: d1 -> statistics -> hourly -> cycle
# ---------------------------------------------------------------------------


def test_successful_d1_finalizes_before_hourly_and_cycle():
    """An eligible in-window iteration publishes D-1 before hourly/census."""
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(times=[_bahia(2, 30)], order=order)

    assert order == ["d1", "statistics", "hourly", "cycle"]
    assert _stats_calls(cc_mock) == [
        mock.call(_STATS_COMMAND, "--date", TARGET_DATE)
    ]
    cycle_mock.assert_called_once()


# ---------------------------------------------------------------------------
# R2 — a D-1 that occupies the queue defers finalization
# ---------------------------------------------------------------------------


def test_busy_queue_after_d1_defers_finalization_to_next_drained_iteration():
    """No statistics call while blocked; exactly one on the next drained loop."""
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(2, 0), _bahia(2, 30)],
        decisions=[_eligible(), _busy(), _eligible()],
        order=order,
    )

    assert order == ["d1", "statistics", "hourly", "cycle"]
    assert _d1_calls(cc_mock) == [mock.call(_D1_COMMAND, "--mode", "d1")]
    assert _stats_calls(cc_mock) == [
        mock.call(_STATS_COMMAND, "--date", TARGET_DATE)
    ]
    assert cycle_mock.call_count == 1


# ---------------------------------------------------------------------------
# R3 — cooldown blocks the census, never the publication
# ---------------------------------------------------------------------------


def test_pending_is_published_when_only_cooldown_blocks_census():
    """A cooldown-only decision still publishes the drain-safe pending date."""
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(2, 30)],
        decisions=[_eligible(), _cooldown_only()],
        order=order,
    )

    assert order == ["d1", "statistics"]
    assert _stats_calls(cc_mock) == [
        mock.call(_STATS_COMMAND, "--date", TARGET_DATE)
    ]
    cycle_mock.assert_not_called()


# ---------------------------------------------------------------------------
# R4 — failed D-1 still finalizes with the enumerated warning
# ---------------------------------------------------------------------------


def test_failed_d1_finalizes_with_incomplete_warning():
    """A RuntimeError D-1 still captures the pending date as degraded."""

    def cc_effect(command, *args, **kwargs):
        if command == _D1_COMMAND:
            raise RuntimeError("boom")

    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(3, 0)], call_side_effect=cc_effect
    )

    assert _stats_calls(cc_mock) == [
        mock.call(
            _STATS_COMMAND,
            "--date",
            TARGET_DATE,
            "--quality-warning",
            D1_WARNING,
        )
    ]
    cycle_mock.assert_called_once()


def test_d1_system_exit_finalizes_with_incomplete_warning():
    """An exit-75 contention race is captured like any observed failure."""

    def cc_effect(command, *args, **kwargs):
        if command == _D1_COMMAND:
            raise SystemExit(75)

    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(3, 0)], call_side_effect=cc_effect
    )

    assert _stats_calls(cc_mock) == [
        mock.call(
            _STATS_COMMAND,
            "--date",
            TARGET_DATE,
            "--quality-warning",
            D1_WARNING,
        )
    ]
    cycle_mock.assert_called_once()


def test_successful_d1_finalizes_without_warning():
    """A successful D-1 call carries no degradation warning."""
    cc_mock, _ = _run_loop(times=[_bahia(3, 0)])

    assert _stats_calls(cc_mock) == [
        mock.call(_STATS_COMMAND, "--date", TARGET_DATE)
    ]


# ---------------------------------------------------------------------------
# R5 — finalization failure is aggregate, consumed and non-blocking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("boom"), SystemExit(75)],
    ids=["runtime-error", "system-exit"],
)
def test_finalization_failure_logs_aggregate_and_never_blocks_the_loop(
    exc, caplog
):
    """Failures record only the technical class and date, once per process."""
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")
    calls = {"count": 0}

    def cc_effect(command, *args, **kwargs):
        if command == _STATS_COMMAND:
            calls["count"] += 1
            raise exc

    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(3, 0), _bahia(3, 30)], call_side_effect=cc_effect
    )

    assert calls["count"] == 1
    assert cycle_mock.call_count == 2

    messages = [r.message for r in caplog.records]
    assert any(
        TARGET_DATE in message and type(exc).__name__ in message
        for message in messages
    )


# ---------------------------------------------------------------------------
# R6 — one attempt per process, restart may repeat safely
# ---------------------------------------------------------------------------


def test_same_date_is_not_materialized_twice_within_one_process():
    cc_mock, cycle_mock = _run_loop(times=[_bahia(3, 0), _bahia(3, 30)])

    assert len(_stats_calls(cc_mock)) == 1
    assert cycle_mock.call_count == 2


def test_restart_inside_the_window_repeats_d1_and_finalization():
    """Two separate process runs each perform their own idempotent attempt."""
    first_cc, _ = _run_loop(times=[_bahia(2, 30)])
    second_cc, _ = _run_loop(times=[_bahia(2, 30)])

    assert _d1_calls(first_cc) == [mock.call(_D1_COMMAND, "--mode", "d1")]
    assert _d1_calls(second_cc) == [mock.call(_D1_COMMAND, "--mode", "d1")]
    assert len(_stats_calls(first_cc)) == 1
    assert len(_stats_calls(second_cc)) == 1


# ---------------------------------------------------------------------------
# R7 — canonical aggregate markers only on success
# ---------------------------------------------------------------------------


def test_successful_d1_and_hourly_emit_the_canonical_markers(caplog):
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")
    _run_loop(times=[_bahia(2, 30)])

    messages = [r.message for r in caplog.records]
    assert messages.count(D1_MARKER) == 1
    assert messages.count(HOURLY_MARKER) == 1


def test_failed_d1_and_hourly_never_emit_success_markers(caplog):
    caplog.set_level(logging.INFO, logger="apps.census.orchestration")

    def cc_effect(command, *args, **kwargs):
        raise RuntimeError("boom")

    _run_loop(times=[_bahia(2, 30)], call_side_effect=cc_effect)

    messages = [r.message for r in caplog.records]
    assert D1_MARKER not in messages
    assert HOURLY_MARKER not in messages
    assert not any("result=success" in message for message in messages)


# ---------------------------------------------------------------------------
# R8 — Compose delivers the bounded, fail-closed statistics configuration
# ---------------------------------------------------------------------------


def _service_block(compose: str, service: str) -> str:
    matches = re.search(
        rf"^  {service}:\n(?P<body>(?:    .*\n|\n)+?)"
        r"(?=^  [a-z][a-z0-9_]*:\n|^volumes:\n|^networks:\n|\Z)",
        compose,
        re.MULTILINE,
    )
    assert matches, f"service {service!r} not found in Compose"
    return matches.group("body")


def test_compose_delivers_statistics_configuration_to_the_orchestrator():
    compose = (ROOT / "compose.hospital.yml").read_text(encoding="utf-8")
    block = _service_block(compose, "census_orchestrator")

    assert 'STATISTICS_ACTIVATION_DATE: "${STATISTICS_ACTIVATION_DATE:-}"' in block
    assert (
        "STATISTICS_FINALIZATION_LOOKBACK_DAYS: "
        '"${STATISTICS_FINALIZATION_LOOKBACK_DAYS:-7}"'
    ) in block

    # Fail-closed and scoped: exactly the orchestrator declares each variable
    # and the override introduces no new credential.
    activation_keys = [
        line
        for line in compose.splitlines()
        if line.strip().startswith("STATISTICS_ACTIVATION_DATE:")
    ]
    lookback_keys = [
        line
        for line in compose.splitlines()
        if line.strip().startswith("STATISTICS_FINALIZATION_LOOKBACK_DAYS:")
    ]
    assert len(activation_keys) == 1
    assert len(lookback_keys) == 1
    assert activation_keys[0].strip() == (
        'STATISTICS_ACTIVATION_DATE: "${STATISTICS_ACTIVATION_DATE:-}"'
    )
    assert lookback_keys[0].strip() == (
        "STATISTICS_FINALIZATION_LOOKBACK_DAYS: "
        '"${STATISTICS_FINALIZATION_LOOKBACK_DAYS:-7}"'
    )
    assert "PASSWORD" not in block
    assert "SECRET" not in block


# ---------------------------------------------------------------------------
# R10 — post-05:00 restart recovers through the durable absence of a revision
# ---------------------------------------------------------------------------


def test_post_window_restart_recovers_missing_report_with_not_confirmed_warning():
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(times=[_bahia(6, 0)], order=order)

    assert _d1_calls(cc_mock) == []
    assert _stats_calls(cc_mock) == [
        mock.call(
            _STATS_COMMAND,
            "--date",
            TARGET_DATE,
            "--quality-warning",
            NOT_CONFIRMED_WARNING,
        )
    ]
    assert order == ["statistics", "hourly", "cycle"]
    cycle_mock.assert_called_once()


def test_post_window_recovery_waits_for_the_first_drained_iteration():
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(6, 0), _bahia(6, 30)],
        decisions=[_busy(), _eligible()],
        order=order,
    )

    assert order == ["statistics", "hourly", "cycle"]
    assert len(_stats_calls(cc_mock)) == 1
    cycle_mock.assert_called_once()


# ---------------------------------------------------------------------------
# R11 — ready revision, absent boundary and pre-boundary date are inert
# ---------------------------------------------------------------------------


def test_ready_revision_creates_no_recovery_pending():
    order: list[str] = []
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(6, 0)], report_ready=True, order=order
    )

    assert _stats_calls(cc_mock) == []
    assert order == ["hourly", "cycle"]
    cycle_mock.assert_called_once()


def test_absent_activation_creates_no_pending_in_or_out_of_window():
    for hour in (2, 6):
        cc_mock, cycle_mock = _run_loop(
            times=[_bahia(hour)], activation=None
        )
        assert _stats_calls(cc_mock) == []
        assert cycle_mock.call_count == 1


def test_target_before_activation_creates_no_pending_in_window():
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(2, 30)], activation=date(2026, 9, 10)
    )

    assert _d1_calls(cc_mock) == [mock.call(_D1_COMMAND, "--mode", "d1")]
    assert _stats_calls(cc_mock) == []
    cycle_mock.assert_called_once()


def test_target_before_activation_creates_no_post_window_pending():
    cc_mock, cycle_mock = _run_loop(
        times=[_bahia(6, 0)], activation=date(2026, 9, 10)
    )

    assert _stats_calls(cc_mock) == []
    cycle_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Bahia boundary 04:59 / 05:00
# ---------------------------------------------------------------------------


def test_boundary_0459_finalizes_naturally_and_0500_recovers_unconfirmed():
    order_0459: list[str] = []
    cc_0459, _ = _run_loop(times=[_bahia(4, 59)], order=order_0459)
    assert _d1_calls(cc_0459) == [mock.call(_D1_COMMAND, "--mode", "d1")]
    assert _stats_calls(cc_0459) == [
        mock.call(_STATS_COMMAND, "--date", TARGET_DATE)
    ]
    assert order_0459 == ["d1", "statistics", "hourly", "cycle"]

    order_0500: list[str] = []
    cc_0500, _ = _run_loop(times=[_bahia(5, 0)], order=order_0500)
    assert _d1_calls(cc_0500) == []
    assert _stats_calls(cc_0500) == [
        mock.call(
            _STATS_COMMAND,
            "--date",
            TARGET_DATE,
            "--quality-warning",
            NOT_CONFIRMED_WARNING,
        )
    ]
    assert order_0500 == ["statistics", "hourly", "cycle"]
