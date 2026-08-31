"""PFIF-S1: persistent empty-admissions encounter fallback (RED first).

Covers the whole vertical slice with synthetic fixtures only — no real
legacy access, no browser, no network:

- R1: pure ``PatientFlowSnapshot`` contract and conservative recency buckets;
- R2: structural ``Atendimentos`` parser helpers in ``legacy_navigation``;
- R3: job-scoped flow snapshot action on the real handle bridge;
- R4: enriched adapter method compatible with ``get_admission_snapshot``;
- R5: persistent worker recognizes a recent encounter (zero clinical effect);
- R6: boundary/stale/none, standalone and full-sync stay fail-closed;
- R7: no sensitive sentinel leaks to outputs, stages or errors.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.legacy_navigation import (
    NavigationError,
    NavigationTimeoutError,
    read_admissions_rows,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
from apps.ingestion.extractors.session_policy import TabCleanupOutcome
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunStageMetric,
)
from apps.patients.models import Admission, Patient
from tests.unit.test_legacy_navigation import (  # noqa: PLC0415
    FakeNavigationFrame,
    FakeNavigationPage,
)
from tests.unit.test_persistent_worker_command import (  # noqa: PLC0415
    _ADMISSION_SNAPSHOT_DATA,
    _EVOLUTION_DATA,
    _make_adapter_mock,
    _queue_admissions_run,
    _queue_full_sync_run,
)

# ---------------------------------------------------------------------------
# Synthetic data (never real patient/clinical values)
# ---------------------------------------------------------------------------

_TODAY = date(2025, 5, 12)

_PROFESSIONAL_SENTINEL = "SENTINEL-PROFESSIONAL-XYZ"
_TYPE_SENTINEL = "SENTINEL-TYPE-XYZ"
_SPECIALTY_SENTINEL = "SENTINEL-SPECIALTY-XYZ"
_RECORD_SENTINEL = "SENTINEL-RECORD-7777"


def _encounter_row(
    date_str: str,
    *,
    n_cells: int = 4,
) -> dict[str, Any]:
    """Build one synthetic ``Atendimentos`` row as read from ``frame_pol``.

    Cells 2-4 carry sentinels so tests can prove that type, specialty and
    professional values never leave the structural parser.
    """
    cells = [date_str, _TYPE_SENTINEL, _SPECIALTY_SENTINEL, _PROFESSIONAL_SENTINEL]
    return {"cells": cells[:n_cells] if n_cells <= 4 else cells}


def _flow_page(
    *,
    admissions_rows: list[dict[str, Any]] | None = None,
    encounter_rows: list[dict[str, Any]] | None = None,
    atendimentos_visible: bool = True,
) -> FakeNavigationPage:
    """Build a fake legacy page with ``frame_pol`` serving both tables.

    Models the production topology: both tables live ONLY inside
    ``frame_pol``; the top-level page never contains them.
    """
    page = FakeNavigationPage()
    page.make_selector_visible("#prontuarioInput")
    page.make_selector_visible("role:link:Pesquisa Avançada")
    page.make_selector_visible("text:Internações")
    if atendimentos_visible:
        page.make_selector_visible("text:Atendimentos")
    frame = FakeNavigationFrame()
    frame.set_eval_result(
        "#tabelaInternacoes\\:resultList_data > tr", admissions_rows or []
    )
    if encounter_rows is not None:
        frame.set_eval_result(
            "#tabela_resultados\\:resultList_data > tr", encounter_rows
        )
    page.set_frame(frame)
    return page


def _admissions_iframe_row(start: str = "15/01/2024") -> dict[str, Any]:
    """Build one synthetic internações row (admissions capture path)."""
    return {
        "dataRi": "0",
        "dataRk": "RK-SYNTH-001",
        "cells": [start, "20/01/2024", "Setor Sintético", "Leito 0"],
        "hasDetailsLink": True,
    }


# ===========================================================================
# R1 — Pure contract: recency buckets and value object
# ===========================================================================


class TestEncounterRecencyBuckets:
    """D3: date-only evidence yields conservative closed buckets."""

    def test_missing_date_is_none(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        assert (
            classify_encounter_recency(None, today=_TODAY).value == "none"
        )

    def test_today_is_recent_confirmed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        assert (
            classify_encounter_recency(_TODAY, today=_TODAY).value
            == "recent_confirmed"
        )

    def test_yesterday_is_recent_confirmed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        assert (
            classify_encounter_recency(
                date(2025, 5, 11), today=_TODAY
            ).value
            == "recent_confirmed"
        )

    def test_day_before_yesterday_is_boundary_never_accepted(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        recency = classify_encounter_recency(date(2025, 5, 10), today=_TODAY)
        assert recency.value == "boundary"
        assert recency.value != "recent_confirmed"

    def test_three_days_old_is_stale(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        assert (
            classify_encounter_recency(date(2025, 5, 9), today=_TODAY).value
            == "stale"
        )

    def test_far_past_is_stale(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        assert (
            classify_encounter_recency(date(2024, 1, 1), today=_TODAY).value
            == "stale"
        )

    def test_future_date_is_never_recent(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            classify_encounter_recency,
        )

        recency = classify_encounter_recency(date(2025, 5, 13), today=_TODAY)
        assert recency.value == "none"
        assert recency.value != "recent_confirmed"


class TestPatientFlowSnapshotContract:
    """R1: immutable value object with normalized admissions and max date."""

    def test_build_picks_latest_date_deterministically(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        flow = PatientFlowSnapshot.build(
            admissions=[],
            encounter_dates=[date(2025, 5, 9), date(2025, 5, 11), date(2025, 5, 10)],
            today=_TODAY,
        )
        assert flow.latest_encounter_date == date(2025, 5, 11)
        assert flow.encounter_recency.value == "recent_confirmed"

    def test_build_without_dates_is_none_recency(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        flow = PatientFlowSnapshot.build(
            admissions=[], encounter_dates=[], today=_TODAY
        )
        assert flow.latest_encounter_date is None
        assert flow.encounter_recency.value == "none"
        assert flow.has_recent_encounter is False
        assert flow.is_empty is True

    def test_build_normalizes_admissions_to_immutable_tuple(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        admission = {"admission_key": "K-1", "admission_start": "2025-05-01"}
        flow = PatientFlowSnapshot.build(
            admissions=[admission], encounter_dates=[], today=_TODAY
        )
        assert isinstance(flow.admissions, tuple)
        assert flow.admissions[0]["admission_key"] == "K-1"
        assert flow.is_empty is False

    def test_value_object_is_frozen(self) -> None:
        import dataclasses

        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        flow = PatientFlowSnapshot.build(
            admissions=[], encounter_dates=[_TODAY], today=_TODAY
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            # ``()`` is type-correct for the tuple field: only the frozen
            # contract can reject this assignment.
            flow.admissions = ()  # type: ignore[misc]

    def test_has_recent_encounter_true_only_for_recent(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        recent = PatientFlowSnapshot.build(
            admissions=[], encounter_dates=[date(2025, 5, 11)], today=_TODAY
        )
        boundary = PatientFlowSnapshot.build(
            admissions=[], encounter_dates=[date(2025, 5, 10)], today=_TODAY
        )
        assert recent.has_recent_encounter is True
        assert boundary.has_recent_encounter is False


# ===========================================================================
# R2 — Structural parser helpers (legacy_navigation)
# ===========================================================================


class TestEncounterTableParsing:
    """Structural read: four cells, first cell DD/MM/AAAA, deterministic."""

    def test_reads_and_sorts_valid_dates_ignoring_invalid_rows(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            read_encounter_dates,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        frame.set_eval_result(
            "#tabela_resultados\\:resultList_data > tr",
            [
                _encounter_row("12/05/2025"),
                _encounter_row("10/05/2025"),
                _encounter_row("99/99/2025"),  # invalid date -> ignored
                _encounter_row("11/05/2025", n_cells=3),  # short row -> ignored
                _encounter_row("11/05/2025"),  # valid four-cell row
            ],
        )
        page.set_frame(frame)

        dates = read_encounter_dates(page)

        assert dates == [date(2025, 5, 10), date(2025, 5, 11), date(2025, 5, 12)]
        # No cell value other than the first (date) may survive parsing.
        assert _PROFESSIONAL_SENTINEL not in str(dates)
        assert _TYPE_SENTINEL not in str(dates)
        assert _SPECIALTY_SENTINEL not in str(dates)

    def test_no_frame_yields_no_dates(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            read_encounter_dates,
        )

        page = FakeNavigationPage()  # no frame set
        assert read_encounter_dates(page) == []

    def test_click_atendimentos_uses_exact_visible_item(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            click_atendimentos,
        )

        page = _flow_page()
        click_atendimentos(page)
        assert "Atendimentos" in page.text_calls
        assert page.click_timeouts  # bounded click happened

    def test_click_atendimentos_missing_menu_is_sanitized(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            click_atendimentos,
        )

        page = FakeNavigationPage()  # nothing visible
        with pytest.raises(NavigationError) as excinfo:
            click_atendimentos(page)
        assert "Atendimentos" in str(excinfo.value)
        assert _RECORD_SENTINEL not in str(excinfo.value)

    def test_wait_for_encounters_table_returns_frame(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            wait_for_encounters_table,
        )

        page = _flow_page(encounter_rows=[_encounter_row("11/05/2025")])
        frame = wait_for_encounters_table(page, timeout_ms=2000)
        assert frame is not None
        assert "frame_pol" in page.frame_name_calls

    def test_wait_for_encounters_table_times_out_typed(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            wait_for_encounters_table,
        )

        page = FakeNavigationPage()  # no frame at all
        with pytest.raises(NavigationTimeoutError):
            wait_for_encounters_table(page, timeout_ms=200)

    def test_admissions_rows_reader_unchanged(self) -> None:
        """Compat guard: the internações reader keeps its contract."""
        page = _flow_page(admissions_rows=[_admissions_iframe_row()])
        rows = read_admissions_rows(page)
        assert len(rows) == 1
        assert rows[0]["admissionKey"] == "RK-SYNTH-001"


# ===========================================================================
# R3 — Bridge job-scoped flow snapshot action
# ===========================================================================


class TestBridgeFlowSnapshotAction:
    """The bridge captures admissions first; encounters only when empty."""

    def _bridge(self, page: FakeNavigationPage) -> RealHandleBridge:
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        return RealHandleBridge(RealisticPersistentHandle(page=page))

    def test_empty_admissions_with_recent_encounter_is_recognized(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        page = _flow_page(
            admissions_rows=[],
            encounter_rows=[_encounter_row("11/05/2025")],
        )
        bridge = self._bridge(page)

        flow = bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert flow.admissions == ()
        assert flow.encounter_recency is EncounterRecency.RECENT_CONFIRMED
        assert flow.latest_encounter_date == date(2025, 5, 11)
        # Exactly one Atendimentos click happened, after internações.
        assert page.text_calls == ["Internações", "Atendimentos"]

    def test_nonempty_admissions_never_click_atendimentos(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        page = _flow_page(
            admissions_rows=[_admissions_iframe_row()],
            encounter_rows=[_encounter_row("11/05/2025")],
        )
        bridge = self._bridge(page)

        flow = bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert len(flow.admissions) == 1
        assert flow.encounter_recency is EncounterRecency.NONE
        assert "Atendimentos" not in page.text_calls

    def test_empty_admissions_without_dates_is_fail_closed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        page = _flow_page(admissions_rows=[], encounter_rows=[])
        bridge = self._bridge(page)

        flow = bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert flow.encounter_recency is EncounterRecency.NONE

    def test_boundary_encounter_is_not_recent(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        page = _flow_page(
            admissions_rows=[],
            encounter_rows=[_encounter_row("10/05/2025")],
        )
        bridge = self._bridge(page)

        flow = bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert flow.encounter_recency is EncounterRecency.BOUNDARY

    def test_no_active_page_raises_sanitized_error(self) -> None:
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        bridge = RealHandleBridge(RealisticPersistentHandle(page=None))
        with pytest.raises(NavigationError) as excinfo:
            bridge.capture_patient_flow_snapshot(
                patient_record=_RECORD_SENTINEL, today=_TODAY
            )
        message = str(excinfo.value)
        assert _RECORD_SENTINEL not in message
        assert "frame_pol" not in message

    def test_no_new_browser_tab_or_url_is_opened(self) -> None:
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        handle_calls: list[str] = []
        handle = RealisticPersistentHandle(
            page=_flow_page(admissions_rows=[])
        )
        original_open = handle.open_tab

        def _spy_open(url: str, *, timeout: int = 120) -> bool:
            handle_calls.append(url)
            return original_open(url, timeout=timeout)

        handle.open_tab = _spy_open  # type: ignore[method-assign]
        bridge = RealHandleBridge(handle)

        bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert handle_calls == []


class TestBridgeFlowLifecycleCache:
    """No encounter/admissions state may cross a lifecycle boundary."""

    def test_flow_action_starts_from_clean_job_state(self) -> None:
        handle = _flow_page(admissions_rows=[])
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        bridge = RealHandleBridge(RealisticPersistentHandle(page=handle))
        # Simulate a previous job's admissions snapshot still in memory.
        bridge._admissions_snapshot_html = "<div>PREVIOUS-PATIENT</div>"

        bridge.capture_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert bridge._admissions_snapshot_html is None

    def _bridge_with_previous_snapshot(
        self,
    ) -> tuple[RealHandleBridge, str]:
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        page = _flow_page(admissions_rows=[_admissions_iframe_row()])
        bridge = RealHandleBridge(RealisticPersistentHandle(page=page))
        assert bridge.navigate_to_admissions(patient_record="PAT-A") is True
        html = bridge.get_page_html()
        assert "RK-SYNTH-001" in html
        return bridge, html

    def test_close_last_tab_clears_cache(self) -> None:
        bridge, _ = self._bridge_with_previous_snapshot()
        bridge.close_last_non_root_tab()
        assert bridge._admissions_snapshot_html is None

    def test_restart_clears_cache(self) -> None:
        bridge, _ = self._bridge_with_previous_snapshot()
        bridge.restart_browser()
        assert bridge._admissions_snapshot_html is None

    def test_bootstrap_clears_cache(self) -> None:
        bridge, _ = self._bridge_with_previous_snapshot()
        with suppress(Exception):
            # bootstrap may fail on synthetic credentials; the cache must be
            # dropped BEFORE any bootstrap action regardless of the outcome.
            bridge.bootstrap()
        assert bridge._admissions_snapshot_html is None

    def test_shutdown_clears_cache(self) -> None:
        bridge, _ = self._bridge_with_previous_snapshot()
        bridge.shutdown()
        assert bridge._admissions_snapshot_html is None


# ===========================================================================
# R4 — Adapter enriched method
# ===========================================================================


class _StubSessionHandle:
    """Minimal stub session WITHOUT the flow snapshot capability."""

    def __init__(self) -> None:
        self.opened_urls: list[str] = []

    def get_page_html(self) -> str:
        return ""

    def is_connected(self) -> bool:
        return True

    def click_selector(self, selector: str) -> None:
        return None

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        self.opened_urls.append(url)
        return True

    def get_tab_classes(self) -> list[str]:
        return ["tabs-first tabs-last tabs-selected"]

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        return TabCleanupOutcome.ROOT_ONLY

    def restart_browser(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class TestAdapterFlowSnapshot:
    """get_patient_flow_snapshot enriches without breaking the old API."""

    def test_stub_without_capability_stays_fail_closed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        stub = _StubSessionHandle()
        adapter = PersistentExtractionAdapter(stub)

        flow = adapter.get_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )

        assert flow.encounter_recency is EncounterRecency.NONE
        assert flow.admissions == ()
        assert stub.opened_urls == []  # no new URL opened

    def test_bridge_path_returns_snapshot_and_job_counted_once(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            EncounterRecency,
        )

        page = _flow_page(
            admissions_rows=[],
            encounter_rows=[_encounter_row("11/05/2025")],
        )
        from tests.unit.test_real_handle_bridge import (  # noqa: PLC0415
            RealisticPersistentHandle,
        )

        adapter = PersistentExtractionAdapter(
            RealHandleBridge(RealisticPersistentHandle(page=page))
        )
        adapter._controller = MagicMock()

        snapshot = adapter.get_admission_snapshot(
            patient_record=_RECORD_SENTINEL,
            start_date="2025-01-01",
            end_date="2025-05-12",
        )
        assert snapshot == []  # old API contract unchanged

        flow = adapter.get_patient_flow_snapshot(
            patient_record=_RECORD_SENTINEL, today=_TODAY
        )
        assert flow.encounter_recency is EncounterRecency.RECENT_CONFIRMED

        # Readiness/renewal/cleanup/mark occur ONCE per job: the fallback
        # must not add an extra mark_job_processed.
        assert adapter._controller.mark_job_processed.call_count == 1


# ===========================================================================
# R5 — Worker recognition of a recent encounter
# ===========================================================================

_WORKER_MODULE = (
    "apps.ingestion.management.commands"
    ".process_ingestion_runs_persistent_session"
)


def _recent_flow() -> Any:
    from apps.ingestion.extractors.patient_flow_snapshot import (
        PatientFlowSnapshot,
    )

    return PatientFlowSnapshot.build(
        admissions=[],
        encounter_dates=[timezone.localdate()],
        today=timezone.localdate(),
    )


def _run_persistent_worker(mock_adapter: MagicMock) -> None:
    with patch.object(
        _worker_command(), "_create_adapter", return_value=mock_adapter
    ):
        call_command("process_ingestion_runs_persistent_session")


def _worker_command() -> type:
    from apps.ingestion.management.commands import (
        process_ingestion_runs_persistent_session as module,
    )

    return module.Command


@pytest.mark.django_db
class TestWorkerRecognizedRecentEncounter:
    """Empty batch-bound admissions + today/yesterday encounter succeeds."""

    def test_recent_encounter_run_succeeds_with_zero_clinical_effect(
        self,
    ) -> None:
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _queue_admissions_run(
            batch=batch,
            parameters_json={
                "patient_record": "PF-S1",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = _recent_flow()

        with patch(
            f"{_WORKER_MODULE}.persist_admissions_snapshot"
        ) as persist_mock, patch(
            f"{_WORKER_MODULE}.enqueue_most_recent_admission_full_sync"
        ) as fullsync_mock, patch(
            f"{_WORKER_MODULE}.queue_demographics_only_run"
        ) as demo_mock:
            _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.admissions_seen == 0
        assert run.admissions_created == 0
        assert run.admissions_updated == 0
        assert run.events_processed == 0
        assert run.events_created == 0
        assert run.events_skipped == 0
        assert run.events_revised == 0

        # Zero persistence and zero follow-ups.
        persist_mock.assert_not_called()
        fullsync_mock.assert_not_called()
        demo_mock.assert_not_called()
        assert Patient.objects.count() == 0
        assert Admission.objects.count() == 0
        assert not IngestionRun.objects.filter(intent="full_sync").exists()

        # Attempt succeeded.
        from apps.ingestion.models import IngestionRunAttempt

        attempt = IngestionRunAttempt.objects.filter(run=run).first()
        assert attempt is not None
        assert attempt.status == "succeeded"

        # Stage metrics: admissions_capture + allowlisted encounter_fallback.
        stages = {
            s.stage_name: s
            for s in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages["admissions_capture"].status == "succeeded"
        fallback_stage = stages["encounter_fallback"]
        assert fallback_stage.status == "succeeded"
        assert fallback_stage.details_json == {
            "outcome": "recent_encounter_without_admission",
            "recency": "recent_confirmed",
        }

        # Batch drains.
        batch.refresh_from_db()
        assert batch.status == "succeeded"
        assert batch.finished_at is not None

        # Fallback consulted exactly once.
        mock_adapter.get_patient_flow_snapshot.assert_called_once()

    def test_fallback_receives_local_today(self) -> None:
        run = _queue_admissions_run(
            batch=CensusExecutionBatch.objects.create(status="running"),
            parameters_json={
                "patient_record": "PF-S1B",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = _recent_flow()
        _run_persistent_worker(mock_adapter)

        kwargs = mock_adapter.get_patient_flow_snapshot.call_args.kwargs
        assert kwargs["today"] == timezone.localdate()
        run.refresh_from_db()
        assert run.status == "succeeded"


# ===========================================================================
# R6 — Fail-closed preserved
# ===========================================================================


@pytest.mark.django_db
class TestWorkerFallbackFailClosed:
    """Boundary/stale/none and navigation failures keep the failure path."""

    def _boundary_flow(self) -> Any:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        return PatientFlowSnapshot.build(
            admissions=[],
            encounter_dates=[timezone.localdate() - timedelta(days=2)],
            today=timezone.localdate(),
        )

    def test_boundary_encounter_fails_closed(self) -> None:
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _queue_admissions_run(
            max_attempts=3,
            batch=batch,
            parameters_json={
                "patient_record": "PF-S1C",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = (
            self._boundary_flow()
        )
        _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        mock_adapter.cleanup_after_failure.assert_called_once()
        batch.refresh_from_db()
        assert batch.status == "failed"

        stages = {
            s.stage_name: s
            for s in IngestionRunStageMetric.objects.filter(run=run)
        }
        assert stages["admissions_capture"].status == "failed"
        assert "encounter_fallback" not in stages

    def test_stale_encounter_fails_closed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        run = _queue_admissions_run(
            batch=CensusExecutionBatch.objects.create(status="running"),
            parameters_json={
                "patient_record": "PF-S1D",
                "intent": "admissions_only",
            },
        )
        stale = PatientFlowSnapshot.build(
            admissions=[],
            encounter_dates=[timezone.localdate() - timedelta(days=30)],
            today=timezone.localdate(),
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = stale
        _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        mock_adapter.cleanup_after_failure.assert_called_once()

    def test_none_encounter_fails_closed(self) -> None:
        from apps.ingestion.extractors.patient_flow_snapshot import (
            PatientFlowSnapshot,
        )

        run = _queue_admissions_run(
            batch=CensusExecutionBatch.objects.create(status="running"),
            parameters_json={
                "patient_record": "PF-S1E",
                "intent": "admissions_only",
            },
        )
        none_flow = PatientFlowSnapshot.build(
            admissions=[], encounter_dates=[], today=timezone.localdate()
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = none_flow
        _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"

    def test_fallback_navigation_failure_keeps_retry_taxonomy(self) -> None:
        run = _queue_admissions_run(
            max_attempts=2,
            batch=CensusExecutionBatch.objects.create(status="running"),
            parameters_json={
                "patient_record": "PF-S1F",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.side_effect = ExtractionError(
            "Failed to capture the patient flow snapshot via legacy actions."
        )
        _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        assert run.failure_reason == "source_unavailable"
        assert run.status == "queued"  # retryable: requeued with backoff
        mock_adapter.cleanup_after_failure.assert_called_once()

    def test_standalone_empty_capture_does_not_trigger_fallback(self) -> None:
        run = _queue_admissions_run()  # batch_id is None
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        _run_persistent_worker(mock_adapter)

        mock_adapter.get_patient_flow_snapshot.assert_not_called()
        run.refresh_from_db()
        assert run.status == "succeeded"  # standalone empty stays valid

    def test_full_sync_does_not_trigger_fallback(self) -> None:
        run = _queue_full_sync_run()
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        mock_adapter.extract_evolutions.return_value = _EVOLUTION_DATA
        _run_persistent_worker(mock_adapter)

        mock_adapter.get_patient_flow_snapshot.assert_not_called()
        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_nonempty_snapshot_does_not_trigger_fallback(self) -> None:
        run = _queue_admissions_run(
            batch=CensusExecutionBatch.objects.create(status="running"),
            parameters_json={
                "patient_record": "PF-S1G",
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_ADMISSION_SNAPSHOT_DATA)
        with patch(
            f"{_WORKER_MODULE}.enqueue_most_recent_admission_full_sync"
        ), patch(f"{_WORKER_MODULE}.queue_demographics_only_run"):
            _run_persistent_worker(mock_adapter)

        mock_adapter.get_patient_flow_snapshot.assert_not_called()
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 1


# ===========================================================================
# R7 — Privacy sentinels
# ===========================================================================


@pytest.mark.django_db
class TestPrivacySentinels:
    """No professional/type/specialty/record sentinel may reach outputs."""

    def test_recognized_run_emits_no_sensitive_sentinel(self, capsys) -> None:
        batch = CensusExecutionBatch.objects.create(status="running")
        run = _queue_admissions_run(
            batch=batch,
            parameters_json={
                "patient_record": _RECORD_SENTINEL,
                "intent": "admissions_only",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=[])
        mock_adapter.get_patient_flow_snapshot.return_value = _recent_flow()
        _run_persistent_worker(mock_adapter)

        run.refresh_from_db()
        captured = capsys.readouterr()
        assert _RECORD_SENTINEL not in captured.out
        assert _RECORD_SENTINEL not in captured.err
        assert _PROFESSIONAL_SENTINEL not in captured.out
        assert _PROFESSIONAL_SENTINEL not in captured.err

        for stage in IngestionRunStageMetric.objects.filter(run=run):
            payload = json.dumps(stage.details_json, default=str)
            assert _RECORD_SENTINEL not in payload
            assert _PROFESSIONAL_SENTINEL not in payload
            assert _TYPE_SENTINEL not in payload
            assert _SPECIALTY_SENTINEL not in payload
        assert run.error_message == ""

    def test_bridge_parser_output_has_no_row_text(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            read_encounter_dates,
        )

        page = _flow_page(
            admissions_rows=[],
            encounter_rows=[
                _encounter_row("11/05/2025"),
                _encounter_row("10/05/2025"),
            ],
        )
        dates = read_encounter_dates(page)
        rendered = repr(dates)
        for sentinel in (
            _PROFESSIONAL_SENTINEL,
            _TYPE_SENTINEL,
            _SPECIALTY_SENTINEL,
        ):
            assert sentinel not in rendered
