"""Tests for RealHandleBridge (PSW-S9).

Prove that the bridge can translate real legacy UI HTML/download data into
the synthetic container format expected by ``PersistentExtractionAdapter``,
without requiring the real legacy DOM to produce ``#admission-snapshot-data``
and ``#evolution-data`` containers.

All tests use mocked Playwright pages or synthetic anonymous HTML.
No real legacy access required.
"""

from __future__ import annotations

import json

from apps.ingestion.extractors.persistent_extraction_adapter import (
    _ADMISSION_DATA_DIV_ID,
    _DATA_CONTAINER_RE,
    _EVOLUTION_DATA_CONTAINER_RE,
    _EVOLUTION_DATA_DIV_ID,
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
