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

from apps.ingestion.extractors.persistent_extraction_adapter import (
    _ADMISSION_DATA_DIV_ID,
    _DATA_CONTAINER_RE,
    _EVOLUTION_DATA_CONTAINER_RE,
    _EVOLUTION_DATA_DIV_ID,
)
from tests.unit.test_legacy_navigation import (  # noqa: PLC0415
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

    def close_last_non_root_tab(self) -> None:
        self._closed_tab_calls += 1

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
        """Full adapter.extract_evolutions() succeeds with bridge output."""
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

        # Replace handle HTML with legacy evolution JSON before navigation
        handle.set_html(LEGACY_EVOLUTIONS_PAGE_JSON)

        result = adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 2
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

            def close_last_non_root_tab(self) -> None:
                self._closed += 1

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

    def test_adapter_uses_legacy_actions_when_yield_no_json_events(
        self,
    ) -> None:
        """Adapter calls legacy action flow when fast paths yield no events
        and the session supports it."""
        # Import helper to generate valid PDF bytes inline
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )
        from tests.unit.test_persistent_evolution_pdf import (  # noqa: PLC0415
            REPRESENTATIVE_REPORT_TEXT,
            _build_pdf_bytes,
        )

        handle = FakePlaywrightHandle()

        # Return HTML with NO evolution data (empty container)
        # so fast paths yield []
        handle.set_html(
            '<html><body>'
            '<div id="tempoSessao"><span>00</span>:<span>27</span>:'
            '<span>30</span></div>'
            '<div id="evolution-data">[]</div>'
            '</body></html>'
        )

        valid_pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)

        mock_row_locator = MagicMock()
        mock_row_locator.wait_for = MagicMock()
        initial_frame = MagicMock()
        initial_frame.locator.return_value = mock_row_locator
        initial_frame.eval_on_selector_all.return_value = [
            {
                "dataRi": "0",
                "dataRk": "ADM-RK-001",
                "cells": ["15/01/2024", "20/01/2024", "A", "B",
                          "Detalhes"],
                "hasDetailsLink": True,
            },
        ]
        # Configure the frame to appear as a report page immediately
        # so wait_for_report_or_no_evolutions does NOT poll for 120s.
        def frame_side_effect(name):
            nonlocal initial_frame
            return initial_frame

        page = MagicMock()
        page.frame.side_effect = frame_side_effect
        page.content.return_value = (
            '<html><body>'
            '<object type="application/pdf" '
            'data="https://example.com/report.pdf"></object>'
            '</body></html>'
        )
        page.url = "https://legacy.example.com/"
        page.context.request.get.return_value.ok = True
        page.context.request.get.return_value.body.return_value = (
            valid_pdf_bytes
        )

        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(
            bridge,
            config=SessionControllerConfig(
                base_evolutions_url="/evolutions/{patient_record}",
            ),
        )

        # Fast paths yield [] via the empty evolution-data container
        # (open_tab -> bridge get_page_html -> evolution-data div -> []);
        # PDF fallback (extract_evolutions_pdf) exists on the bridge;
        # legacy action fallback (extract_evolutions_via_legacy_actions)
        # also exists. With fakes, the action path proceeds through
        # admissions selection, downloads a valid PDF via the existing
        # context, extracts text, normalises, and returns events.
        result = adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_existing_json_fast_path_still_works(self) -> None:
        """Adapter still uses JSON script tag fast path when present."""
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

        # JSON fast path should return events
        assert len(result) >= 1

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
        page.content.return_value = (
            "<html><body>"
            '<object type="application/pdf" '
            'data="https://example.com/report.pdf"></object>'
            "</body></html>"
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

        # Session where fast paths yield [] (empty evolution-data) and the
        # PSW-S11 PDF fallback also yields [], so the adapter reaches the
        # PSW-S13 legacy action fallback. The action method returns a
        # single known event in the 5-key contract.
        session = MagicMock()
        session.is_connected.return_value = True
        session.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        session.open_tab.return_value = True
        session.get_page_html.return_value = (
            "<html><body>"
            '<div id="tempoSessao">'
            "<span>00</span>:<span>29</span>:<span>01</span>"
            "</div>"
            '<div id="evolution-data">[]</div>'
            "</body></html>"
        )
        session.extract_evolutions_pdf.return_value = []
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
