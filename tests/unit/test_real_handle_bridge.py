"""Tests for RealHandleBridge (PSW-S9 / PSW-S11).

Prove that the bridge can translate real legacy UI HTML/download data into
the synthetic container format expected by ``PersistentExtractionAdapter``,
without requiring the real legacy DOM to produce ``#admission-snapshot-data``
and ``#evolution-data`` containers.

PSW-S11 adds the persistent evolution PDF flow delegation tests
(``TestRealHandleBridgeEvolutionPdf``).

All tests use mocked Playwright pages or synthetic anonymous HTML.
No real legacy access required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from apps.ingestion.extractors.persistent_extraction_adapter import (
    _ADMISSION_DATA_DIV_ID,
    _DATA_CONTAINER_RE,
    _EVOLUTION_DATA_CONTAINER_RE,
    _EVOLUTION_DATA_DIV_ID,
)
from apps.ingestion.extractors.session_policy import TabCleanupOutcome
from tests.unit.test_legacy_navigation import (  # noqa: PLC0415
    FakeClock,
    FakeNavigationFrame,
    FakeNavigationPage,
)

# ===========================================================================
# Representative legacy UI HTML (no synthetic containers!)
# ===========================================================================

LEGACY_ADMISSIONS_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <table id="tabelaInternacoes:resultList">
    <tbody id="tabelaInternacoes:resultList_data">
      <tr data-ri="0" data-rk="ADM-RK-001">
        <td>15/01/2024</td>
        <td>20/01/2024</td>
        <td>Enfermaria A</td>
        <td>Leito 101</td>
        <td><a title="Detalhes da Internação">Detalhes</a></td>
      </tr>
      <tr data-ri="1" data-rk="ADM-RK-002">
        <td>01/03/2024</td>
        <td></td>
        <td>UTI</td>
        <td>Leito 005</td>
        <td><a title="Detalhes da Internação">Detalhes</a></td>
      </tr>
      <tr data-ri="2" data-rk="">
        <td>10/05/2024</td>
        <td>15/05/2024</td>
        <td></td>
        <td></td>
        <td><a title="Detalhes da Internação">Detalhes</a></td>
      </tr>
    </tbody>
  </table>
</div>
</body>
</html>"""

LEGACY_EVOLUTIONS_PAGE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>27</span>:<span>30</span>
</div>
<div id="mainContent">
  <div class="ui-panel-content">
    <pre class="report-text">===== PÁGINA 1 =====
EVOLUÇÃO
/ 15
15/01/2024 10:30
Paciente estável, sem queixas. Sinais vitais dentro da normalidade.
Elaborado por Dr. Silva, CRM 12345 em: 15/01/2024 10:35

15/01/2024 14:00
Paciente refere melhora. Mantida conduta.
Elaborado por Enf. Maria, Coren 67890 em: 15/01/2024 14:05</pre>
  </div>
</div>
</body>
</html>"""

LEGACY_EVOLUTIONS_PAGE_JSON = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>27</span>:<span>30</span>
</div>
<div id="mainContent">
  <script id="evolution-data-json" type="application/json">
[
  {
    "createdAt": "2024-01-15T10:30:00",
    "type": "medical",
    "content": "Paciente est\\u00e1vel, sem queixas.",
    "createdBy": "Dr. Silva",
    "admissionKey": "ADM-RK-001"
  },
  {
    "createdAt": "2024-01-15T14:00:00",
    "type": "nursing",
    "content": "Paciente refere melhora.",
    "createdBy": "Enf. Maria",
    "admissionKey": "ADM-RK-001"
  }
]
  </script>
</div>
</body>
</html>"""

MISSING_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <p>Nenhuma internação encontrada para este prontuário.</p>
</div>
</body>
</html>"""

EMPTY_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <table id="tabelaInternacoes:resultList">
    <tbody id="tabelaInternacoes:resultList_data">
    </tbody>
  </table>
</div>
</body>
</html>"""


# ===========================================================================
# Fake session handles for bridge tests
# ===========================================================================


class FakePlaywrightHandle:
    """Fake that simulates a ``PlaywrightSessionHandle`` with ``evaluate_js``.

    Provides a minimal Playwright-like interface: ``get_page_html()``,
    ``evaluate_js()``, and the standard ``SessionHandle`` protocol methods.
    """

    def __init__(self) -> None:
        self._html: str = ""
        self._connected: bool = True
        self._clicked_selectors: list[str] = []
        self._opened_urls: list[str] = []
        self._closed_tab_calls: int = 0
        self._restart_calls: int = 0
        self._tab_classes: list[str] = ["tabs-first tabs-last tabs-selected"]
        self._last_open_timeout: int | None = None
        self._js_results: dict[str, object] = {}
        self._js_calls: list[str] = []
        self._shutdown_calls: int = 0

    # --- State mutators ---

    def set_html(self, html: str) -> None:
        self._html = html

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def set_tab_classes(self, classes: list[str]) -> None:
        self._tab_classes = list(classes)

    def set_evaluate_js_result(self, expression_match: str,
                               result: object) -> None:
        """Register a JS evaluation result for a matching expression."""
        self._js_results[expression_match] = result

    # --- SessionHandle protocol ---

    def get_page_html(self) -> str:
        return self._html

    def is_connected(self) -> bool:
        return self._connected

    def click_selector(self, selector: str) -> None:
        self._clicked_selectors.append(selector)

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        self._opened_urls.append(url)
        self._last_open_timeout = timeout
        return True

    def get_tab_classes(self) -> list[str]:
        return list(self._tab_classes)

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        self._closed_tab_calls += 1
        return TabCleanupOutcome.CLOSED_AND_VERIFIED

    def restart_browser(self) -> None:
        self._restart_calls += 1
        self._connected = True

    def shutdown(self) -> None:
        self._shutdown_calls += 1

    def ensure_current_page(self):
        """Return None by default (PSW-S12). Override in specific tests."""
        return None

    def evaluate_js(self, expression: str) -> object:
        """Simulate Playwright's page.evaluate()."""
        self._js_calls.append(expression)
        for match_key, result in self._js_results.items():
            if match_key in expression:
                return result
        return None

    # --- Test query helpers ---

    @property
    def opened_urls(self) -> list[str]:
        return list(self._opened_urls)

    @property
    def last_open_timeout(self) -> int | None:
        return self._last_open_timeout

    @property
    def closed_tab_calls(self) -> int:
        return self._closed_tab_calls

    @property
    def restart_calls(self) -> int:
        return self._restart_calls

    @property
    def shutdown_calls(self) -> int:
        return self._shutdown_calls

    @property
    def js_calls(self) -> list[str]:
        return list(self._js_calls)


# ===========================================================================
# Bridge tests: synthetic-container production
# ===========================================================================


class TestRealHandleBridgeAdmissions:
    """Tests that the bridge produces valid admission snapshot containers
    from representative legacy UI HTML that does NOT contain synthetic
    ``#admission-snapshot-data`` divs."""

    def test_bridge_produces_synthetic_container_from_legacy_table(
        self,
    ) -> None:
        """Bridge wraps admission data from legacy tabelaInternacoes into
        <div id='admission-snapshot-data'>."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        # Simulate: open admissions tab, then get page HTML
        bridge.open_tab("/consultarInternacoes.xhtml")
        result_html = bridge.get_page_html()

        # Must contain the synthetic admission-snapshot-data container
        assert _ADMISSION_DATA_DIV_ID in result_html
        # Must contain valid JSON inside the container
        match = _DATA_CONTAINER_RE.search(result_html)
        assert match is not None, (
            "Bridge must produce <div id='admission-snapshot-data'> "
            "with JSON content"
        )
        json_text = match.group(1)
        data = json.loads(json_text)
        assert isinstance(data, list)
        assert len(data) == 3  # three rows in the table

        # Verify canonical fields (bridge outputs camelCase for
        # AdmissionSnapshotParser compatibility)
        assert data[0]["admissionKey"] == "ADM-RK-001"
        assert data[0]["admissionStart"] == "2024-01-15"
        assert data[0]["admissionEnd"] == "2024-01-20"
        assert data[0]["ward"] == "Enfermaria A"
        assert data[0]["bed"] == "Leito 101"

        # Open-ended admission
        assert data[1]["admissionKey"] == "ADM-RK-002"
        assert data[1]["admissionEnd"] is None

        # Row with empty admission key — gets fallback key like path2.py
        assert data[2]["admissionKey"] == "row-2"
        assert data[2]["admissionStart"] == "2024-05-10"

    def test_bridge_preserves_session_counter_in_output(self) -> None:
        """Bridge output still contains #tempoSessao for controller
        checks."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        result_html = bridge.get_page_html()

        # The session counter must pass through (the counter div with
        # tempoSessao id and span-based time display)
        assert "tempoSessao" in result_html
        assert "<span>00</span>" in result_html
        assert "<span>29</span>" in result_html
        assert "<span>01</span>" in result_html

    def test_bridge_preserves_renewal_popup_for_defensive_detection(self) -> None:
        """Bridge output keeps #casca_renovasession so the controller's
        defensive is_renewal_popup_visible() check still works."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_policy import (
            is_renewal_popup_visible,
        )

        popup_html = (
            '<div id="casca_renovasession" aria-hidden="false" '
            'style="display: block;">'
            '<button class="ui-confirmdialog-yes">Renovar</button>'
            "</div>"
        )
        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML + popup_html)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        result_html = bridge.get_page_html()

        # Defensive popup detection must still see the visible popup.
        assert "casca_renovasession" in result_html
        assert is_renewal_popup_visible(result_html) is True

    def test_bridge_empty_table_produces_empty_json(self) -> None:
        """Bridge handles empty admission tables gracefully."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(EMPTY_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        result_html = bridge.get_page_html()

        match = _DATA_CONTAINER_RE.search(result_html)
        assert match is not None
        data = json.loads(match.group(1))
        assert data == []

    def test_bridge_missing_table_returns_empty_json(self) -> None:
        """Bridge handles missing admissions table by returning empty JSON."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(MISSING_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        # The bridge should produce a container with empty data, or the
        # adapter will raise SnapshotContainerMissingError later.
        result_html = bridge.get_page_html()

        # Bridge still produces the container (even with empty data)
        # so the adapter's existing error taxonomy applies.
        match = _DATA_CONTAINER_RE.search(result_html)
        assert match is not None
        data = json.loads(match.group(1))
        assert data == []  # no rows to extract

    def test_bridge_timeout_propagates_to_handle(self) -> None:
        """Bridge's open_tab propagates timeout to the wrapped handle."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml", timeout=45)

        assert handle.last_open_timeout == 45


class TestRealHandleBridgeEvolutions:
    """Tests that the bridge produces valid evolution data containers from
    representative legacy UI HTML/download data."""

    def test_bridge_produces_evolution_container_from_legacy_page(
        self,
    ) -> None:
        """Bridge wraps evolution data from legacy evolution page into
        <div id='evolution-data'>."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/relatorioAnaEvoInternacaoPdf.xhtml")
        result_html = bridge.get_page_html()

        # Must contain the synthetic evolution-data container
        assert _EVOLUTION_DATA_DIV_ID in result_html
        match = _EVOLUTION_DATA_CONTAINER_RE.search(result_html)
        assert match is not None, (
            "Bridge must produce <div id='evolution-data'> "
            "for evolution pages"
        )
        data = json.loads(match.group(1))
        assert isinstance(data, list)
        assert len(data) == 2

        assert data[0]["event_type"] == "medical"
        assert data[0]["admission_key"] == "ADM-RK-001"
        assert data[1]["event_type"] == "nursing"

    def test_bridge_non_evolution_url_passes_html_through(self) -> None:
        """Bridge returns raw HTML when URL is not an evolution page."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/some-other-page.xhtml")
        result_html = bridge.get_page_html()

        # Raw HTML passed through without synthetic containers.
        # Use full element check (the ID "evolution-data" is a
        # substring of "evolution-data-json" in script id, so check
        # that the container div is NOT present).
        assert "<div id=\"evolution-data\">" not in result_html
        assert "<div id=\"admission-snapshot-data\">" not in result_html
        assert "evolution-data-json" in result_html  # original content

    def test_bridge_evolution_empty_content(self) -> None:
        """Bridge handles empty evolution content gracefully."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(
            """<html><body>
            <div id="tempoSessao">00:27:30</div>
            </body></html>"""
        )
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/evolutions/12345")
        result_html = bridge.get_page_html()

        match = _EVOLUTION_DATA_CONTAINER_RE.search(result_html)
        assert match is not None
        data = json.loads(match.group(1))
        assert data == []


# ===========================================================================
# Protocol delegation tests
# ===========================================================================


class TestRealHandleBridgeDelegation:
    """Bridge delegates all protocol methods to the wrapped handle."""

    def test_bridge_delegates_is_connected(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        assert bridge.is_connected() is True
        handle.set_connected(False)
        assert bridge.is_connected() is False

    def test_bridge_delegates_click_selector(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        bridge.click_selector("#someButton")
        assert "#someButton" in handle._clicked_selectors

    def test_bridge_delegates_tab_operations(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_tab_classes(["tabs-first", "tabs-last"])
        bridge = RealHandleBridge(handle)

        assert bridge.get_tab_classes() == ["tabs-first", "tabs-last"]

        bridge.close_last_non_root_tab()
        assert handle.closed_tab_calls == 1

    def test_bridge_delegates_restart_browser(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        bridge.restart_browser()
        assert handle.restart_calls == 1

    def test_bridge_delegates_shutdown(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        bridge.shutdown()
        assert handle.shutdown_calls == 1


# ===========================================================================
# Integration: bridge + adapter contract
# ===========================================================================


class TestBridgeToAdapterIntegration:
    """Tests that the bridge output satisfies the adapter's extraction
    contract (container regexes, JSON parsing)."""

    def test_adapter_can_parse_bridge_admission_output(self) -> None:
        """The PersistentExtractionAdapter can consume bridge output."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            _parse_admissions_json,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        bridge_html = bridge.get_page_html()

        # Parse through existing adapter machinery
        match = _DATA_CONTAINER_RE.search(bridge_html)
        assert match is not None
        json_text = match.group(1)

        result = _parse_admissions_json(json_text)
        assert len(result) == 3
        assert result[0]["admission_key"] == "ADM-RK-001"
        assert result[0]["admission_start"] == "2024-01-15"

    def test_adapter_can_parse_bridge_evolution_output(self) -> None:
        """The PersistentExtractionAdapter can consume bridge evolution
        output."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            _parse_evolutions_json,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/relatorioAnaEvoInternacaoPdf.xhtml")
        bridge_html = bridge.get_page_html()

        match = _EVOLUTION_DATA_CONTAINER_RE.search(bridge_html)
        assert match is not None
        json_text = match.group(1)

        result = _parse_evolutions_json(json_text)
        assert len(result) == 2
        assert result[0]["admission_key"] == "ADM-RK-001"
        assert "content" in result[0]

    def test_bridge_output_is_consumable_by_full_adapter_flow(self) -> None:
        """Full adapter.get_admission_snapshot() succeeds with bridge
        output."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        handle = FakePlaywrightHandle()

        # Set up ensure_current_page to return a fake page that supports
        # the navigation helpers (PSW-S12: navigate_to_admissions).
        fake_page = MagicMock()
        fake_frame = MagicMock()
        fake_frame.eval_on_selector_all.return_value = [
            {
                "dataRi": "0",
                "dataRk": "ADM-RK-001",
                "cells": ["15/01/2024", "20/01/2024", "Enfermaria A",
                          "Leito 101", "Detalhes"],
                "hasDetailsLink": True,
            },
            {
                "dataRi": "1",
                "dataRk": "ADM-RK-002",
                "cells": ["01/03/2024", "", "UTI", "Leito 005",
                          "Detalhes"],
                "hasDetailsLink": True,
            },
            {
                "dataRi": "2",
                "dataRk": "",
                "cells": ["10/05/2024", "15/05/2024", "", "",
                          "Detalhes"],
                "hasDetailsLink": True,
            },
        ]
        fake_page.frame.return_value = fake_frame
        handle.ensure_current_page = lambda: fake_page  # type: ignore[method-assign]

        # Set counter HTML initially for readiness checks
        handle.set_html("""<html><body>
        <div id="tempoSessao">
          Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
        </div></body></html>""")
        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_admissions_url="/consultarInternacoes.xhtml",
            ),
        )

        # Replace handle HTML with legacy table HTML before navigation
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["admission_key"] == "ADM-RK-001"

    def test_bridge_adapter_evolution_flow(self) -> None:
        """PSW-S20: the real bridge dispatches action-first end-to-end.

        ``adapter.extract_evolutions`` calls the bridge's
        ``extract_evolutions_via_legacy_actions`` directly (no synthetic
        evolution URL) and enriches the returned 5-key events with the
        persistible schema. The JSON container translation remains covered by
        the direct bridge tests (``TestRealHandleBridgeEvolutions``); it is no
        longer reached through ``open_tab`` on the real handle (R2/R3).
        """
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        handle = FakePlaywrightHandle()
        handle.set_html("""<html><body>
        <div id="tempoSessao">
          Tempo de Sessão: <span>00</span>:<span>27</span>:<span>30</span>
        </div></body></html>""")
        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )

        action_events = [
            {
                "admission_key": "ADM-RK-001",
                "happened_at": "2024-01-15T10:30:00",
                "event_type": "medical",
                "content": "Paciente estável.",
                "profession": "Dr. Silva",
            },
            {
                "admission_key": "ADM-RK-001",
                "happened_at": "2024-01-16T09:00:00",
                "event_type": "nursing",
                "content": "Curativo trocado.",
                "profession": "Enf. Maria",
            },
        ]
        with patch.object(
            bridge,
            "extract_evolutions_via_legacy_actions",
            return_value=action_events,
        ):
            result = adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        # No synthetic evolution URL opened on the real handle (R2).
        assert handle._opened_urls == []
        assert isinstance(result, list)
        assert len(result) == 2
        # Adapter enrichment added the persistible schema.
        assert result[0]["patient_source_key"] == "12345"
        assert result[0]["source_system"] == "tasy"
        assert result[0]["content"] is not None

    def test_bridge_tab_cleanup_is_only_cleanup(self) -> None:
        """Tab cleanup through bridge does not alter session state beyond
        closing the tab."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_tab_classes(
            ["tabs-first tabs-last tabs-selected",
             "tabs-last"]
        )
        bridge = RealHandleBridge(handle)

        # Before cleanup
        assert handle.closed_tab_calls == 0

        bridge.close_last_non_root_tab()

        # Cleanup happened
        assert handle.closed_tab_calls == 1

        # Connected state unchanged
        assert bridge.is_connected() is True

    def test_bridge_preserves_exclusive_profile_behavior(self) -> None:
        """Bridge restart delegates to handle restart, preserving
        exclusive profile behavior."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        assert handle.restart_calls == 0

        bridge.restart_browser()

        # Restart was delegated
        assert handle.restart_calls == 1


# ===========================================================================
# Error taxonomy
# ===========================================================================


class TestBridgeErrorTaxonomy:
    """Tests that bridge failures use safe error taxonomy: no credential
    or patient-data leakage."""

    def test_bridge_error_messages_no_sensitive_data(self) -> None:
        """Bridge error messages do not contain credentials, patient data,
        cookies, or internal secrets."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        # Empty HTML that has nothing useful
        handle.set_html("<html><body></body></html>")
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        result = bridge.get_page_html()

        # The bridge should return HTML with an empty container, not leak
        # raw error info.
        assert _ADMISSION_DATA_DIV_ID in result
        assert "password" not in result.lower()
        assert "cookie" not in result.lower()
        assert "token" not in result.lower()


# ===========================================================================
# Bridge: non-real-Handle fallback (no JS evaluation)
# ===========================================================================


class TestBridgeWithoutJSEvaluation:
    """Tests that the bridge can extract data from HTML without requiring
    ``evaluate_js`` on the wrapped handle."""

    def test_bridge_works_without_evaluate_js_capability(self) -> None:
        """Bridge extracts admission data by parsing HTML, not requiring
        evaluate_js."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        # A handle without evaluate_js
        class MinimalHandle:
            def __init__(self, html: str = ""):
                self._html = html
                self._connected = True
                self._clicked: list[str] = []
                self._opened: list[str] = []
                self._closed = 0
                self._restart = 0
                self._tab_classes: list[str] = [
                    "tabs-first tabs-last tabs-selected"
                ]

            def get_page_html(self) -> str:
                return self._html

            def is_connected(self) -> bool:
                return self._connected

            def click_selector(self, s: str) -> None:
                self._clicked.append(s)

            def open_tab(self, u: str, *, timeout: int = 120) -> bool:
                self._opened.append(u)
                return True

            def get_tab_classes(self) -> list[str]:
                return list(self._tab_classes)

            def close_last_non_root_tab(self) -> TabCleanupOutcome:
                self._closed += 1
                return TabCleanupOutcome.CLOSED_AND_VERIFIED

            def restart_browser(self) -> None:
                self._restart += 1

        handle = MinimalHandle(LEGACY_ADMISSIONS_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        bridge.open_tab("/consultarInternacoes.xhtml")
        result_html = bridge.get_page_html()

        match = _DATA_CONTAINER_RE.search(result_html)
        assert match is not None
        data = json.loads(match.group(1))
        assert len(data) == 3
        assert data[0]["admissionKey"] == "ADM-RK-001"


# ===========================================================================
# PSW-S11: persistent evolution PDF flow delegation
# ===========================================================================


class TestRealHandleBridgeEvolutionPdf:
    """The bridge delegates the real legacy PDF flow to EvolutionPdfFlow,
    reusing the wrapped handle's already-open page — no new browser,
    no subprocess, no path2.py shell-out."""

    def test_extract_evolutions_pdf_prefers_ensure_current_page(self) -> None:
        """The real handle exposes ``ensure_current_page()``, not ``current_page()``.

        The bridge MUST obtain the page from ``ensure_current_page()`` when the
        handle does not expose ``current_page()``, otherwise the real-handle PDF
        fallback fails with "no active page".
        """
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        fake_page = object()  # sentinel
        # Real PlaywrightSessionHandle exposes ensure_current_page(), NOT
        # current_page(). FakePlaywrightHandle has neither by default.
        handle.ensure_current_page = lambda: fake_page  # type: ignore[method-assign]
        assert not hasattr(handle, "current_page")

        with patch(
            "apps.ingestion.extractors.real_handle_bridge.EvolutionPdfFlow"
        ) as flow_cls:
            flow_cls.return_value.extract.return_value = []

            bridge.extract_evolutions_pdf(
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        # The flow was built with the page returned by ensure_current_page().
        flow_cls.assert_called_once_with(fake_page)

    def test_extract_evolutions_pdf_uses_handle_current_page(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        fake_page = object()  # sentinel
        handle.current_page = lambda: fake_page  # type: ignore[attr-defined]

        with patch(
            "apps.ingestion.extractors.real_handle_bridge.EvolutionPdfFlow"
        ) as flow_cls:
            flow_cls.return_value.extract.return_value = [
                {
                    "admission_key": "ADM-1",
                    "happened_at": "2024-01-15T10:00:00",
                    "event_type": "medical",
                    "content": "ok",
                    "profession": "Dr. X",
                }
            ]

            events = bridge.extract_evolutions_pdf(
                start_date="2024-01-01",
                end_date="2024-01-31",
                timeout=90,
            )

        # EvolutionPdfFlow was built with the handle's existing page.
        flow_cls.assert_called_once_with(fake_page)
        flow_cls.return_value.extract.assert_called_once()
        _, kwargs = flow_cls.return_value.extract.call_args
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["end_date"] == "2024-01-31"
        assert kwargs["timeout"] == 90
        assert len(events) == 1
        assert events[0]["event_type"] == "medical"

    def test_extract_evolutions_pdf_no_page_raises_sanitized_error(self) -> None:
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        # Handle without current_page() -> no active page for the PDF flow.
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with pytest.raises(EvolutionPdfError, match="no active page"):
            bridge.extract_evolutions_pdf(
                start_date="2024-01-01", end_date="2024-01-31"
            )

    def test_extract_evolutions_pdf_propagates_sanitized_flow_error(self) -> None:
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        handle.current_page = lambda: object()  # type: ignore[attr-defined]

        with patch(
            "apps.ingestion.extractors.real_handle_bridge.EvolutionPdfFlow"
        ) as flow_cls:
            flow_cls.return_value.extract.side_effect = EvolutionPdfError(
                "Evolution report PDF could not be located on the page"
            )

            with pytest.raises(EvolutionPdfError, match="could not be located"):
                bridge.extract_evolutions_pdf(
                    start_date="2024-01-01", end_date="2024-01-31"
                )


# ===========================================================================
# PSW-S13: extract_evolutions_via_legacy_actions
# ===========================================================================


class TestBridgeExtractEvolutionsViaLegacyActions:
    """Tests for the real-handle legacy evolution action flow (PSW-S13).

    The bridge exposes ``extract_evolutions_via_legacy_actions()`` which
    performs the full JSP/PrimeFaces action sequence for evolution extraction:
    search patient -> open admissions -> select overlapping -> open details
    -> click Evolução -> fill dates -> select ascending -> visualize ->
    download PDF -> normalize text.
    """

    def test_method_exists_and_returns_list(self) -> None:
        """Bridge exposes the method and it returns a list (empty with fakes)."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_ADMISSIONS_TABLE_HTML)
        bridge = RealHandleBridge(handle)

        # When no active page is available, the method returns [] gracefully.
        result = bridge.extract_evolutions_via_legacy_actions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
            timeout=30,
        )

        assert isinstance(result, list)
        assert result == []

    def test_no_active_page_returns_empty_list(self) -> None:
        """Returns empty list when no active page is available."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        # No ensure_current_page -> no active page
        result = bridge.extract_evolutions_via_legacy_actions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert result == []

    def test_real_handle_adapter_calls_action_method_without_open_tab(
        self,
    ) -> None:
        """PSW-S20 R1/R2: the real handle dispatches action-first.

        The adapter calls ``extract_evolutions_via_legacy_actions`` directly
        and opens ZERO synthetic/direct evolution URLs, even though the bridge
        still exposes ``open_tab`` and the legacy URL template is configured.
        The action method is patched so the dispatch contract (not the action
        internals) is the unit under test; the action internals are covered by
        the bridge-level tests below.
        """
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)
        bridge = RealHandleBridge(handle)

        action_events = [
            {
                "admission_key": "ADM-RK-001",
                "happened_at": "2024-01-15T10:30:00",
                "event_type": "medical",
                "content": "Paciente estável.",
                "profession": "Dr. Silva",
            }
        ]
        with patch.object(
            bridge,
            "extract_evolutions_via_legacy_actions",
            return_value=action_events,
        ) as mock_action:
            adapter = PersistentExtractionAdapter(
                bridge,
                config=SessionControllerConfig(
                    base_evolutions_url="/evolutions/{patient_record}",
                ),
            )
            result = adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-01-31",
                timeout=33,
            )

        # R2: no synthetic/direct evolution URL was opened on the handle.
        assert handle._opened_urls == []
        # The action method was called once with the full contract + timeout.
        mock_action.assert_called_once_with(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
            timeout=33,
        )
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_real_handle_does_not_open_synthetic_evolution_url(
        self,
    ) -> None:
        """PSW-S20 R3: a JSON/pre page state does NOT bypass required real
        navigation. Even when the page holds a ``evolution-data-json`` script,
        the real handle never opens a synthetic evolution URL and the action
        method is the only extraction path."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        handle = FakePlaywrightHandle()
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)
        bridge = RealHandleBridge(handle)

        with patch.object(
            bridge,
            "extract_evolutions_via_legacy_actions",
            return_value=[],
        ) as mock_action:
            adapter = PersistentExtractionAdapter(
                bridge,
                config=SessionControllerConfig(
                    base_evolutions_url="/evolutions/{patient_record}",
                ),
            )
            result = adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        # The JSON in the page was NOT consumed via a synthetic open_tab.
        assert handle._opened_urls == []
        mock_action.assert_called_once()
        assert result == []

    def test_no_subprocess_or_new_browser(self) -> None:
        """The legacy actions path reuses the existing page/context.

        Spies on ``subprocess`` entry points and ``sync_playwright`` while
        running the full action flow (search -> admissions -> detail ->
        Evolução -> dates -> visualize -> PDF download -> normalize) to prove
        none of them is ever invoked, and that the existing handle/page/
        context is reused rather than replaced.
        """
        from unittest.mock import patch

        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from tests.unit.test_persistent_evolution_pdf import (  # noqa: PLC0415
            REPRESENTATIVE_REPORT_TEXT,
            _build_pdf_bytes,
        )

        handle = FakePlaywrightHandle()
        valid_pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)

        # A fake frame whose URL already looks like the report page so
        # ``wait_for_report_or_no_evolutions`` resolves immediately, and
        # whose ``locator(...).count()`` returns 1 (for ``#printLinks``).
        frame = MagicMock()
        frame.url = (
            "https://legacy.example.com/"
            "relatorioAnaEvoInternacaoPdf.xhtml"
        )
        frame_locator = MagicMock()
        frame_locator.count.return_value = 1
        frame_locator.first.wait_for = MagicMock()
        frame_locator.first.click = MagicMock()
        frame.locator.return_value = frame_locator
        frame.get_by_role.return_value = frame_locator
        frame.eval_on_selector_all.return_value = [
            {
                "dataRi": "0",
                "dataRk": "ADM-001",
                "cells": [
                    "15/01/2024",
                    "20/01/2024",
                    "A",
                    "B",
                    "Detalhes",
                ],
                "hasDetailsLink": True,
            },
        ]

        page = MagicMock()
        page.frame.return_value = frame
        from apps.ingestion.extractors.persistent_evolution_pdf import (  # noqa: PLC0415
            _PDF_OBJECT_SELECTOR,
        )

        pdf_object_locator = MagicMock()
        pdf_object_locator.count.return_value = 1
        pdf_object_locator.first.get_attribute.return_value = (
            "https://example.com/report.pdf"
        )
        page.locator.side_effect = (
            lambda selector, *a, **k: pdf_object_locator
            if selector == _PDF_OBJECT_SELECTOR
            else MagicMock()
        )
        page.url = "https://legacy.example.com/"
        page.context.request.get.return_value.ok = True
        page.context.request.get.return_value.body.return_value = (
            valid_pdf_bytes
        )

        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]
        bridge = RealHandleBridge(handle)

        with (
            patch("subprocess.run") as mock_run,
            patch("subprocess.Popen") as mock_popen,
            patch("subprocess.check_output") as mock_check_output,
            patch("subprocess.call") as mock_call,
            patch("playwright.sync_api.sync_playwright") as mock_sync,
        ):
            result = bridge.extract_evolutions_via_legacy_actions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-01-31",
                timeout=30,
            )

        # The full action flow executed and produced events.
        assert isinstance(result, list)
        assert len(result) >= 1

        # No subprocess of any kind and no Playwright re-entry.
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_check_output.assert_not_called()
        mock_call.assert_not_called()
        mock_sync.assert_not_called()

        # PDF was fetched through the existing page context (reused),
        # proving no new browser/context was spun up.
        page.context.request.get.assert_called()

        # The existing handle was reused, not replaced or restarted.
        assert handle.is_connected() is True

    def test_legacy_action_events_carry_persistible_fields(self) -> None:
        """Adapter enriches legacy-action events with persistible fields.

        The bridge's ``extract_evolutions_via_legacy_actions`` returns the
        5-key contract (admission_key/happened_at/event_type/content/
        profession). The adapter's enrichment must add the schema the
        shared ingestion service persists (content_text, profession_type,
        author_name, patient_source_key, source_system), proving the
        PSW-S13 action flow plugs into the existing persistence path.
        """
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        # Session that EXPLICITLY advertises real action navigation (R1:
        # dispatch is selected by capability, not by method presence on a
        # mock). The action method returns a single known event in the 5-key
        # contract; the adapter must enrich it with the persistible schema.
        session = MagicMock()
        session.is_connected.return_value = True
        session.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        session.get_page_html.return_value = (
            "<html><body>"
            '<div id="tempoSessao">'
            "<span>00</span>:<span>29</span>:<span>01</span>"
            "</div></body></html>"
        )
        session.supports_real_evolution_actions.return_value = True
        session.extract_evolutions_via_legacy_actions.return_value = [
            {
                "admission_key": "ADM-001",
                "happened_at": "2024-01-15T10:00:00",
                "event_type": "medical",
                "content": "Paciente estável, sem queixas.",
                "profession": "Médico CRM 1234",
            },
        ]

        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )

        result = adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert len(result) == 1
        event = result[0]
        # Original 5-key contract preserved.
        assert event["content"] == "Paciente estável, sem queixas."
        assert event["event_type"] == "medical"
        # Persistible schema added by adapter enrichment.
        assert event["patient_source_key"] == "12345"
        assert event["source_system"] == "tasy"
        assert event["content_text"] == "Paciente estável, sem queixas."
        assert event["author_name"] == "Médico CRM 1234"
        assert "profession_type" in event
        # The action flow was actually used (not the fast paths).
        session.extract_evolutions_via_legacy_actions.assert_called_once_with(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
            timeout=120,
        )

    def test_required_date_fill_failure_raises_typed_and_skips_report(
        self,
    ) -> None:
        """PSW-S20 R4: a required date-fill failure stops report generation.

        When ``fill_evolution_dates`` raises a non-timeout NavigationError
        (a date input was present but could not be filled), the bridge raises
        a typed ``EvolutionPdfError`` with a constant sanitized message and
        does NOT proceed to generate the report (``click_visualizar_report``
        is never called)."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch(
                "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.search_patient"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
                return_value=[{
                    "admissionKey": "K1",
                    "admissionStart": "2026-01-01",
                    "admissionEnd": "",
                    "ward": "",
                    "bed": "",
                }],
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.open_internacao_detail"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_evolucao"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.fill_evolution_dates",
                side_effect=NavigationError("could not fill date input"),
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.select_ascending_order"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_visualizar_report"
            ) as mock_visualize,
            patch(
                "apps.ingestion.extractors.real_handle_bridge.wait_for_report_or_no_evolutions",
                return_value=False,
            ),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(EvolutionPdfError) as exc_info:
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                )

        # R4: no report was generated after the date-fill failure.
        mock_visualize.assert_not_called()
        # R7: the message is constant/sanitized (no raw cause text).
        assert "could not fill date input" not in str(exc_info.value)
        assert exc_info.value.__context__ is None
        assert exc_info.value.__cause__ is None

    def test_required_date_inputs_absent_raises_typed_and_skips_report(
        self,
    ) -> None:
        """PSW-S20 R4: required date inputs absent -> typed failure, no report.

        ``fill_evolution_dates`` returns False when the required start/end
        date inputs are absent (the evolution modal did not expose them). The
        bridge raises a typed ``EvolutionPdfError`` and never generates a
        report for an unbounded/default window."""
        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch(
                "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.search_patient"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
                return_value=[{
                    "admissionKey": "K1",
                    "admissionStart": "2026-01-01",
                    "admissionEnd": "",
                    "ward": "",
                    "bed": "",
                }],
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.open_internacao_detail"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_evolucao"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.fill_evolution_dates",
                return_value=False,
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.select_ascending_order"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_visualizar_report"
            ) as mock_visualize,
            patch(
                "apps.ingestion.extractors.real_handle_bridge.wait_for_report_or_no_evolutions",
                return_value=False,
            ),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(EvolutionPdfError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                )

        mock_visualize.assert_not_called()


# ===========================================================================
# PSW-S20-C1: action-flow cooperative timeout budget
# ===========================================================================


class TestBridgeActionFlowTimeoutBudget:
    """PSW-S20-C1 A2: ONE cooperative deadline bounds every action helper,
    the report wait, and the download. Each helper receives a positive
    ``timeout_ms`` no greater than the caller budget; later helpers receive
    the SAME deadline's remaining budget (never a fresh full timeout)."""

    _BASE = "apps.ingestion.extractors.real_handle_bridge"

    def test_action_flow_shares_one_deadline_across_all_helpers(self) -> None:
        """One deadline propagates to every named boundary; later helpers see
        a strictly smaller remaining budget after a consumed step."""
        import time

        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        budget_s = 60
        budget_ms = budget_s * 1000
        base = self._BASE

        spies = {
            name: MagicMock()
            for name in (
                "search_patient",
                "click_internacoes",
                "open_internacao_detail",
                "click_evolucao",
                "select_ascending_order",
                "click_visualizar_report",
            )
        }
        ensure = MagicMock()
        # Inject real time consumption so later helpers provably see a smaller
        # remaining budget (ONE shared deadline, not per-helper resets).
        ensure.side_effect = lambda *a, **k: time.sleep(0.30)
        read_snap = MagicMock(
            return_value=[{
                "admissionKey": "K1",
                "admissionStart": "2026-01-01",
                "admissionEnd": "2026-01-15",
                "ward": "",
                "bed": "",
            }]
        )
        fill_dates = MagicMock(return_value=True)
        report_wait = MagicMock(return_value=True)
        resolve_pdf = MagicMock(return_value="https://example/report.pdf")
        download = MagicMock(return_value=b"%PDF-1.4 ok")

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch(f"{base}.ensure_search_screen", ensure),
            patch(f"{base}.search_patient", spies["search_patient"]),
            patch(f"{base}.click_internacoes", spies["click_internacoes"]),
            patch(f"{base}._read_and_build_snapshot", read_snap),
            patch(
                f"{base}.open_internacao_detail",
                spies["open_internacao_detail"],
            ),
            patch(f"{base}.click_evolucao", spies["click_evolucao"]),
            patch(f"{base}.fill_evolution_dates", fill_dates),
            patch(
                f"{base}.select_ascending_order",
                spies["select_ascending_order"],
            ),
            patch(
                f"{base}.click_visualizar_report",
                spies["click_visualizar_report"],
            ),
            patch(f"{base}.wait_for_report_or_no_evolutions", report_wait),
            patch.object(bridge, "_resolve_pdf_url_from_report_page", resolve_pdf),
            patch.object(bridge, "_download_pdf", download),
            patch(f"{base}.extract_pdf_text", return_value="raw text"),
            patch(
                f"{base}.normalize_pdf_report_text",
                return_value=[{
                    "admission_key": "K1",
                    "happened_at": "2026-01-10T09:00:00",
                    "event_type": "medical",
                    "content": "ok",
                    "profession": "Dr",
                }],
            ),
            patch.object(bridge, "_resolve_active_page", return_value=MagicMock()),
        ):
            result = bridge.extract_evolutions_via_legacy_actions(
                patient_record="123",
                start_date="2026-01-01",
                end_date="2026-01-15",
                timeout=budget_s,
            )

        def ms_of(spy: MagicMock) -> int:
            calls = spy.call_args_list
            assert calls, "action helper was not called"
            assert "timeout_ms" in calls[0].kwargs, "no timeout_ms propagated"
            return calls[0].kwargs["timeout_ms"]

        ordered = [
            ensure,
            spies["search_patient"],
            spies["click_internacoes"],
            read_snap,
            spies["open_internacao_detail"],
            spies["click_evolucao"],
            fill_dates,
            spies["select_ascending_order"],
            spies["click_visualizar_report"],
            report_wait,
        ]
        values = [ms_of(s) for s in ordered]

        # Every named boundary received a positive timeout_ms within budget.
        for v in values:
            assert 0 < v <= budget_ms

        # The deadline is shared: after ensure_search_screen consumed ~0.30s,
        # every later helper received a strictly smaller budget than it.
        assert values[1] < values[0]
        for v in values[1:]:
            assert v <= values[0]

        # Report wait + download share the same deadline (bounded, not flat).
        assert report_wait.call_args.kwargs["timeout_ms"] <= budget_ms
        resolve_pdf.assert_called_once()
        download.assert_called_once()
        assert len(result) == 1

    def test_action_flow_propagates_typed_timeout_from_bounded_helper(
        self,
    ) -> None:
        """A typed ``NavigationTimeoutError`` raised by a bounded action helper
        propagates unchanged (never swallowed or turned into an empty window)."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        base = self._BASE
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch(
                f"{base}.ensure_search_screen",
                side_effect=NavigationTimeoutError("deadline expired"),
            ),
            patch(f"{base}.search_patient"),
            patch(f"{base}.click_internacoes"),
            patch(f"{base}._read_and_build_snapshot", return_value=[]),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(NavigationTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                    timeout=60,
                )

    def test_legacy_helper_binds_fixed_waits_to_timeout_ms(self) -> None:
        """A legacy action helper bounds its fixed Playwright wait by the
        supplied ``timeout_ms`` instead of the full default."""
        from apps.ingestion.extractors.legacy_navigation import (
            click_visualizar_report,
        )

        page = MagicMock()
        frame = MagicMock()
        page.frame.return_value = frame
        button = MagicMock()
        frame.locator.return_value = button

        click_visualizar_report(page, timeout_ms=250)

        wait_timeout = button.first.wait_for.call_args.kwargs["timeout"]
        # Bounded by the 250ms budget, strictly below the 15000ms default.
        assert 0 < wait_timeout <= 250

    def test_initial_snapshot_overrun_classified_as_timeout(self) -> None:
        """PSW-S20-C2: when the initial snapshot overruns the shared deadline,
        the expired deadline is classified BEFORE the empty result is
        interpreted. The result is a typed EvolutionPdfTimeoutError, never a
        no-overlap/empty interpretation, and selection never runs."""
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        base = self._BASE
        clock = {"t": 1000.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def overrun_snapshot(*a, **k):  # noqa: ANN202
            # Non-interruptible operation "took" beyond the budget.
            clock["t"] += 2.0
            return []

        choose = MagicMock()
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch("time.monotonic", new=fake_monotonic),
            patch(f"{base}.ensure_search_screen"),
            patch(f"{base}.search_patient"),
            patch(f"{base}.click_internacoes"),
            patch(
                f"{base}._read_and_build_snapshot",
                side_effect=overrun_snapshot,
            ),
            patch(f"{base}.choose_overlapping_admissions", choose),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="P1",
                    start_date="2026-01-01",
                    end_date="2026-01-31",
                    timeout=1,
                )

        # The empty snapshot was NOT interpreted: selection never ran.
        choose.assert_not_called()

    def test_selection_overrun_wins_over_no_overlap_error(self) -> None:
        """PSW-S20-C2: when overlap selection overruns and raises a functional
        NavigationError, the expired deadline is classified BEFORE the failure
        is converted to a no-overlap EvolutionPdfError."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        base = self._BASE
        clock = {"t": 1000.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def overrun_choose(*a, **k):  # noqa: ANN202
            clock["t"] += 2.0
            raise NavigationError("selection failed")

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch("time.monotonic", new=fake_monotonic),
            patch(f"{base}.ensure_search_screen"),
            patch(f"{base}.search_patient"),
            patch(f"{base}.click_internacoes"),
            patch(
                f"{base}._read_and_build_snapshot",
                return_value=[{
                    "admissionKey": "K1",
                    "admissionStart": "2026-01-01",
                    "admissionEnd": "2026-01-31",
                    "ward": "",
                    "bed": "",
                }],
            ),
            patch(
                f"{base}.choose_overlapping_admissions",
                side_effect=overrun_choose,
            ),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="P1",
                    start_date="2026-01-01",
                    end_date="2026-01-31",
                    timeout=1,
                )

        # The functional no-overlap error was NOT emitted (exact type check:
        # EvolutionPdfTimeoutError subclasses EvolutionPdfError).
        assert type(exc_info.value) is EvolutionPdfTimeoutError
        assert type(exc_info.value) is not EvolutionPdfError

    def test_renavigation_snapshot_overrun_stops_next_admission(
        self,
    ) -> None:
        """PSW-S20-C2: when the re-navigation snapshot for a later admission
        overruns the shared deadline, the expired deadline is classified
        BEFORE the next admission action runs."""
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        base = self._BASE
        clock = {"t": 1000.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def _admission(key: str) -> MagicMock:
            m = MagicMock()
            m.get.return_value = key
            return m

        two_admissions = [_admission("K1"), _admission("K2")]
        snapshot_calls = {"n": 0}

        def snapshot(*a, **k):  # noqa: ANN202
            snapshot_calls["n"] += 1
            if snapshot_calls["n"] == 1:
                return []  # initial value unused: choose is patched
            clock["t"] += 2.0  # re-navigation snapshot overruns
            return []

        open_detail = MagicMock()
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch("time.monotonic", new=fake_monotonic),
            patch(f"{base}.ensure_search_screen"),
            patch(f"{base}.search_patient"),
            patch(f"{base}.click_internacoes"),
            patch(f"{base}._read_and_build_snapshot", side_effect=snapshot),
            patch(
                f"{base}.choose_overlapping_admissions",
                return_value=two_admissions,
            ),
            patch(f"{base}.open_internacao_detail", open_detail),
            patch(f"{base}.click_evolucao"),
            patch(f"{base}.fill_evolution_dates", return_value=True),
            patch(f"{base}.select_ascending_order"),
            patch(f"{base}.click_visualizar_report"),
            patch(
                f"{base}.wait_for_report_or_no_evolutions",
                return_value=False,
            ),
            patch.object(
                bridge, "_resolve_active_page", return_value=MagicMock()
            ),
        ):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="P1",
                    start_date="2026-01-01",
                    end_date="2026-01-31",
                    timeout=1,
                )

        # The second admission's detail action was NOT reached after the
        # overrun: only the first admission opened its detail.
        assert open_detail.call_count == 1
        # Placement #3 classifies the overrun at the boundary, BEFORE the
        # second admission's key is read (without #3 the bridge would reach
        # ``admission.get("admissionKey")`` for K2 before the next helper's
        # deadline argument raises).
        two_admissions[1].get.assert_not_called()


# ===========================================================================
# PSW-S21: Canonical chunking and multi-admission flow
# ===========================================================================


class TestBridgeCanonicalChunkingAndMultiAdmission:
    """PSW-S21: bounded 15-day chunks with canonical overlap, processed
    through the SAME authenticated session, with state restored between
    admissions and chunks, prior events preserved across empty chunks, and
    the correct real admission key stamped on every event.

    Every nav helper is patched so the unit under test is the bridge's
    chunk/admission orchestration (not Playwright). The admission snapshot
    carries real ISO dates so the bridge can compute the bounded per-chunk
    windows via the canonical chunking module.
    """

    _BASE = "apps.ingestion.extractors.real_handle_bridge"

    @staticmethod
    def _admission(key: str, start: str, end: str = "") -> dict:
        return {
            "admissionKey": key,
            "admissionStart": start,
            "admissionEnd": end,
            "ward": "",
            "bed": "",
        }

    def _run(
        self,
        *,
        snapshot,
        report_ready_side_effects,
        normalize_side_effect=None,
        patient_record="123",
        start_date="2026-01-01",
        end_date="2026-01-31",
    ):
        """Run the action flow with every nav helper patched as a spy/mock.

        Returns a dict of spies so each test can assert on call counts, the
        bounded chunk windows, and the per-chunk/per-admission ordering.
        """
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
        # fill_evolution_dates records the bounded chunk windows it received.
        fill_calls: list[dict] = []

        def _fill(*a, **k):
            fill_calls.append(
                {
                    "start_date_br": k.get("start_date_br"),
                    "end_date_br": k.get("end_date_br"),
                }
            )
            return True

        spies["fill_evolution_dates"].side_effect = _fill

        read_snap = MagicMock(return_value=list(snapshot))
        report_wait = MagicMock(side_effect=list(report_ready_side_effects))
        resolve_pdf = MagicMock(return_value="https://example/report.pdf")
        download = MagicMock(return_value=b"%PDF-1.4 ok")
        extract_text = MagicMock(return_value="raw text")

        if normalize_side_effect is None:
            def _default_normalize(*a, **k):
                return [{
                    "admission_key": k.get("admission_key", ""),
                    "happened_at": "2026-01-10T09:00:00",
                    "event_type": "medical",
                    "content": "ok",
                    "profession": "Dr",
                }]

            normalize = MagicMock(side_effect=_default_normalize)
        else:
            normalize = MagicMock(side_effect=normalize_side_effect)

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with (
            patch(f"{base}.ensure_search_screen", spies["ensure_search_screen"]),
            patch(f"{base}.search_patient", spies["search_patient"]),
            patch(f"{base}.click_internacoes", spies["click_internacoes"]),
            patch(f"{base}._read_and_build_snapshot", read_snap),
            patch(f"{base}.open_internacao_detail", spies["open_internacao_detail"]),
            patch(f"{base}.click_evolucao", spies["click_evolucao"]),
            patch(f"{base}.fill_evolution_dates", spies["fill_evolution_dates"]),
            patch(f"{base}.select_ascending_order", spies["select_ascending_order"]),
            patch(f"{base}.click_visualizar_report", spies["click_visualizar_report"]),
            patch(f"{base}.go_back_to_detail_from_report", spies["go_back_to_detail_from_report"]),
            patch(f"{base}.wait_for_report_or_no_evolutions", report_wait),
            patch.object(bridge, "_resolve_pdf_url_from_report_page", resolve_pdf),
            patch.object(bridge, "_download_pdf", download),
            patch(f"{base}.extract_pdf_text", extract_text),
            patch(f"{base}.normalize_pdf_report_text", normalize),
            patch.object(bridge, "_resolve_active_page", return_value=MagicMock()),
        ):
            result = bridge.extract_evolutions_via_legacy_actions(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
                timeout=60,
            )

        return {
            "result": result,
            "spies": spies,
            "fill_calls": fill_calls,
            "report_wait": report_wait,
            "normalize": normalize,
            "resolve_pdf": resolve_pdf,
            "download": download,
            "open_detail": spies["open_internacao_detail"],
            "go_back": spies["go_back_to_detail_from_report"],
            "click_internacoes": spies["click_internacoes"],
            "read_snap": read_snap,
        }

    @staticmethod
    def _br_to_date(br: str):
        from datetime import datetime
        return datetime.strptime(br, "%d/%m/%Y").date()

    def test_long_window_chunked_into_bounded_15_day_intervals(self) -> None:
        """R1/R2: a 31-day admission is split into <=15-day chunks with
        canonical overlap; each chunk window is filled, and the detail state
        is restored between chunks (go_back called chunk_count-1 times)."""
        out = self._run(
            snapshot=[self._admission("K1", "2026-01-01", "2026-01-31")],
            report_ready_side_effects=[True, True, True],
        )

        # 31 days -> 3 chunks; fill called once per chunk.
        assert len(out["fill_calls"]) == 3
        # Every filled window spans at most 15 inclusive days (R2).
        for call in out["fill_calls"]:
            start = self._br_to_date(call["start_date_br"])
            end = self._br_to_date(call["end_date_br"])
            assert (end - start).days + 1 <= 15
        # Canonical 1-day overlap: chunk2.start == chunk1.end.
        c = out["fill_calls"]
        assert c[1]["start_date_br"] == c[0]["end_date_br"]
        # State restored between chunks: go_back called chunk_count - 1 times.
        assert out["go_back"].call_count == 2
        # All chunk events accumulated (R7: nothing discarded).
        assert len(out["result"]) == 3

    def test_empty_middle_chunk_preserves_prior_and_continues(self) -> None:
        """R7: a genuine empty MIDDLE chunk returns no fake events and does
        not discard events already collected; the later chunk continues."""
        out = self._run(
            snapshot=[self._admission("K1", "2026-01-01", "2026-01-31")],
            report_ready_side_effects=[True, False, True],
        )

        # Middle chunk was empty: normalize ran only for chunks 1 and 3.
        assert out["normalize"].call_count == 2
        # Prior + later events preserved across the empty middle chunk.
        assert len(out["result"]) == 2

    def test_empty_final_chunk_preserves_prior_and_terminates(self) -> None:
        """R7: a genuine empty FINAL chunk preserves earlier events and the
        loop terminates without error or fake data."""
        out = self._run(
            snapshot=[self._admission("K1", "2026-01-01", "2026-01-31")],
            report_ready_side_effects=[True, True, False],
        )

        assert out["normalize"].call_count == 2
        assert len(out["result"]) == 2

    def test_two_overlapping_admissions_distinct_keys_ordered(self) -> None:
        """R5/R6: two admissions overlapping the window are both processed in
        deterministic order, the admissions list is reopened between them, and
        each event keeps its real admission key."""
        out = self._run(
            snapshot=[
                self._admission("K1", "2026-01-01", "2026-01-10"),
                self._admission("K2", "2026-01-20", "2026-01-30"),
            ],
            # Each admission is <=15 days -> one chunk each.
            report_ready_side_effects=[True, True],
        )

        # Both admissions opened in deterministic (snapshot) order.
        keys = [
            call.kwargs.get("admission_key")
            for call in out["open_detail"].call_args_list
        ]
        assert keys == ["K1", "K2"]
        # Admissions list reopened before the second admission (no new login).
        assert out["click_internacoes"].call_count >= 2
        # Each event keeps its real admission key (distinct).
        result_keys = sorted({event["admission_key"] for event in out["result"]})
        assert result_keys == ["K1", "K2"]

    def test_no_new_browser_context_or_login_between_chunks(self) -> None:
        """R6: iteration never creates a new browser/context/login."""
        with (
            patch("subprocess.run") as mock_run,
            patch("playwright.sync_api.sync_playwright") as mock_sync,
        ):
            self._run(
                snapshot=[self._admission("K1", "2026-01-01", "2026-01-31")],
                report_ready_side_effects=[True, True, True],
            )
        mock_run.assert_not_called()
        mock_sync.assert_not_called()


# ===========================================================================
# PSW-S16: Real-handle demographics extraction via legacy actions
# ===========================================================================


class TestBridgeExtractDemographicsViaLegacyActions:
    """PSW-S16: the bridge extracts demographics through the already-open
    persistent page/context, modeled on the working demographics script
    (search patient -> Dados do Paciente -> frame_pol -> read fields).

    PSW-S16 correction (fail-closed): navigation/page/global-read failures
    raise a sanitized typed error instead of returning ``{}``.
    """

    @staticmethod
    def _ready_page(*, prontuario="14160147", evaluated=None):
        """Build a fake page whose search/demographics actions all succeed."""
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            SEL_CADASTRO_TAB,
            SEL_DADOS_DO_PACIENTE,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#prontuarioInput")
        page.make_selector_visible("role:link:Pesquisa Avançada")
        page.make_selector_visible(SEL_DADOS_DO_PACIENTE)
        frame = FakeNavigationFrame()
        frame.make_selector_visible(SEL_CADASTRO_TAB)
        frame.make_selector_visible(DEMOGRAPHIC_FIELD_SELECTORS["prontuario"])
        payload = {"prontuario": prontuario}
        if evaluated:
            payload.update(evaluated)
        frame.set_evaluate_result(payload)
        page.set_frame(frame)
        return page

    def test_returns_normalized_in_memory_dict(self) -> None:
        """Bridge returns a normalized dict with every field consumed by
        upsert_patient_demographics, in memory (no JSON file)."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page(
            evaluated={
                "nome": "MARIA DE FATIMA SILVA",
                "cpf": "12345678900",
                "data_nascimento": "15/03/1965",
                "nome_social": "",
            }
        )
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        result = bridge.extract_demographics_via_legacy_actions(
            patient_record="14160147",
            timeout=30,
        )

        assert isinstance(result, dict)
        assert result["nome"] == "MARIA DE FATIMA SILVA"
        assert result["cpf"] == "12345678900"
        assert result["data_nascimento"] == "15/03/1965"
        # Optional empty fields preserved, not dropped.
        assert result["nome_social"] == ""

    def test_no_active_page_raises_navigation_error(self) -> None:
        """R1: no active page raises a sanitized NavigationError, not ``{}``."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        with pytest.raises(NavigationError):
            bridge.extract_demographics_via_legacy_actions(
                patient_record="14160147",
                timeout=30,
            )

    def test_navigation_failure_raises_sanitized_navigation_error(self) -> None:
        """R1: a navigation failure raises a constant-message NavigationError,
        never ``{}``."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        # Search screen not available -> ensure_search_screen raises.
        page = FakeNavigationPage()
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        with pytest.raises(NavigationError) as exc_info:
            bridge.extract_demographics_via_legacy_actions(
                patient_record="14160147",
                timeout=30,
            )
        message = str(exc_info.value)
        # Constant sanitized message; no patient record leaked.
        assert "14160147" not in message

    def test_unexpected_exception_wrapped_without_raw_sentinel(self) -> None:
        """R1/F: an unexpected exception is wrapped in a constant-message
        NavigationError; the raw sentinel text appears in neither the public
        message nor emitted logs."""
        import logging

        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        sentinel = "RAW-SECRET-FRAME-PAYLOAD-XYZ"
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page()
        # Override the frame so evaluate raises an unexpected error carrying
        # raw sentinel text that must never leak.
        class _ExplodingFrame(FakeNavigationFrame):
            def evaluate(self, expression, arg=None):  # noqa: ARG002
                raise RuntimeError(sentinel)

        exploder = _ExplodingFrame()
        exploder.make_selector_visible("#aba_cadastro")
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
        )
        exploder.make_selector_visible(
            DEMOGRAPHIC_FIELD_SELECTORS["prontuario"]
        )
        page.set_frame(exploder)
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        caplog = []
        handler = logging.Handler()
        handler.emit = lambda record: caplog.append(record.getMessage())  # type: ignore[method-assign]
        logger = logging.getLogger(
            "apps.ingestion.extractors.real_handle_bridge"
        )
        logger.addHandler(handler)
        try:
            with pytest.raises(NavigationError) as exc_info:
                bridge.extract_demographics_via_legacy_actions(
                    patient_record="14160147",
                    timeout=30,
                )
        finally:
            logger.removeHandler(handler)

        public_message = str(exc_info.value)
        assert sentinel not in public_message
        assert "14160147" not in public_message
        for logged in caplog:
            assert sentinel not in logged

    def test_no_subprocess_no_new_browser_no_second_login(self) -> None:
        """The demographics action flow reuses the existing page/context."""
        from unittest.mock import patch

        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page(evaluated={"nome": "X", "cpf": ""})
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        with (
            patch("subprocess.run") as mock_run,
            patch("subprocess.Popen") as mock_popen,
            patch("subprocess.check_output") as mock_check_output,
            patch("subprocess.call") as mock_call,
            patch("playwright.sync_api.sync_playwright") as mock_sync,
            patch(
                "apps.ingestion.extractors.legacy_session_bootstrap"
                ".bootstrap_legacy_session"
            ) as mock_bootstrap,
        ):
            result = bridge.extract_demographics_via_legacy_actions(
                patient_record="14160147",
                timeout=30,
            )

        assert isinstance(result, dict)
        assert result["nome"] == "X"
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_check_output.assert_not_called()
        mock_call.assert_not_called()
        mock_sync.assert_not_called()
        mock_bootstrap.assert_not_called()
        assert handle.is_connected() is True

    def test_patient_record_normalized_to_digits(self) -> None:
        """The patient record is normalized (digits-only) before search."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page(prontuario="14160147", evaluated={"nome": "Y"})
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge.extract_demographics_via_legacy_actions(
            patient_record="141/60147-A",
            timeout=30,
        )

        assert page.filled_values.get("#prontuarioInput") == "14160147"

    def test_timeout_budget_bounds_all_action_waits(self) -> None:
        """R5: a small supplied timeout bounds every action-step wait; no
        step receives the full default budget."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page(evaluated={"nome": "Z"})
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge.extract_demographics_via_legacy_actions(
            patient_record="14160147",
            timeout=1,
        )

        waits = list(page.wait_timeouts) + list(page._frame.wait_timeouts)
        assert waits, "action helpers must consume the timeout budget"
        # 1s budget -> no wait may reach the 5s/10s defaults.
        assert max(waits) <= 1100

    def test_non_positive_timeout_raises_sanitized_error(self) -> None:
        """R5: a zero/negative timeout is rejected deterministically."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        with pytest.raises(NavigationError):
            bridge.extract_demographics_via_legacy_actions(
                patient_record="14160147",
                timeout=0,
            )


# ===========================================================================
# PSW-S16 final closure: timeout fidelity for the demographics action flow
# ===========================================================================


class TestDemographicsTimeoutFidelity:
    """R2: every Playwright wait/click/fill receives a positive remaining
    timeout; later timeouts decrease under a controlled clock."""

    @staticmethod
    def _ready_page():
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            SEL_CADASTRO_TAB,
            SEL_DADOS_DO_PACIENTE,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#prontuarioInput")
        page.make_selector_visible("role:link:Pesquisa Avançada")
        page.make_selector_visible(SEL_DADOS_DO_PACIENTE)
        frame = FakeNavigationFrame()
        frame.make_selector_visible(SEL_CADASTRO_TAB)
        frame.make_selector_visible(DEMOGRAPHIC_FIELD_SELECTORS["prontuario"])
        frame.set_evaluate_result({"prontuario": "14160147", "nome": "X"})
        page.set_frame(frame)
        return page

    def test_every_wait_click_fill_receives_positive_timeout(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page()
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge.extract_demographics_via_legacy_actions(
            patient_record="14160147", timeout=30
        )

        actions = list(page.action_timeouts) + list(page._frame.action_timeouts)
        assert actions, "demographics actions must be recorded"
        # Every wait/click/fill received a strictly positive timeout (None
        # would mean an action omitted its deadline-bound timeout).
        assert all(t is not None and t > 0 for t in actions), actions
        # click and fill are observed (not just wait_for).
        assert page.click_timeouts, "click actions must record timeouts"
        assert page.fill_timeouts, "fill actions must record timeouts"

    def test_role_pesquisa_avancada_action_recorded(self) -> None:
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page()
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge.extract_demographics_via_legacy_actions(
            patient_record="14160147", timeout=30
        )

        assert ("link", "Pesquisa Avançada") in page.role_calls

    def test_timeouts_decrease_under_controlled_clock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        clock = FakeClock(step=0.0005)  # 0.5 ms per monotonic call
        monkeypatch.setattr("time.monotonic", clock.monotonic)

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page()
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge.extract_demographics_via_legacy_actions(
            patient_record="14160147", timeout=1
        )

        actions = list(page.action_timeouts) + list(page._frame.action_timeouts)
        assert len(actions) >= 2
        assert all(b <= a for a, b in zip(actions, actions[1:], strict=False)), actions
        assert actions[-1] < actions[0], actions
        assert all(t is not None and t > 0 for t in actions)

    def test_budget_exhaustion_stops_next_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        clock = FakeClock(step=5.0)  # budget exhausts almost immediately
        monkeypatch.setattr("time.monotonic", clock.monotonic)

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)
        page = self._ready_page()
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        with pytest.raises(NavigationError):
            bridge.extract_demographics_via_legacy_actions(
                patient_record="14160147", timeout=1
            )
        # The frame field read (a late operation) never ran.
        assert page._frame.evaluate_calls == []


# ===========================================================================
# PSW-S17 post-ce2c494: D12 — bridge report-content timeout propagation
# ===========================================================================


class TestBridgePdfBoundedUrlResolution:
    """PSW-S17 post-cbf50c1 (D17): the bridge PDF URL resolution must NOT
    call the unbounded ``page.content()``. It resolves the PDF URL through
    bounded locator operations governed by the caller deadline, and a real
    Playwright timeout from the bounded attribute read surfaces as
    EvolutionPdfTimeoutError."""

    def test_resolve_pdf_url_locator_timeout_raises_typed(self) -> None:
        """_resolve_pdf_url_from_report_page: object present but a bounded
        attribute read raises a real Playwright timeout →
        EvolutionPdfTimeoutError (not swallowed into empty HTML)."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        class _TimeoutAttrLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                raise PlaywrightTimeoutError("Timeout 30000ms")

        class _TimeoutAttrPage:
            url = "https://legacy/relatorio.xhtml"
            frames: list = []
            content_calls = 0

            def locator(self, selector):  # noqa: ARG002
                return _TimeoutAttrLocator()

            def content(self):  # type: ignore[no-untyped-def]
                _TimeoutAttrPage.content_calls += 1
                raise AssertionError("page.content() must not be called")

        bridge = RealHandleBridge.__new__(RealHandleBridge)
        with pytest.raises(EvolutionPdfTimeoutError):
            bridge._resolve_pdf_url_from_report_page(
                _TimeoutAttrPage(), _pdf_deadline_s(120)
            )
        assert _TimeoutAttrPage.content_calls == 0

    def test_action_flow_does_not_swallow_locator_timeout(self) -> None:
        """The extract_evolutions_via_legacy_actions caller around PDF URL
        resolution re-raises EvolutionPdfTimeoutError instead of catching
        generic Exception and continuing."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        class _TimeoutAttrLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                raise PlaywrightTimeoutError("Timeout 30000ms")

        class _TimeoutPage:
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []

            def locator(self, selector):  # noqa: ARG002
                return _TimeoutAttrLocator()

        # Patch the full action flow so the report is "ready" and the
        # bounded URL-resolution path is reached directly.
        with patch(
            "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.search_patient"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
            return_value=[{"admissionKey": "K1", "admissionStart": "2026-01-01",
                           "admissionEnd": "", "ward": "", "bed": ""}],
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.open_internacao_detail"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_evolucao"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.fill_evolution_dates"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.select_ascending_order"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_visualizar_report"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.wait_for_report_or_no_evolutions",
            return_value=True,
        ), patch.object(
            bridge, "_resolve_active_page", return_value=_TimeoutPage()
        ):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                    timeout=5,
                )

    def test_small_caller_budget_never_sends_large_download_timeout(
        self,
    ) -> None:
        """A 5-second caller budget never yields a 120-second download on the
        bridge action flow."""
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        class _UrlLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                return "https://legacy.example/report.pdf"

        class _FakeRequest:
            def __init__(self):
                self.calls: list[tuple[str, dict]] = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                raise PlaywrightTimeoutError("Timeout")

        class _FakeContext:
            def __init__(self):
                self.request = _FakeRequest()

        class _DownloadPage:
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []
            context = _FakeContext()

            def locator(self, selector):  # noqa: ARG002
                return _UrlLocator()

        with patch(
            "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.search_patient"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
            return_value=[{"admissionKey": "K1", "admissionStart": "2026-01-01",
                           "admissionEnd": "", "ward": "", "bed": ""}],
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.open_internacao_detail"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_evolucao"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.fill_evolution_dates"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.select_ascending_order"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_visualizar_report"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.wait_for_report_or_no_evolutions",
            return_value=True,
        ), patch.object(
            bridge, "_resolve_active_page", return_value=_DownloadPage()
        ):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                    timeout=5,
                )

        # The download timeout passed to request.get must be bounded by the
        # 5-second caller budget (never 120000 ms).
        assert _DownloadPage.context.request.calls
        _, kwargs = _DownloadPage.context.request.calls[0]
        assert 1 <= kwargs["timeout"] <= 5_000


class TestBridgeDeadlineThroughBodyAndParsing:
    """PSW-S17 post-31dd3c0 (D21): the bridge's shared deadline must reach
    ``request.get()``, ``response.body()`` and the PDF text-extraction /
    normalization boundaries. A fake that ignores its timeout and advances
    the controlled clock past the deadline is caught at the next boundary as
    ``EvolutionPdfTimeoutError``."""

    def test_download_pdf_body_overrun_raises_typed_timeout(self) -> None:
        """R3.3: a response-body fake that advances the clock past the
        deadline produces a typed timeout in the bridge download path."""
        import time as time_mod
        from unittest.mock import patch

        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from tests.unit.test_persistent_evolution_pdf import _MonotonicClock

        clock = _MonotonicClock()

        class _Resp:
            ok = True
            status = 200

            def body(self) -> bytes:
                clock.advance(20.0)
                return b"%PDF-1.4 body"

        class _Req:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def get(self, url: str, **kwargs):
                self.calls.append((url, kwargs))
                return _Resp()

        class _Ctx:
            def __init__(self) -> None:
                self.request = _Req()

        class _Page:
            def __init__(self) -> None:
                self.context = _Ctx()

        page = _Page()
        bridge = RealHandleBridge.__new__(RealHandleBridge)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge._download_pdf(
                    page, "https://legacy.example/r.pdf", _pdf_deadline_s(5)
                )

        # The request received a bounded timeout (<= 5s budget).
        assert page.context.request.calls
        _, kwargs = page.context.request.calls[0]
        assert 1 <= kwargs["timeout"] <= 5_000

    def test_download_pdf_real_playwright_body_timeout_is_typed_no_sentinel(
        self,
    ) -> None:
        """R3.5/R3.6: a public real playwright TimeoutError from
        ``response.body()`` becomes a constant sanitized
        ``EvolutionPdfTimeoutError`` carrying no URL/cookie sentinel and no
        raw cause/context chain."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from tests.unit.test_persistent_evolution_pdf import (
            SENSITIVE_COOKIE_SENTINEL,
            SENSITIVE_URL_SENTINEL,
        )

        sentinel_msg = (
            f"Timeout at {SENSITIVE_URL_SENTINEL} "
            f"cookie={SENSITIVE_COOKIE_SENTINEL}"
        )

        class _Resp:
            ok = True
            status = 200

            def body(self) -> bytes:
                raise PlaywrightTimeoutError(sentinel_msg)

        class _Req:
            def get(self, url, **kwargs):  # noqa: ARG002
                return _Resp()

        class _Ctx:
            def __init__(self) -> None:
                self.request = _Req()

        class _Page:
            def __init__(self) -> None:
                self.context = _Ctx()

        bridge = RealHandleBridge.__new__(RealHandleBridge)

        with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
            bridge._download_pdf(
                _Page(), "https://legacy.example/r.pdf", _pdf_deadline_s(30)
            )

        outer = exc_info.value
        assert SENSITIVE_URL_SENTINEL not in str(outer)
        assert SENSITIVE_COOKIE_SENTINEL not in str(outer)
        assert outer.__cause__ is None
        assert outer.__context__ is None

    def test_action_flow_extraction_overrun_raises_typed_timeout(self) -> None:
        """R3.4: a PDF-text-extraction overrun inside the bridge action flow is
        caught at the next boundary as a typed timeout that propagates (it is
        NOT swallowed as a per-admission skip)."""
        import time as time_mod
        from unittest.mock import patch

        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from tests.unit.test_persistent_evolution_pdf import (
            REPRESENTATIVE_REPORT_TEXT,
            _MonotonicClock,
        )

        clock = _MonotonicClock()
        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        class _UrlLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                return "https://legacy.example/report.pdf"

        class _Req:
            def get(self, url, **kwargs):  # noqa: ARG002
                class _Resp:
                    ok = True

                    def body(self):
                        return b"%PDF-1.4 bytes"

                return _Resp()

        class _Ctx:
            def __init__(self) -> None:
                self.request = _Req()

        class _ReportPage:
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []
            context = _Ctx()

            def locator(self, selector):  # noqa: ARG002
                return _UrlLocator()

        def _slow_extract(_bytes):
            clock.advance(20.0)  # overrun the 5s budget
            return REPRESENTATIVE_REPORT_TEXT

        with (
            patch(
                "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.search_patient"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
                return_value=[{
                    "admissionKey": "K1",
                    "admissionStart": "2026-01-01",
                    "admissionEnd": "",
                    "ward": "",
                    "bed": "",
                }],
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.open_internacao_detail"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_evolucao"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.fill_evolution_dates"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.select_ascending_order"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.click_visualizar_report"
            ),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.wait_for_report_or_no_evolutions",
                return_value=True,
            ),
            patch.object(
                bridge, "_resolve_active_page", return_value=_ReportPage()
            ),
            patch.object(time_mod, "monotonic", clock.monotonic),
            patch(
                "apps.ingestion.extractors.real_handle_bridge.extract_pdf_text",
                _slow_extract,
            ),
        ):
            with pytest.raises(EvolutionPdfTimeoutError):
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                    timeout=5,
                )


class TestBridgeOverlapFailureSanitization:
    """PSW-S17 post-31dd3c0 (D22): the bridge must NOT retain the raw
    ``NavigationError`` in EITHER ``__cause__`` or ``__context__`` when
    wrapping a navigation failure into EvolutionPdfError. Raising ``from None``
    inside the ``except`` handler only suppresses *display* of the context;
    the reference is still attached. The wrapper must be raised OUTSIDE the
    handler."""

    def test_overlap_navigation_error_wrapped_no_cause_no_context(self) -> None:
        """choose_overlapping_admissions NavigationError surfaces as
        EvolutionPdfError with BOTH ``__cause__`` and ``__context__`` None
        (raised outside the handler), and the raw sentinel never leaks."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        handle = FakePlaywrightHandle()
        bridge = RealHandleBridge(handle)

        sentinel = "SENSITIVE_OVERLAP_DETAIL"
        with patch(
            "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.search_patient"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.click_internacoes"
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge._read_and_build_snapshot",
            return_value=[],
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.choose_overlapping_admissions",
            side_effect=NavigationError(sentinel),
        ), patch.object(
            bridge, "_resolve_active_page", return_value=MagicMock()
        ):
            with pytest.raises(EvolutionPdfError) as exc_info:
                bridge.extract_evolutions_via_legacy_actions(
                    patient_record="123",
                    start_date="2026-01-01",
                    end_date="2026-01-15",
                )

        outer = exc_info.value
        msg = str(outer)
        assert sentinel not in msg
        # D22: no cause AND no context chain carrying the raw navigation
        # error (``from None`` inside the handler would still leave
        # ``__context__`` set to the raw NavigationError).
        assert outer.__cause__ is None
        assert outer.__context__ is None
