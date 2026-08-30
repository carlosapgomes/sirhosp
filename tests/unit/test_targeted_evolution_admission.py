"""HTEFS-S2 — strict targeted-admission selection (consolidated).

Covers the targeted ``full_sync`` flow end to end without any real browser,
network, or legacy access:

- pure selector ``select_target_admission`` (stable period/state facts; the
  legacy source key is ONLY a tie-break hint);
- ``open_internacao_detail(strict=True)`` (no first-row fallback in targeted
  mode; legacy mode preserved);
- adapter propagation of the named target context to the real action method
  (stub dispatch unchanged);
- bridge targeted extraction (single compatible admission; required-action
  failures propagate as typed sanitized errors — never an empty list);
- worker resolution of ``admission_id`` against the persisted patient
  (foreign/unknown/undatable admissions fail closed before extraction).

All identifiers and dates are clearly synthetic (``SYNTH-*`` / ``SYN-*``).
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone as dj_timezone

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.legacy_navigation import (
    SEL_DETAILS_LINK,
    SEL_INTERNACOES_TABLE_BODY,
    SEL_INTERNACOES_TABLE_ROWS,
    NavigationError,
    choose_overlapping_admissions,
    open_internacao_detail,
)
from apps.ingestion.extractors.persistent_evolution_pdf import EvolutionPdfError
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
from apps.ingestion.extractors.session_controller import SessionControllerConfig
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
    Command as PersistentWorkerCommand,
)
from apps.patients.models import Admission, Patient
from tests.unit.test_legacy_navigation import (
    FakeNavigationFrame,
    FakeNavigationPage,
)
from tests.unit.test_persistent_extraction_adapter import FakeExtractionSession
from tests.unit.test_persistent_worker_command import (
    _make_adapter_mock,
    _queue_full_sync_run,
)
from tests.unit.test_real_handle_bridge import FakePlaywrightHandle

_SESSION_COUNTER_HTML = (
    '<div id="tempoSessao" class="tempo-sessao">'
    "Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>"
    "</div>"
)


def _row(key: str, start: str, end: str = "") -> dict[str, str]:
    """Build a canonical-snapshot admission row (ISO dates, SYNTH ids)."""
    return {
        "admissionKey": key,
        "admissionStart": start,
        "admissionEnd": end,
        "ward": "SYN-WARD",
        "bed": "SYN-BED",
    }


def _target_context(**overrides: Any) -> Any:
    """Build the named target context (imports the HTEFS-S2 type)."""
    from apps.ingestion.extractors.legacy_navigation import (  # noqa: PLC0415
        TargetAdmissionContext,
    )

    kwargs: dict[str, Any] = {
        "start_date": "2024-03-01",
        "end_date": "",
        "is_active": True,
        "source_admission_key": "",
    }
    kwargs.update(overrides)
    return TargetAdmissionContext(**kwargs)


def _select_rows(
    rows: list[dict[str, str]],
    *,
    requested_start: str,
    requested_end: str,
    target: Any,
) -> dict[str, str]:
    """Invoke the pure selector (imports the HTEFS-S2 function)."""
    from apps.ingestion.extractors.legacy_navigation import (  # noqa: PLC0415
        select_target_admission,
    )

    return select_target_admission(
        rows,
        requested_start=requested_start,
        requested_end=requested_end,
        target=target,
    )


# ===========================================================================
# Pure selector (R3/R4/R5)
# ===========================================================================


class TestSelectTargetAdmission:
    """Pure selection of the legacy row compatible with the local target.

    Selection order: overlap with the requested window, start equal to the
    local start, state compatibility (active -> open row; closed -> equal
    end), then the source-key hint may only tie-break already-compatible
    candidates. Zero or residual ambiguity fails closed with constant
    sanitized messages.
    """

    def test_active_target_is_unique_selection_among_overlapping(self) -> None:
        """R3: two overlapping rows — the active target's start selects only
        the compatible open row; the older closed row is never chosen."""
        rows = [
            _row("SYN-RK-OLD", "2024-01-01", "2024-01-10"),
            _row("SYN-RK-CUR", "2024-02-01"),
        ]
        target = _target_context(start_date="2024-02-01")

        selected = _select_rows(
            rows,
            requested_start="2024-01-05",
            requested_end="2024-02-15",
            target=target,
        )

        assert selected["admissionKey"] == "SYN-RK-CUR"

    def test_stale_key_unique_stable_match_accepted(self) -> None:
        """R4: a stale local source key never defeats a unique period/state
        match — the row is accepted by stable facts alone."""
        rows = [_row("SYN-RK-CURRENT", "2024-03-01", "2024-03-20")]
        target = _target_context(
            start_date="2024-03-01",
            end_date="2024-03-20",
            is_active=False,
            source_admission_key="SYN-RK-STALE",
        )

        selected = _select_rows(
            rows,
            requested_start="2024-03-01",
            requested_end="2024-03-20",
            target=target,
        )

        assert selected["admissionKey"] == "SYN-RK-CURRENT"

    def test_compatible_hint_tie_breaks_stable_matches(self) -> None:
        """R3: two stable-compatible rows — a hint matching exactly one of
        them selects the hinted compatible row."""
        rows = [
            _row("SYN-RK-OTHER", "2024-03-01", "2024-03-20"),
            _row("SYN-RK-HINTED", "2024-03-01", "2024-03-20"),
        ]
        target = _target_context(
            start_date="2024-03-01",
            end_date="2024-03-20",
            is_active=False,
            source_admission_key="SYN-RK-HINTED",
        )

        selected = _select_rows(
            rows,
            requested_start="2024-03-01",
            requested_end="2024-03-20",
            target=target,
        )

        assert selected["admissionKey"] == "SYN-RK-HINTED"

    def test_incompatible_hinted_candidate_never_selected(self) -> None:
        """R4: the hint points at a row with an incompatible period — the
        hint must NOT authorize it; the compatible row is the unique match."""
        rows = [
            _row("SYN-RK-INCOMPAT", "2024-02-01", "2024-02-20"),
            _row("SYN-RK-COMPAT", "2024-03-01", "2024-03-20"),
        ]
        target = _target_context(
            start_date="2024-03-01",
            end_date="2024-03-20",
            is_active=False,
            source_admission_key="SYN-RK-INCOMPAT",
        )

        selected = _select_rows(
            rows,
            requested_start="2024-02-01",
            requested_end="2024-03-20",
            target=target,
        )

        assert selected["admissionKey"] == "SYN-RK-COMPAT"

    def test_active_state_hint_never_resolves_closed_candidate(self) -> None:
        """R4: an active local target — a hint on a closed row must not
        override the open-state compatibility rule."""
        rows = [
            _row("SYN-RK-OPEN", "2024-03-01"),
            _row("SYN-RK-CLOSED-HINT", "2024-03-01", "2024-03-20"),
        ]
        target = _target_context(source_admission_key="SYN-RK-CLOSED-HINT")

        selected = _select_rows(
            rows,
            requested_start="2024-03-01",
            requested_end="2024-03-20",
            target=target,
        )

        assert selected["admissionKey"] == "SYN-RK-OPEN"

    def test_zero_compatible_raises_constant_sanitized(self) -> None:
        """R5: no compatible row fails closed with the constant message; no
        key, date, or other received value leaks into the error."""
        rows = [_row("SYN-RK-A", "2024-05-01", "2024-05-10")]
        target = _target_context(source_admission_key="SYN-RK-A")

        with pytest.raises(NavigationError) as exc_info:
            _select_rows(
                rows,
                requested_start="2024-03-01",
                requested_end="2024-03-20",
                target=target,
            )

        message = str(exc_info.value)
        for sentinel in ("SYN-RK-A", "2024-03-01", "2024-05-01"):
            assert sentinel not in message

    def test_zero_candidates_at_all_raises_constant_sanitized(self) -> None:
        """R5: an empty legacy table fails closed (no index error, no
        first-row behavior)."""
        target = _target_context()

        with pytest.raises(NavigationError):
            _select_rows(
                [],
                requested_start="2024-03-01",
                requested_end="2024-03-20",
                target=target,
            )

    def test_residual_ambiguity_raises_constant_sanitized(self) -> None:
        """R5: two stable-compatible rows and no resolvable hint fail closed
        with the constant ambiguous message — never first/recent row."""
        rows = [
            _row("SYN-RK-A", "2024-03-01", "2024-03-20"),
            _row("SYN-RK-B", "2024-03-01", "2024-03-20"),
        ]
        target = _target_context(
            end_date="2024-03-20",
            is_active=False,
        )

        with pytest.raises(NavigationError) as exc_info:
            _select_rows(
                rows,
                requested_start="2024-03-01",
                requested_end="2024-03-20",
                target=target,
            )

        message = str(exc_info.value)
        for sentinel in ("SYN-RK-A", "SYN-RK-B", "2024-03-01"):
            assert sentinel not in message

    def test_non_matching_hint_keeps_ambiguity_fail_closed(self) -> None:
        """R5: a hint that matches none of the compatible rows does not
        break the tie — residual ambiguity still fails closed."""
        rows = [
            _row("SYN-RK-A", "2024-03-01", "2024-03-20"),
            _row("SYN-RK-B", "2024-03-01", "2024-03-20"),
        ]
        target = _target_context(
            end_date="2024-03-20",
            is_active=False,
            source_admission_key="SYN-RK-UNRELATED",
        )

        with pytest.raises(NavigationError):
            _select_rows(
                rows,
                requested_start="2024-03-01",
                requested_end="2024-03-20",
                target=target,
            )


# ===========================================================================
# Strict detail opening (R6)
# ===========================================================================


class TestOpenInternacaoDetailStrict:
    """``open_internacao_detail(strict=True)`` forbids the first-row
    fallback; the default mode preserves the existing fallback."""

    def test_strict_mode_never_requests_first_row_locator(self) -> None:
        """R6: when the keyed row is absent, strict mode raises sanitized
        WITHOUT ever locating the first-row-with-details fallback."""
        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        page.set_frame(frame)

        with pytest.raises(NavigationError) as exc_info:
            open_internacao_detail(
                page,
                admission_key="SYN-RK-MISSING",
                strict=True,
            )

        message = str(exc_info.value)
        assert "SYN-RK-MISSING" not in message
        fallback_selector = (
            f"{SEL_INTERNACOES_TABLE_ROWS}:has({SEL_DETAILS_LINK})"
        )
        assert fallback_selector not in frame._locator_calls
        # Only the keyed row selector was ever requested.
        keyed_selector = (
            f"{SEL_INTERNACOES_TABLE_BODY} > tr[data-rk=\"SYN-RK-MISSING\"]"
        )
        assert frame._locator_calls == [keyed_selector]

    def test_default_mode_preserves_first_row_fallback(self) -> None:
        """R6/R8: default mode keeps the first-row fallback path — the
        fallback locator is requested when the keyed row is absent."""
        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        fallback_selector = (
            f"{SEL_INTERNACOES_TABLE_ROWS}:has({SEL_DETAILS_LINK})"
        )
        keyed_selector = (
            f"{SEL_INTERNACOES_TABLE_BODY} > tr[data-rk=\"SYN-RK-KEY\"]"
        )
        details_selector = f"{keyed_selector} {SEL_DETAILS_LINK}"
        frame.make_selector_visible(fallback_selector)
        frame.make_selector_visible(details_selector)
        page.set_frame(frame)

        open_internacao_detail(page, admission_key="SYN-RK-KEY")

        assert fallback_selector in frame._locator_calls


# ===========================================================================
# Adapter dispatch (R2/R8)
# ===========================================================================


_EVOLUTION_CONTAINER_HTML = (
    "<html><body>"
    '<div id="evolution-data">'
    "[{\"admission_key\": \"SYN-RK-1\", \"happened_at\": "
    "\"2024-02-10T09:00:00\", \"event_type\": \"medical\", "
    "\"content\": \"SYNTH evolution content\", \"profession\": \"Dr Synth\"}]"
    "</div>"
    "</body></html>"
)


class TestAdapterTargetContext:
    """The adapter propagates the named target context to the REAL action
    method and keeps the legacy/stub dispatch contracts unchanged."""

    def _bridge_with_spied_action(self) -> tuple[RealHandleBridge, MagicMock]:
        handle = FakePlaywrightHandle()
        handle.set_html(_SESSION_COUNTER_HTML)
        bridge = RealHandleBridge(handle)
        return bridge, MagicMock(return_value=[])

    def test_adapter_passes_target_context_to_real_action_method(self) -> None:
        """R2: a targeted run forwards the exact named context object."""
        bridge, action = self._bridge_with_spied_action()
        target = _target_context(source_admission_key="SYN-RK-HINT",
                                 start_date="2024-02-01")
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )

        with patch.object(
            bridge,
            "extract_evolutions_via_legacy_actions",
            action,
        ):
            adapter.extract_evolutions(
                patient_record="SYN-PR-1",
                start_date="2024-02-01",
                end_date="2024-02-15",
                timeout=33,
                target_admission=target,
            )

        action.assert_called_once_with(
            patient_record="SYN-PR-1",
            start_date="2024-02-01",
            end_date="2024-02-15",
            timeout=33,
            target_admission=target,
        )

    def test_adapter_dispatch_without_target_unchanged(self) -> None:
        """R8: a run without target keeps the EXACT legacy action kwargs."""
        bridge, action = self._bridge_with_spied_action()
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )

        with patch.object(
            bridge,
            "extract_evolutions_via_legacy_actions",
            action,
        ):
            adapter.extract_evolutions(
                patient_record="SYN-PR-1",
                start_date="2024-01-01",
                end_date="2024-01-31",
                timeout=33,
            )

        action.assert_called_once_with(
            patient_record="SYN-PR-1",
            start_date="2024-01-01",
            end_date="2024-01-31",
            timeout=33,
        )

    def test_stub_path_accepts_target_argument_without_change(self) -> None:
        """R8: the stub URL/container path keeps working when a target is
        passed — the target does not alter stub dispatch."""
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
            start_date="2024-02-01",
            end_date="2024-02-15",
            target_admission=_target_context(
                start_date="2024-02-01",
                source_admission_key="SYN-RK-1",
            ),
        )

        assert isinstance(result, list)
        assert result[0]["admission_key"] == "SYN-RK-1"


# ===========================================================================
# Bridge targeted extraction (R1..R5 bridge-level, R7, R8/R10)
# ===========================================================================


class TestBridgeTargetedExtraction:
    """Targeted extraction through the bridge action flow (all nav helpers
    patched — no Playwright, no network)."""

    _BASE = "apps.ingestion.extractors.real_handle_bridge"

    def _run_flow(
        self,
        *,
        snapshot: list[dict[str, str]],
        target: Any = None,
        report_ready: list[bool] | None = None,
        click_evolucao_side_effect: Exception | None = None,
        download_side_effect: Exception | None = None,
        start_date: str = "2024-01-05",
        end_date: str = "2024-02-15",
    ) -> dict[str, Any]:
        """Run the action flow with every nav helper patched as a spy."""
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        base = self._BASE
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

        read_snap = MagicMock(return_value=list(snapshot))
        report_wait = MagicMock(
            side_effect=report_ready if report_ready is not None else [True]
        )
        resolve_pdf = MagicMock(return_value="https://legacy.example/report.pdf")
        download = MagicMock(return_value=b"%PDF-1.4 synth")
        if download_side_effect is not None:
            download.side_effect = download_side_effect
        extract_text = MagicMock(return_value="raw synth text")
        normalize = MagicMock(
            side_effect=lambda *a, **k: [
                {
                    "admission_key": k.get("admission_key", ""),
                    "happened_at": "2024-01-10T09:00:00",
                    "event_type": "medical",
                    "content": "ok",
                    "profession": "Dr Synth",
                }
            ]
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        kwargs: dict[str, Any] = {
            "patient_record": "SYN-PR-1",
            "start_date": start_date,
            "end_date": end_date,
            "timeout": 60,
        }
        if target is not None:
            kwargs["target_admission"] = target

        with (
            patch(f"{base}.ensure_search_screen", spies["ensure_search_screen"]),
            patch(f"{base}.search_patient", spies["search_patient"]),
            patch(f"{base}.click_internacoes", spies["click_internacoes"]),
            patch(f"{base}._read_and_build_snapshot", read_snap),
            patch(
                f"{base}.open_internacao_detail",
                spies["open_internacao_detail"],
            ),
            patch(f"{base}.click_evolucao", spies["click_evolucao"]),
            patch(f"{base}.fill_evolution_dates", spies["fill_evolution_dates"]),
            patch(
                f"{base}.select_ascending_order",
                spies["select_ascending_order"],
            ),
            patch(
                f"{base}.click_visualizar_report",
                spies["click_visualizar_report"],
            ),
            patch(
                f"{base}.go_back_to_detail_from_report",
                spies["go_back_to_detail_from_report"],
            ),
            patch(f"{base}.wait_for_report_or_no_evolutions", report_wait),
            patch.object(bridge, "_resolve_pdf_url_from_report_page", resolve_pdf),
            patch.object(bridge, "_download_pdf", download),
            patch(f"{base}.extract_pdf_text", extract_text),
            patch(f"{base}.normalize_pdf_report_text", normalize),
            patch.object(bridge, "_resolve_active_page", return_value=MagicMock()),
        ):
            result = bridge.extract_evolutions_via_legacy_actions(**kwargs)

        return {
            "result": result,
            "open_detail": spies["open_internacao_detail"],
            "normalize": normalize,
        }

    def test_target_selects_only_compatible_admission(self) -> None:
        """R1/R3: among two overlapping rows, only the target-compatible row
        has its detail opened; events carry the selected current key."""
        snapshot = [
            _row("SYN-RK-OLD", "2024-01-01", "2024-01-10"),
            _row("SYN-RK-CUR", "2024-02-01"),
        ]
        target = _target_context(source_admission_key="SYN-RK-STALE",
                                 start_date="2024-02-01")

        out = self._run_flow(snapshot=snapshot, target=target)

        keys = [
            call.kwargs.get("admission_key")
            for call in out["open_detail"].call_args_list
        ]
        assert keys == ["SYN-RK-CUR"]
        assert len(out["result"]) >= 1
        assert all(
            event["admission_key"] == "SYN-RK-CUR" for event in out["result"]
        )

    def test_target_required_action_failure_propagates_not_empty(self) -> None:
        """R7: an Evolução activation failure on the target propagates the
        typed error — it is never converted into an empty/partial result."""
        snapshot = [_row("SYN-RK-CUR", "2024-02-01")]
        target = _target_context(source_admission_key="SYN-RK-CUR",
                                 start_date="2024-02-01")

        with pytest.raises(NavigationError):
            self._run_flow(
                snapshot=snapshot,
                target=target,
                click_evolucao_side_effect=NavigationError(
                    "Falha ao acionar o botão Evolução."
                ),
            )

    def test_target_pdf_download_failure_propagates_not_empty(self) -> None:
        """R7: a required PDF download failure on the target propagates the
        typed sanitized error instead of skipping/returning a list."""
        snapshot = [_row("SYN-RK-CUR", "2024-02-01")]
        target = _target_context(source_admission_key="SYN-RK-CUR",
                                 start_date="2024-02-01")

        with pytest.raises(EvolutionPdfError):
            self._run_flow(
                snapshot=snapshot,
                target=target,
                download_side_effect=EvolutionPdfError(
                    "Falha ao baixar o PDF do relatório de evolução"
                ),
            )

    def test_no_target_processes_all_overlapping_admissions(self) -> None:
        """R8: without a target, both overlapping admissions are processed
        in deterministic order (legacy behavior preserved)."""
        snapshot = [
            _row("SYN-RK-1", "2024-01-10", "2024-01-20"),
            _row("SYN-RK-2", "2024-02-01"),
        ]

        out = self._run_flow(
            snapshot=snapshot,
            target=None,
            report_ready=[True, True],
        )

        keys = [
            call.kwargs.get("admission_key")
            for call in out["open_detail"].call_args_list
        ]
        assert keys == ["SYN-RK-1", "SYN-RK-2"]
        assert out["normalize"].call_count == 2


# ===========================================================================
# Worker resolution (R1/R2/R8/R9)
# ===========================================================================


_SYNTH_SNAPSHOT = [
    {
        "admission_key": "SYN-KEY-CURRENT",
        "admission_start": "2024-01-15",
        "ward": "SYN-WARD",
        "bed": "SYN-BED",
    }
]

_SYNTH_EVOLUTION = [
    {
        "admission_key": "SYN-KEY-CURRENT",
        "happened_at": "2024-01-16T10:30:00",
        "event_type": "medical_evolution",
        "content": "SYNTH stable patient.",
        "profession": "medica",
    }
]


def _synth_patient(key: str) -> Patient:
    return Patient.objects.create(
        source_system="tasy",
        patient_source_key=key,
        name=f"Synth Patient {key}",
    )


def _synth_admission(
    patient: Patient,
    *,
    key: str,
    start: datetime.datetime,
    end: datetime.datetime | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=dj_timezone.make_aware(start),
        discharge_date=(
            dj_timezone.make_aware(end) if end is not None else None
        ),
    )


@pytest.mark.django_db
class TestWorkerTargetAdmissionResolution:
    """The worker resolves ``admission_id`` against the persisted patient
    and propagates the named context — or fails closed before extraction."""

    def _process(self, mock_adapter: MagicMock) -> None:
        with patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        ):
            call_command("process_ingestion_runs_persistent_session")

    def test_worker_resolves_target_and_passes_context(self) -> None:
        """R1/R2: an admission of the run's patient resolves to the named
        context (start, optional end, active flag, key hint)."""
        patient = _synth_patient("SYN-PR-1")
        admission = _synth_admission(
            patient,
            key="SYN-KEY-STALE",
            start=datetime.datetime(2024, 1, 15),
        )
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-1",
                "intent": "full_sync",
                "start_date": "2024-01-15",
                "end_date": "2024-02-15",
                "admission_id": str(admission.pk),
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)
        mock_adapter.extract_evolutions.return_value = _SYNTH_EVOLUTION

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        kwargs = mock_adapter.extract_evolutions.call_args.kwargs
        assert kwargs["target_admission"] == _target_context(
            start_date="2024-01-15",
            source_admission_key="SYN-KEY-STALE",
        )

    def test_worker_resolves_closed_target_context(self) -> None:
        """R1/R2: a discharged admission propagates end date and inactive
        flag."""
        patient = _synth_patient("SYN-PR-2")
        admission = _synth_admission(
            patient,
            key="SYN-KEY-CLOSED",
            start=datetime.datetime(2024, 1, 10),
            end=datetime.datetime(2024, 1, 20),
        )
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-2",
                "intent": "full_sync",
                "start_date": "2024-01-10",
                "end_date": "2024-01-20",
                "admission_id": str(admission.pk),
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)
        mock_adapter.extract_evolutions.return_value = _SYNTH_EVOLUTION

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        kwargs = mock_adapter.extract_evolutions.call_args.kwargs
        assert kwargs["target_admission"] == _target_context(
            start_date="2024-01-10",
            end_date="2024-01-20",
            is_active=False,
            source_admission_key="SYN-KEY-CLOSED",
        )

    def test_worker_admission_of_other_patient_fails_before_extraction(
        self,
    ) -> None:
        """R1/R9: an admission of ANOTHER patient fails the run before
        ``extract_evolutions``; the admission id never reaches the error."""
        # Both patients must exist: the run's local patient and the foreign
        # owner of the targeted admission id.
        _synth_patient("SYN-PR-A")
        patient_b = _synth_patient("SYN-PR-B")
        foreign = _synth_admission(
            patient_b,
            key="SYN-KEY-B",
            start=datetime.datetime(2024, 1, 10),
        )
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-A",
                "intent": "full_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "admission_id": str(foreign.pk),
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        mock_adapter.extract_evolutions.assert_not_called()
        assert str(foreign.pk) not in (run.error_message or "")
        assert "SYN-KEY-B" not in (run.error_message or "")

    def test_worker_unknown_admission_id_fails_before_extraction(self) -> None:
        """R1: an unknown admission id fails closed before extraction."""
        _synth_patient("SYN-PR-A")
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-A",
                "intent": "full_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "admission_id": "999999",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        mock_adapter.extract_evolutions.assert_not_called()

    def test_worker_target_without_admission_date_fails_closed(self) -> None:
        """R1: a local target without any admission date cannot build a
        stable-fact context — fail closed before extraction."""
        patient = _synth_patient("SYN-PR-A")
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="SYN-KEY-NODATE",
            admission_date=None,
        )
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-A",
                "intent": "full_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "admission_id": str(admission.pk),
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "failed"
        mock_adapter.extract_evolutions.assert_not_called()

    def test_worker_without_admission_id_keeps_legacy_extraction(self) -> None:
        """R8: a run without ``admission_id`` extracts with no target —
        the all-overlapping-admissions path stays available."""
        _synth_patient("SYN-PR-1")
        run = _queue_full_sync_run(
            parameters_json={
                "patient_record": "SYN-PR-1",
                "intent": "full_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-02-15",
            },
        )
        mock_adapter = _make_adapter_mock(snapshot_result=_SYNTH_SNAPSHOT)
        mock_adapter.extract_evolutions.return_value = _SYNTH_EVOLUTION

        self._process(mock_adapter)

        run.refresh_from_db()
        assert run.status == "succeeded"
        kwargs = mock_adapter.extract_evolutions.call_args.kwargs
        assert kwargs["target_admission"] is None


# ===========================================================================
# Legacy mode regression guard (R8)
# ===========================================================================


class TestLegacyOverlapModePreserved:
    """``choose_overlapping_admissions`` keeps its all-overlapping contract
    (used by the no-target mode)."""

    def test_choose_overlapping_admissions_returns_all_overlaps(self) -> None:
        rows = [
            _row("SYN-RK-1", "2024-01-10", "2024-01-20"),
            _row("SYN-RK-2", "2024-02-01"),
            _row("SYN-RK-OUT", "2025-01-01", "2025-01-31"),
        ]

        selected = choose_overlapping_admissions(
            rows,
            start_date="2024-01-05",
            end_date="2024-02-15",
        )

        assert [row["admissionKey"] for row in selected] == [
            "SYN-RK-1",
            "SYN-RK-2",
        ]

    def test_targeted_extraction_error_is_typed(self) -> None:
        """Sanity: the typed taxonomy used by target failures is importable
        and distinct (no bare Exception semantics)."""
        assert issubclass(EvolutionPdfError, Exception)
        assert issubclass(ExtractionError, Exception)
