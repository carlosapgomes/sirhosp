"""HTEFS-S5 — sanitized substep observability (consolidated).

Covers the targeted evolution substep protocol end to end without any real
browser, network, or legacy access:

- closed ``EvolutionSubstep`` enum (exactly the nine sanitized names, each
  within the stage-metric 50-char capacity, no dynamic names possible);
- ordered ``started`` → terminal pairs for every instrumented substep in a
  successful targeted flow (search, admissions, selection, detail, action,
  report, download, parse);
- localized failures: activation timeout keeps the ``timeout`` taxonomy and
  parse failure keeps ``invalid_payload`` — telemetry never reclassifies;
- optional telemetry: no callback keeps legacy contracts (real dispatch
  kwargs, stub path) and a broken callback is best-effort — it can neither
  block the extraction nor replace the action exception;
- worker materialization: terminal ``IngestionRunStageMetric`` rows with
  enum-derived names, timestamps and no dynamic payload; ``started`` is
  never persisted;
- aggregate chunk counters (``chunks_planned``/``chunks_committed``/
  ``chunks_failed``/``events_processed``, integers only) consistent with the
  cumulative run counters and the coverage ledger on full success, on
  partial failure, and after a chunk-transaction failure;
- sentinel absence: distinct sentinels injected into patient record,
  admission key, dates, URL, selector, cookie and raw exception text never
  reach stdout/stderr or any new ``details_json`` surface.

All identifiers and dates are clearly synthetic (``SYN-*`` / ``ZQ7-*``).
"""

from __future__ import annotations

import datetime
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.legacy_navigation import NavigationTimeoutError
from apps.ingestion.extractors.persistent_evolution_pdf import EvolutionPdfError
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
from apps.ingestion.extractors.session_controller import SessionControllerConfig
from apps.ingestion.models import IngestionRunStageMetric
from tests.unit.test_incremental_evolution_coverage import (
    _admission,
    _evolution,
    _patient,
    _queue_targeted_run,
    _run_worker,
    _snapshot_row,
)
from tests.unit.test_persistent_extraction_adapter import FakeExtractionSession
from tests.unit.test_persistent_worker_command import _make_adapter_mock
from tests.unit.test_real_handle_bridge import FakePlaywrightHandle
from tests.unit.test_targeted_evolution_admission import (
    _EVOLUTION_CONTAINER_HTML,
    _SESSION_COUNTER_HTML,
    _row,
    _target_context,
)

_WORKER_MODULE = (
    "apps.ingestion.management.commands."
    "process_ingestion_runs_persistent_session"
)
_BASE_BRIDGE = "apps.ingestion.extractors.real_handle_bridge"

_EXPECTED_FLOW_SUBSTEPS = (
    "evolution_search_navigation",
    "evolution_admissions_capture",
    "evolution_target_selection",
    "evolution_detail_open",
    "evolution_action_activation",
    "evolution_report_generation",
    "evolution_pdf_download",
    "evolution_pdf_parse",
)

_AGGREGATE_KEYS = (
    "chunks_planned",
    "chunks_committed",
    "chunks_failed",
    "events_processed",
)

# Distinct sensitive sentinels (RED item 12). None of them may appear in
# stdout/stderr or in any new stage-metric details surface.
_SENT_PAT = "ZQ7SENTINELPAT"
_SENT_KEY = "ZQ7SENTINELKEY"
_SENT_DATE = "ZQ7SENTINELDATE"
_SENT_URL = "ZQ7SENTINELURL"
_SENT_SELECTOR = "ZQ7SENTINELSELECTOR"
_SENT_COOKIE = "ZQ7SENTINELCOOKIE"
_SENT_RAW = "ZQ7SENTINELRAW"
_ALL_SENTINELS = (
    _SENT_PAT,
    _SENT_KEY,
    _SENT_DATE,
    _SENT_URL,
    _SENT_SELECTOR,
    _SENT_COOKIE,
    _SENT_RAW,
)


# ---------------------------------------------------------------------------
# Bridge flow helper (all nav helpers patched — no Playwright, no network)
# ---------------------------------------------------------------------------


def _run_bridge_flow(
    *,
    snapshot: list[dict[str, str]],
    target: Any,
    click_evolucao_side_effect: Exception | None = None,
    extract_text_side_effect: Exception | None = None,
    report_ready: list[bool] | None = None,
    progress_callback: Any = None,
    start_date: str = "2024-03-01",
    end_date: str = "2024-03-10",
    normalized_content: str = "SYNTH ok content",
) -> list[dict[str, Any]]:
    """Run the targeted action flow with every nav helper patched.

    When ``progress_callback`` is not ``None`` it is passed to the bridge as
    the optional telemetry callback (a plain ``list.append`` collects
    ``(substep, status)`` pairs; a raising mock proves best-effort).
    """
    spies = {
        name: MagicMock()
        for name in (
            "ensure_search_screen",
            "search_patient",
            "click_internacoes",
            "open_internacao_detail",
            "click_evolucao",
            "fill_evolution_dates",
            "select_ascending_order",
            "click_visualizar_report",
            "go_back_to_detail_from_report",
        )
    }
    if click_evolucao_side_effect is not None:
        spies["click_evolucao"].side_effect = click_evolucao_side_effect
    spies["fill_evolution_dates"].side_effect = lambda *a, **k: True

    bridge = RealHandleBridge(FakePlaywrightHandle())
    kwargs: dict[str, Any] = {
        "patient_record": "SYN-PR-1",
        "start_date": start_date,
        "end_date": end_date,
        "timeout": 60,
        "target_admission": target,
    }
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback

    with (
        patch(
            f"{_BASE_BRIDGE}.ensure_search_screen", spies["ensure_search_screen"]
        ),
        patch(f"{_BASE_BRIDGE}.search_patient", spies["search_patient"]),
        patch(f"{_BASE_BRIDGE}.click_internacoes", spies["click_internacoes"]),
        patch(
            f"{_BASE_BRIDGE}._read_and_build_snapshot",
            MagicMock(return_value=list(snapshot)),
        ),
        patch(
            f"{_BASE_BRIDGE}.open_internacao_detail",
            spies["open_internacao_detail"],
        ),
        patch(f"{_BASE_BRIDGE}.click_evolucao", spies["click_evolucao"]),
        patch(f"{_BASE_BRIDGE}.fill_evolution_dates", spies["fill_evolution_dates"]),
        patch(
            f"{_BASE_BRIDGE}.select_ascending_order",
            spies["select_ascending_order"],
        ),
        patch(
            f"{_BASE_BRIDGE}.click_visualizar_report",
            spies["click_visualizar_report"],
        ),
        patch(
            f"{_BASE_BRIDGE}.go_back_to_detail_from_report",
            spies["go_back_to_detail_from_report"],
        ),
        patch(
            f"{_BASE_BRIDGE}.wait_for_report_or_no_evolutions",
            MagicMock(
                side_effect=report_ready if report_ready is not None else [True]
            ),
        ),
        patch.object(
            bridge,
            "_resolve_pdf_url_from_report_page",
            MagicMock(return_value=f"https://legacy.example/{_SENT_URL}/report.pdf"),
        ),
        patch.object(
            bridge, "_download_pdf", MagicMock(return_value=b"%PDF-1.4 synth")
        ),
        patch(
            f"{_BASE_BRIDGE}.extract_pdf_text",
            MagicMock(side_effect=extract_text_side_effect or "raw synth text"),
        ),
        patch(
            f"{_BASE_BRIDGE}.normalize_pdf_report_text",
            MagicMock(
                side_effect=lambda *a, **k: [
                    {
                        "admission_key": k.get("admission_key", ""),
                        "happened_at": "2024-03-05T09:00:00",
                        "event_type": "medical",
                        "content": normalized_content,
                        "profession": "Dr Synth",
                    }
                ]
            ),
        ),
        patch.object(bridge, "_resolve_active_page", return_value=MagicMock()),
    ):
        return bridge.extract_evolutions_via_legacy_actions(**kwargs)


def _collector(events: list[tuple[Any, str]]) -> Any:
    """Two-argument callback that appends ``(substep, status)`` pairs."""

    def _collect(substep: Any, status: str) -> None:
        events.append((substep, status))

    return _collect


def _statuses_for(
    events: list[tuple[Any, str]], substep_value: str
) -> list[str]:
    """Status sequence recorded for one substep value."""
    return [status for substep, status in events if substep.value == substep_value]


# ===========================================================================
# R1 — closed enum (RED item 1)
# ===========================================================================


class TestClosedSubstepEnum:
    """Exactly the nine sanitized names; no dynamic name can be emitted."""

    def test_enum_members_are_exactly_the_nine_closed_names(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import EvolutionSubstep

        assert {substep.value for substep in EvolutionSubstep} == {
            "evolution_search_navigation",
            "evolution_admissions_capture",
            "evolution_target_selection",
            "evolution_detail_open",
            "evolution_action_activation",
            "evolution_report_generation",
            "evolution_pdf_download",
            "evolution_pdf_parse",
            "evolution_chunk_commit",
        }
        # Stable names, unique, and within the stage-metric 50-char capacity.
        values = [substep.value for substep in EvolutionSubstep]
        assert len(values) == len(set(values))
        assert all(len(value) <= 50 for value in values)
        assert all(value.startswith("evolution_") for value in values)


# ===========================================================================
# R2/R3 — ordered pairs and localized failures in the bridge flow
# ===========================================================================


class TestBridgeOrderedSubsteps:
    """Successful targeted flow emits started→succeeded exactly once per
    instrumented substep, in flow order; the callback receives ONLY an enum
    member and a status string — never a payload (R9, structural)."""

    def test_successful_targeted_flow_emits_ordered_pairs(self) -> None:
        events: list[tuple[Any, str]] = []
        snapshot = [_row("SYN-RK-CUR", "2024-03-01")]
        target = _target_context(
            start_date="2024-03-01", source_admission_key="SYN-RK-STALE"
        )
        result = _run_bridge_flow(
            snapshot=snapshot,
            target=target,
            progress_callback=_collector(events),
        )

        assert len(result) == 1
        started_order = [
            substep.value for substep, status in events if status == "started"
        ]
        assert started_order == list(_EXPECTED_FLOW_SUBSTEPS)
        for value in _EXPECTED_FLOW_SUBSTEPS:
            assert _statuses_for(events, value) == ["started", "succeeded"], value

    def test_callback_receives_only_enum_and_status_no_payload(self) -> None:
        """Structural R9 proof: every emission is exactly
        ``(EvolutionSubstep, status)`` with no third argument, kwargs, or
        dynamic object — even with sentinel-laden inputs (URL, clinical
        text, admission key, patient record)."""
        from apps.ingestion.extractors.real_handle_bridge import (
            SUBSTEP_STATUSES,
            EvolutionSubstep,
        )

        events: list[tuple[Any, str]] = []

        def strict_callback(substep: Any, status: str) -> None:
            assert isinstance(substep, EvolutionSubstep)
            assert status in SUBSTEP_STATUSES
            events.append((substep, status))

        _run_bridge_flow(
            snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
            target=_target_context(start_date="2024-03-01"),
            normalized_content=f"clinical {_SENT_RAW} text",
            progress_callback=strict_callback,
        )
        assert len(events) >= 2 * len(_EXPECTED_FLOW_SUBSTEPS)

    def test_explicit_empty_report_succeeds_reached_substeps(self) -> None:
        """R3: an explicit no-evolutions dialog is SUCCESS for the actions
        that reached it (never a failed telemetry row)."""
        events: list[tuple[Any, str]] = []
        result = _run_bridge_flow(
            snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
            target=_target_context(start_date="2024-03-01"),
            report_ready=[False],
            progress_callback=_collector(events),
        )

        assert result == []
        # Substeps UP TO the report wait succeeded; download/parse are not
        # reached by an explicit no-evolutions result, so they emit nothing
        # (R3: explicit empty is success for the actions that reached it).
        for value in _EXPECTED_FLOW_SUBSTEPS[:6]:
            assert _statuses_for(events, value) == ["started", "succeeded"], value
        assert _statuses_for(events, "evolution_pdf_download") == []
        assert _statuses_for(events, "evolution_pdf_parse") == []

    def test_activation_timeout_emits_failed_and_keeps_timeout_taxonomy(
        self,
    ) -> None:
        """R3/R9: the activation substep is localized as failed and the SAME
        typed timeout propagates for the run's ``timeout`` classification."""
        from apps.ingestion.run_lifecycle import classify_failure_reason

        events: list[tuple[Any, str]] = []
        with pytest.raises(NavigationTimeoutError) as exc_info:
            _run_bridge_flow(
                snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
                target=_target_context(start_date="2024-03-01"),
                click_evolucao_side_effect=NavigationTimeoutError(
                    "source-system action timed out (sanitized)"
                ),
                progress_callback=_collector(events),
            )

        assert _statuses_for(events, "evolution_action_activation") == [
            "started",
            "failed",
        ]
        # Later substeps never started.
        assert _statuses_for(events, "evolution_report_generation") == []
        # The original typed exception is preserved and classifies as timeout.
        assert classify_failure_reason(exc_info.value) == ("timeout", True)

    def test_parse_failure_emits_failed_and_keeps_invalid_payload_taxonomy(
        self,
    ) -> None:
        """R3/R9: a PDF parse failure is localized on ``evolution_pdf_parse``
        while the existing ``invalid_payload`` classification is unchanged."""
        from apps.ingestion.run_lifecycle import classify_failure_reason

        events: list[tuple[Any, str]] = []
        with pytest.raises(EvolutionPdfError):
            _run_bridge_flow(
                snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
                target=_target_context(start_date="2024-03-01"),
                extract_text_side_effect=EvolutionPdfError(
                    "Evolution report could not be read (sanitized)"
                ),
                progress_callback=_collector(events),
            )

        assert _statuses_for(events, "evolution_pdf_download") == [
            "started",
            "succeeded",
        ]
        assert _statuses_for(events, "evolution_pdf_parse") == ["started", "failed"]
        assert classify_failure_reason(
            EvolutionPdfError("Evolution report could not be read (sanitized)")
        ) == ("invalid_payload", False)


# ===========================================================================
# R5 — best-effort telemetry in the bridge
# ===========================================================================


class TestBrokenCallbackBestEffort:
    """A callback that raises must neither block extraction nor replace the
    original action exception (R5)."""

    def test_broken_callback_does_not_block_extraction(self) -> None:
        broken = MagicMock(side_effect=RuntimeError(f"{_SENT_RAW} exploded"))
        result = _run_bridge_flow(
            snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
            target=_target_context(start_date="2024-03-01"),
            progress_callback=broken,
        )
        assert len(result) == 1, "broken telemetry must not stop the extraction"
        assert broken.called

    def test_broken_callback_does_not_replace_action_exception(self) -> None:
        """The action's typed timeout must propagate — never the callback's
        RuntimeError."""
        broken = MagicMock(side_effect=RuntimeError(f"{_SENT_RAW} exploded"))
        with pytest.raises(NavigationTimeoutError):
            _run_bridge_flow(
                snapshot=[_row("SYN-RK-CUR", "2024-03-01")],
                target=_target_context(start_date="2024-03-01"),
                click_evolucao_side_effect=NavigationTimeoutError(
                    "source-system action timed out (sanitized)"
                ),
                progress_callback=broken,
            )


# ===========================================================================
# R10 — callback absence keeps adapter/stub contracts (RED item 5)
# ===========================================================================


class TestCallbackAbsenceContracts:
    """No callback: real dispatch kwargs byte-identical, stub path ignores
    telemetry, bridge flow unchanged."""

    def test_adapter_without_callback_real_dispatch_kwargs_unchanged(self) -> None:
        handle = FakePlaywrightHandle()
        handle.set_html(_SESSION_COUNTER_HTML)
        bridge = RealHandleBridge(handle)
        action = MagicMock(return_value=[])
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )
        with patch.object(
            bridge, "extract_evolutions_via_legacy_actions", action
        ):
            adapter.extract_evolutions(
                patient_record="SYN-PR-1",
                start_date="2024-03-01",
                end_date="2024-03-10",
                timeout=33,
            )
        assert action.call_count == 1
        assert "progress_callback" not in action.call_args.kwargs

    def test_adapter_forwards_callback_only_to_real_action(self) -> None:
        handle = FakePlaywrightHandle()
        handle.set_html(_SESSION_COUNTER_HTML)
        bridge = RealHandleBridge(handle)
        action = MagicMock(return_value=[])
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )
        callback = MagicMock()
        with patch.object(
            bridge, "extract_evolutions_via_legacy_actions", action
        ):
            adapter.extract_evolutions(
                patient_record="SYN-PR-1",
                start_date="2024-03-01",
                end_date="2024-03-10",
                timeout=33,
                progress_callback=callback,
            )
        assert action.call_args.kwargs["progress_callback"] is callback
        # The adapter itself never invokes the callback — only the real
        # action method receives it.
        callback.assert_not_called()

    def test_stub_path_ignores_callback(self) -> None:
        """The stub URL/container path must not receive the callback kwarg
        and must keep working when a caller passes one."""
        session = FakeExtractionSession()
        session.set_html(_SESSION_COUNTER_HTML + _EVOLUTION_CONTAINER_HTML)
        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )
        result = adapter.extract_evolutions(
            patient_record="SYN-PR-1",
            start_date="2024-03-01",
            end_date="2024-03-10",
            progress_callback=MagicMock(),
        )
        assert isinstance(result, list)
        assert result[0]["admission_key"] == "SYN-RK-1"


# ===========================================================================
# R4 — worker materialization of stage metrics (RED item 7)
# ===========================================================================


@pytest.mark.django_db
class TestWorkerStageMaterialization:
    """Terminal stage rows carry enum names, timestamps and no payload;
    ``started`` is never persisted."""

    def test_worker_materializes_stage_metrics_from_callback_events(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import EvolutionSubstep

        patient = _patient("SYN-SUB-M1")
        admission = _admission(
            patient, key="SYN-SUB-ADM-M1",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-SUB-M1",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-SUB-ADM-M1", "2024-01-01")],
        )

        def extract_side_effect(**kwargs):
            on_progress = kwargs.get("progress_callback")
            if on_progress is not None:
                on_progress(EvolutionSubstep.ACTION_ACTIVATION, "started")
                on_progress(EvolutionSubstep.ACTION_ACTIVATION, "succeeded")
                on_progress(EvolutionSubstep.PDF_PARSE, "started")
                on_progress(EvolutionSubstep.PDF_PARSE, "failed")
            return [_evolution("SYN-SUB-ADM-M1", "2024-01-05T10:00:00")]

        adapter.extract_evolutions.side_effect = extract_side_effect
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        rows = list(IngestionRunStageMetric.objects.filter(run=run))
        by_pair = {(row.stage_name, row.status): row for row in rows}
        activation = by_pair[("evolution_action_activation", "succeeded")]
        parse = by_pair[("evolution_pdf_parse", "failed")]
        for row in (activation, parse):
            assert row.started_at is not None
            assert row.finished_at is not None
            assert row.finished_at >= row.started_at
            # No dynamic payload on substep rows.
            assert row.details_json == {}
        # 'started' is never persisted (the model has no such status).
        assert all(row.status != "started" for row in rows)
        # The chunk commit is materialized after the transaction confirms.
        assert ("evolution_chunk_commit", "succeeded") in by_pair
        # Every stage name belongs to the closed enum or the legacy stages.
        allowed = {substep.value for substep in EvolutionSubstep} | {
            "admissions_capture",
            "gap_planning",
            "evolution_extraction",
            "ingestion_persistence",
        }
        assert {row.stage_name for row in rows} <= allowed


# ===========================================================================
# R6/R7/R8 — aggregate chunk counters in the worker (RED items 8–10)
# ===========================================================================


def _stage_details(run_id: int, stage_name: str, status: str) -> dict[str, Any]:
    row = IngestionRunStageMetric.objects.filter(
        run_id=run_id, stage_name=stage_name, status=status
    ).first()
    assert row is not None, f"missing stage {stage_name}/{status} for run {run_id}"
    return row.details_json


@pytest.mark.django_db
class TestWorkerChunkAggregates:
    """Aggregate counters are integers only, consistent with the run
    counters and the coverage ledger — on success, partial failure, and
    transaction failure."""

    def test_full_success_two_chunks_planned2_committed2_failed0(self) -> None:
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-SUB-A1")
        admission = _admission(
            patient, key="SYN-SUB-ADM-A1",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-SUB-A1",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-29",  # canonical: (01-01..01-15)(01-15..01-29)
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-SUB-ADM-A1", "2024-01-01")],
        )
        calls: list[str] = []

        def extract_side_effect(**kwargs):
            calls.append(kwargs["start_date"])
            happened = (
                "2024-01-05T10:00:00" if len(calls) == 1 else "2024-01-20T10:00:00"
            )
            return [_evolution("SYN-SUB-ADM-A1", happened)]

        adapter.extract_evolutions.side_effect = extract_side_effect
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 2
        assert len(calls) == 2

        extraction = _stage_details(run.pk, "evolution_extraction", "succeeded")
        persistence = _stage_details(run.pk, "ingestion_persistence", "succeeded")
        for details in (extraction, persistence):
            for key in _AGGREGATE_KEYS:
                assert isinstance(details[key], int), key
        assert extraction["chunks_planned"] == 2
        assert extraction["chunks_committed"] == 2
        assert extraction["chunks_failed"] == 0
        assert extraction["events_processed"] == run.events_processed
        assert persistence["chunks_committed"] == 2
        assert persistence["chunks_failed"] == 0
        assert persistence["events_processed"] == run.events_processed
        # Coherent with the ledger: one coverage row per committed chunk.
        assert (
            EvolutionExtractionCoverage.objects.filter(
                admission_id=admission.pk
            ).count()
            == 2
        )
        # One chunk_commit terminal per committed chunk.
        assert (
            IngestionRunStageMetric.objects.filter(
                run_id=run.pk,
                stage_name="evolution_chunk_commit",
                status="succeeded",
            ).count()
            == 2
        )

    def test_partial_failure_committed1_failed1_events_preserved(self) -> None:
        """R6/R8: first chunk commits; second chunk extraction fails — the
        failed aggregate keeps committed=1/failed=1 and the committed events
        survive while the run follows its failure policy."""
        from apps.clinical_docs.models import ClinicalEvent

        patient = _patient("SYN-SUB-A2")
        admission = _admission(
            patient, key="SYN-SUB-ADM-A2",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-SUB-A2",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-29",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-SUB-ADM-A2", "2024-01-01")],
        )
        calls: list[str] = []

        def extract_side_effect(**kwargs):
            calls.append(kwargs["start_date"])
            if len(calls) == 1:
                return [_evolution("SYN-SUB-ADM-A2", "2024-01-05T10:00:00")]
            raise ExtractionError(
                "Evolution flow failed after deadline (sanitized) "
                f"{_SENT_URL} {_SENT_RAW}"
            )

        adapter.extract_evolutions.side_effect = extract_side_effect
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.events_processed == 1

        details = _stage_details(run.pk, "evolution_extraction", "failed")
        assert details["chunks_planned"] == 2
        assert details["chunks_committed"] == 1
        assert details["chunks_failed"] == 1
        assert details["events_processed"] == 1
        # Sanitized error fields remain the only error text.
        assert "error_type" in details and "error_message" in details
        assert ClinicalEvent.objects.count() == 1

    def test_transaction_failure_emits_chunk_commit_failed_without_commit(
        self,
    ) -> None:
        """R7: a failure INSIDE the chunk transaction emits
        ``evolution_chunk_commit: failed`` and ``chunks_committed`` does not
        increment."""
        from apps.clinical_docs.models import ClinicalEvent
        from apps.ingestion.models import EvolutionExtractionCoverage

        patient = _patient("SYN-SUB-A3")
        admission = _admission(
            patient, key="SYN-SUB-ADM-A3",
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key="SYN-SUB-A3",
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-10",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            snapshot_result=[_snapshot_row("SYN-SUB-ADM-A3", "2024-01-01")],
        )
        adapter.extract_evolutions.side_effect = lambda **kwargs: [
            _evolution("SYN-SUB-ADM-A3", "2024-01-05T10:00:00"),
        ]
        with patch(
            f"{_WORKER_MODULE}.EvolutionExtractionCoverage.objects"
            f".update_or_create",
            side_effect=RuntimeError("forced coverage failure"),
        ):
            _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        # The chunk commit substep is materialized as failed — never as a
        # success and never as a persisted 'started' row.
        assert (
            IngestionRunStageMetric.objects.filter(
                run_id=run.pk,
                stage_name="evolution_chunk_commit",
                status="failed",
            ).count()
            == 1
        )
        assert (
            IngestionRunStageMetric.objects.filter(
                run_id=run.pk,
                stage_name="evolution_chunk_commit",
                status="succeeded",
            ).exists()
            is False
        )
        details = _stage_details(run.pk, "ingestion_persistence", "failed")
        assert details["chunks_planned"] == 1
        assert details["chunks_committed"] == 0
        assert details["chunks_failed"] == 1
        assert ClinicalEvent.objects.count() == 0
        assert EvolutionExtractionCoverage.objects.count() == 0


# ===========================================================================
# R9 — sentinel absence across ALL new surfaces (RED item 12)
# ===========================================================================


@pytest.mark.django_db
class TestSentinelAbsence:
    """Distinct sentinels injected into patient record, admission key,
    dates, URL, selector, cookie and raw exception text never reach
    stdout/stderr or any new ``details_json``."""

    def test_sentinels_absent_from_outputs_and_new_details(self, capsys) -> None:
        patient = _patient(_SENT_PAT)
        admission = _admission(
            patient, key=_SENT_KEY,
            start=datetime.datetime(2024, 1, 1),
        )
        run = _queue_targeted_run(
            patient_key=_SENT_PAT,
            admission=admission,
            start_date="2024-01-01",
            end_date="2024-01-29",
            max_attempts=1,
        )
        adapter = _make_adapter_mock(
            # The date sentinel rides the raw exception below (a real date is
            # required here so the admissions capture persists normally).
            snapshot_result=[_snapshot_row(_SENT_KEY, "2024-01-01")],
        )
        calls: list[str] = []
        raw_message = (
            f"{_SENT_DATE} {_SENT_URL} {_SENT_SELECTOR} {_SENT_COOKIE} "
            f"{_SENT_RAW}"
        )

        def extract_side_effect(**kwargs):
            calls.append(kwargs["start_date"])
            if len(calls) == 1:
                # Clinical text also carries a sentinel — it must never leak
                # into telemetry details.
                return [_evolution(_SENT_KEY, "2024-01-05T10:00:00", content=_SENT_RAW)]
            raise ExtractionError(raw_message)

        adapter.extract_evolutions.side_effect = extract_side_effect
        _run_worker(adapter)

        run.refresh_from_db()
        assert run.status == "failed"

        # ALL stage metrics of the run (new surfaces included) are free of
        # every sentinel.
        rows = list(
            IngestionRunStageMetric.objects.filter(run=run).values_list(
                "stage_name", "status", "details_json"
            )
        )
        serialized = json.dumps(rows, default=str)
        for sentinel in _ALL_SENTINELS:
            assert sentinel not in serialized, sentinel

        # The new aggregate surface exists and is integer-only counters.
        failed_details = _stage_details(run.pk, "evolution_extraction", "failed")
        for key in _AGGREGATE_KEYS:
            assert isinstance(failed_details[key], int), key
        assert failed_details["chunks_committed"] == 1
        assert failed_details["chunks_failed"] == 1

        # stdout/stderr carry no sentinel either.
        captured = capsys.readouterr()
        combined = f"{captured.out}{captured.err}"
        for sentinel in _ALL_SENTINELS:
            assert sentinel not in combined, sentinel
