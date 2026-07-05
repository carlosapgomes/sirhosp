"""Unit tests for persistent extraction adapter (PSW-S3).

Tests cover admission snapshot extraction through the persistent session
abstraction using fake browser/session objects — no real browser required.
"""

from __future__ import annotations

import pytest

from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.session_controller import (
    SessionControllerConfig,
)

# ---------------------------------------------------------------------------
# Synthetic HTML fixtures for admission snapshot data
# ---------------------------------------------------------------------------

_VALID_ADMISSIONS_JSON = """[
    {
        "admissionKey": "ADM-001",
        "admissionStart": "2024-01-15",
        "admissionEnd": "2024-01-20",
        "ward": "Enfermaria A",
        "bed": "001"
    },
    {
        "admissionKey": "ADM-002",
        "admissionStart": "2024-03-01",
        "admissionEnd": null,
        "ward": "UTI",
        "bed": "005"
    }
]"""

VALID_ADMISSION_PAGE_HTML = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="admission-snapshot-data">
{_VALID_ADMISSIONS_JSON}
</div>
</body>
</html>"""

EMPTY_ADMISSIONS_JSON = "[]"

EMPTY_ADMISSION_PAGE_HTML = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="admission-snapshot-data">
{EMPTY_ADMISSIONS_JSON}
</div>
</body>
</html>"""

MISSING_DATA_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<p>No admissions data found for this patient.</p>
</body>
</html>"""

INVALID_JSON_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="admission-snapshot-data">
{invalid json here}
</div>
</body>
</html>"""

WRONG_TYPE_JSON_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="admission-snapshot-data">
{"not_a_list": true}
</div>
</body>
</html>"""

VALID_COUNTER_HTML = r"""<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>"""

# Combined HTML with valid counter + admissions data
VALID_FULL_PAGE_HTML = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="admission-snapshot-data">
{_VALID_ADMISSIONS_JSON}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Fake session handle for persistent extraction adapter tests
# ---------------------------------------------------------------------------


class FakeExtractionSession:
    """Fake session handle for testing the persistent extraction adapter.

    Simulates page HTML, tab navigation, connection status, and records
    all interactions for assertion. Extends the pattern from PSW-S2 tests
    with extraction-specific features.
    """

    def __init__(self) -> None:
        self._html: str = ""
        self._html_by_url: dict[str, str] = {}
        self._connected: bool = True
        self._clicked_selectors: list[str] = []
        self._opened_urls: list[str] = []
        self._closed_tab_calls: int = 0
        self._restart_calls: int = 0
        self._open_tab_fail: bool = False
        self._tab_classes: list[str] = ["tabs-first tabs-last tabs-selected"]
        self._on_open_tab_cb = None
        self._last_open_timeout: int | None = None

    # --- Fake state mutators (test helpers) ---

    def set_html(self, html: str) -> None:
        self._html = html

    def set_html_for_url(self, url: str, html: str) -> None:
        """Set the HTML returned when a specific URL is navigated."""
        self._html_by_url[url] = html

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def fail_next_open_tab(self) -> None:
        """Make the next ``open_tab`` call return False."""
        self._open_tab_fail = True

    def set_on_open_tab(self, callback) -> None:
        """Register a callback invoked when ``open_tab`` is called.

        Useful for simulating page state changes (e.g. counter reset)
        after tab navigation.
        """
        self._on_open_tab_cb = callback

    def set_tab_classes(self, classes: list[str]) -> None:
        self._tab_classes = list(classes)

    # --- Interface implementation (SessionHandle protocol) ---

    def get_page_html(self) -> str:
        return self._html

    def is_connected(self) -> bool:
        return self._connected

    def click_selector(self, selector: str) -> None:
        self._clicked_selectors.append(selector)

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        self._opened_urls.append(url)
        self._last_open_timeout = timeout
        if self._open_tab_fail:
            return False
        # If there's a URL-specific HTML override, use it.
        if url in self._html_by_url:
            self._html = self._html_by_url[url]
        if self._on_open_tab_cb is not None:
            self._on_open_tab_cb()
        return True

    def get_tab_classes(self) -> list[str]:
        return list(self._tab_classes)

    def close_last_non_root_tab(self) -> None:
        self._closed_tab_calls += 1

    def restart_browser(self) -> None:
        self._restart_calls += 1
        self._connected = True

    # --- Test query helpers ---

    @property
    def clicked_selectors(self) -> list[str]:
        return list(self._clicked_selectors)

    @property
    def opened_urls(self) -> list[str]:
        return list(self._opened_urls)

    @property
    def closed_tab_calls(self) -> int:
        return self._closed_tab_calls

    @property
    def restart_calls(self) -> int:
        return self._restart_calls


# ===========================================================================
# Happy path: successful admission snapshot extraction
# ===========================================================================


class TestGetAdmissionSnapshot:
    """Tests for successful admission snapshot extraction."""

    def test_returns_normalized_admissions(self) -> None:
        """Extracts and normalizes admissions from session page HTML."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 2

        # First admission
        assert result[0]["admission_key"] == "ADM-001"
        assert result[0]["admission_start"] == "2024-01-15"
        assert result[0]["admission_end"] == "2024-01-20"
        assert result[0]["ward"] == "Enfermaria A"
        assert result[0]["bed"] == "001"

        # Second admission (open-ended)
        assert result[1]["admission_key"] == "ADM-002"
        assert result[1]["admission_end"] is None

    def test_empty_admissions_returns_empty_list(self) -> None:
        """Empty admissions snapshot returns empty list."""
        session = FakeExtractionSession()
        session.set_html(EMPTY_ADMISSION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 0

    def test_navigates_to_admissions_page_with_parameters(self) -> None:
        """Adapter opens a tab with patient_record and dates in the URL."""
        session = FakeExtractionSession()
        # Set counter HTML initially for ensure_ready / renew_if_needed checks
        session.set_html(
            f"<html><body>{VALID_COUNTER_HTML}</body></html>"
        )
        # After navigating to admissions URL, return the admission page.
        session.set_html_for_url(
            "/admissions/12345",
            VALID_ADMISSION_PAGE_HTML,
        )

        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}",
            ),
        )

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Should have opened the admissions tab
        admission_urls = [u for u in session.opened_urls if "/admissions/" in u]
        assert len(admission_urls) >= 1
        assert "/admissions/12345" in admission_urls[0]
        assert len(result) == 2

    def test_normalized_format_matches_existing_parser(self) -> None:
        """Normalized dict format matches AdmissionSnapshotParser output."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Verify canonical field names (matching AdmissionSnapshotParser)
        assert "admission_key" in result[0]
        assert "admission_start" in result[0]
        assert "admission_end" in result[0]
        assert "ward" in result[0]
        assert "bed" in result[0]

        # Verify no raw source fields leaked through
        assert "admissionKey" not in result[0]
        assert "admissionStart" not in result[0]


# ===========================================================================
# Session checkpoint tests
# ===========================================================================


class TestSessionCheckpoints:
    """Tests that session readiness/renewal checkpoints are called."""

    def test_ensure_ready_called_before_extraction(self) -> None:
        """ensure_ready() is called before navigating to admissions data."""
        session = FakeExtractionSession()
        # Set initial counter HTML so ensure_ready passes
        session.set_html(VALID_COUNTER_HTML)
        adapter = PersistentExtractionAdapter(session)

        # Track ensure_ready calls via a custom wrapper
        ensure_ready_called = False
        original_controller = adapter._controller
        original_ensure_ready = original_controller.ensure_ready

        def tracking_ensure_ready() -> bool:
            nonlocal ensure_ready_called
            ensure_ready_called = True
            return original_ensure_ready()

        original_controller.ensure_ready = tracking_ensure_ready  # type: ignore[assignment]

        # Set admission HTML for after ensure_ready passes
        session.set_html(VALID_ADMISSION_PAGE_HTML)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert ensure_ready_called, "ensure_ready() was not called before extraction"

    def test_renew_if_needed_called_before_extraction(self) -> None:
        """renew_if_needed() is called before navigating to admissions data."""
        session = FakeExtractionSession()
        session.set_html(VALID_COUNTER_HTML)
        adapter = PersistentExtractionAdapter(session)

        renew_called = False
        original_controller = adapter._controller
        original_renew = original_controller.renew_if_needed

        def tracking_renew() -> bool:
            nonlocal renew_called
            renew_called = True
            return original_renew()

        original_controller.renew_if_needed = tracking_renew  # type: ignore[assignment]

        session.set_html(VALID_ADMISSION_PAGE_HTML)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert renew_called, "renew_if_needed() was not called before extraction"

    def test_navigates_page_to_extract_admissions(self) -> None:
        """Adapter navigates to a page to obtain admission data."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Verify that some URL was navigated (opened a tab)
        assert len(session.opened_urls) >= 1

    def test_tab_cleanup_called_after_extraction(self) -> None:
        """close_job_tab_if_present is called after successful extraction."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        # Set up two tabs so cleanup will close the last non-root tab
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        adapter = PersistentExtractionAdapter(session)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # After success, tab should be cleaned up (close_job_tab_if_present)
        assert session.closed_tab_calls == 1

    def test_mark_job_processed_called_after_success(self) -> None:
        """mark_job_processed is called after successful extraction."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Controller should have tracked this as a processed job
        assert adapter._controller.jobs_processed == 1
        assert adapter._controller.consecutive_failures == 0


# ===========================================================================
# Failure modes
# ===========================================================================


class TestFailureModes:
    """Tests that session/extraction failures map to correct errors."""

    def test_ensure_ready_failure_raises_extraction_error(self) -> None:
        """When ensure_ready fails, ExtractionError is raised."""
        session = FakeExtractionSession()
        session.set_connected(False)  # Disconnected → ensure_ready fails
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(ExtractionError, match="Session not ready"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_renew_if_needed_failure_raises_extraction_error(self) -> None:
        """When renew_if_needed fails, ExtractionError is raised."""
        session = FakeExtractionSession()
        # Set counter HTML so ensure_ready passes
        session.set_html(VALID_COUNTER_HTML)
        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=99999,  # Force renewal attempt
                safe_renewal_tab_url="",  # No URL → renew fails
            ),
        )

        with pytest.raises(ExtractionError, match="Session renewal failed"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_missing_snapshot_data_raises_extraction_error(self) -> None:
        """Page has no admission-snapshot-data container → ExtractionError."""
        session = FakeExtractionSession()
        session.set_html(MISSING_DATA_HTML)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(ExtractionError, match="no data container"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        # No tab close on extraction failure
        assert session.closed_tab_calls == 0

    def test_invalid_json_raises_invalid_json_error(self) -> None:
        """Container has invalid JSON → InvalidJsonError."""
        session = FakeExtractionSession()
        session.set_html(INVALID_JSON_HTML)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(InvalidJsonError, match="Invalid JSON"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_wrong_json_type_raises_invalid_json_error(self) -> None:
        """Container has valid JSON but not a list → InvalidJsonError."""
        session = FakeExtractionSession()
        session.set_html(WRONG_TYPE_JSON_HTML)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(InvalidJsonError, match="must be a list"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_tab_open_failure_raises_extraction_error(self) -> None:
        """When open_tab fails, ExtractionError is raised."""
        session = FakeExtractionSession()
        session.set_html(
            f"<html><body>{VALID_COUNTER_HTML}</body></html>"
        )
        session.fail_next_open_tab()
        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}",
            ),
        )

        with pytest.raises(ExtractionError, match="Failed to navigate"):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_no_real_browser_launched(self) -> None:
        """Tests pass without any real browser — uses only fakes."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # No real browser objects involved
        assert len(result) == 2
        assert session.restart_calls == 0


# ===========================================================================
# Integration-style lifecycle with fakes
# ===========================================================================


class TestLifecycleWithFakes:
    """End-to-end lifecycle scenarios with fakes."""

    def test_full_lifecycle_session_checkpoints(self) -> None:
        """Full lifecycle: ensure_ready → renew → extract → cleanup → mark."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])

        # Simulate counter reset on safe tab open.
        session.set_on_open_tab(
            lambda: session.set_html(VALID_FULL_PAGE_HTML)
        )

        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )

        # Simulate low counter so renewal is triggered
        low_counter_admissions_html = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>05</span>:<span>00</span>
</div>
<div id="admission-snapshot-data">
{_VALID_ADMISSIONS_JSON}
</div>
</body>
</html>"""
        session.set_html(low_counter_admissions_html)

        result = adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Extraction succeeded
        assert len(result) == 2

        # Tab cleanup performed
        assert session.closed_tab_calls >= 1

        # Job marked
        assert adapter._controller.jobs_processed == 1

    def test_recovery_path_on_failure(self) -> None:
        """When extraction fails due to data error, no tab close occurs."""
        session = FakeExtractionSession()
        session.set_html(MISSING_DATA_HTML)  # No snapshot data container
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(ExtractionError):
            adapter.get_admission_snapshot(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        # Data extraction failure is NOT a session failure — counter stays 0
        assert adapter._controller.consecutive_failures == 0

        # No tab close on data extraction failure
        assert session.closed_tab_calls == 0


# ===========================================================================
# Timeout propagation to the session handle
# ===========================================================================


class TestTimeoutPropagationToHandle:
    """Tests that the adapter forwards ``timeout`` to the handle's open_tab."""

    def test_timeout_reaches_session_handle(self) -> None:
        """The timeout kwarg is propagated to ``SessionHandle.open_tab``."""
        session = FakeExtractionSession()
        session.set_html(VALID_FULL_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        adapter.get_admission_snapshot(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
            timeout=60,
        )

        assert session._last_open_timeout == 60


# ===========================================================================
# Default configuration
# ===========================================================================


class TestDefaultConfig:
    """Tests for default adapter configuration."""

    def test_default_config_is_conservative(self) -> None:
        """Adapter uses conservative defaults."""
        session = FakeExtractionSession()
        adapter = PersistentExtractionAdapter(session)
        assert adapter._controller.config.max_jobs_per_session == 50
        assert adapter._controller.config.max_lifetime_seconds == 3600
        assert adapter._controller.config.max_consecutive_failures == 3
        assert adapter._controller.config.renewal_threshold_seconds == 600


# ===========================================================================
# Evolution extraction (PSW-S5)
# ===========================================================================

_VALID_EVOLUTIONS_JSON = (
    '['
    '{"admissionKey": "ADM-001",'
    ' "happened_at": "2024-01-16T10:30:00",'
    ' "event_type": "medical_evolution",'
    ' "content": "Patient stable, vital signs normal.",'
    ' "profession": "medica"},'
    '{"admissionKey": "ADM-001",'
    ' "happened_at": "2024-01-17T14:00:00",'
    ' "event_type": "nursing_evolution",'
    ' "content": "Dressing changed, wound healing well.",'
    ' "profession": "enfermagem"}'
    ']'
)

EVOLUTION_PAGE_HTML = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="evolution-data">
{_VALID_EVOLUTIONS_JSON}
</div>
</body>
</html>"""

EMPTY_EVOLUTIONS_JSON = "[]"

EMPTY_EVOLUTION_PAGE_HTML = f"""<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="evolution-data">
{EMPTY_EVOLUTIONS_JSON}
</div>
</body>
</html>"""

MISSING_EVOLUTION_DATA_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<p>No evolution data found.</p>
</body>
</html>"""

INVALID_EVOLUTION_JSON_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="evolution-data">
{invalid json here}
</div>
</body>
</html>"""


class TestExtractEvolutions:
    """Tests for persistent extract_evolutions."""

    def test_returns_normalized_evolutions(self) -> None:
        """Extracts and returns normalized evolutions from session page HTML."""
        session = FakeExtractionSession()
        session.set_html(EVOLUTION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["admission_key"] == "ADM-001"
        assert result[1]["admission_key"] == "ADM-001"

    def test_empty_evolutions_returns_empty_list(self) -> None:
        """Empty evolutions data returns empty list."""
        session = FakeExtractionSession()
        session.set_html(EMPTY_EVOLUTION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        result = adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(result, list)
        assert len(result) == 0

    def test_navigates_with_timeout(self) -> None:
        """Timeout is propagated to the session handle."""
        session = FakeExtractionSession()
        session.set_html(EVOLUTION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
            timeout=60,
        )

        assert session._last_open_timeout == 60

    def test_missing_evolution_data_container_raises_extraction_error(self) -> None:
        """Page missing evolution-data container raises ExtractionError."""
        session = FakeExtractionSession()
        session.set_html(MISSING_EVOLUTION_DATA_HTML)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(ExtractionError, match="no data container"):
            adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_invalid_json_raises_invalid_json_error(self) -> None:
        """Invalid JSON in evolution container raises InvalidJsonError."""
        session = FakeExtractionSession()
        session.set_html(INVALID_EVOLUTION_JSON_HTML)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(InvalidJsonError):
            adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_ensure_ready_called_before_extraction(self) -> None:
        """ensure_ready() checkpoint is called before evolution extraction."""
        session = FakeExtractionSession()
        session.set_html(EVOLUTION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        ensure_ready_called = False
        original = adapter._controller.ensure_ready

        def track() -> bool:
            nonlocal ensure_ready_called
            ensure_ready_called = True
            return original()

        adapter._controller.ensure_ready = track  # type: ignore[assignment]

        adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert ensure_ready_called

    def test_tab_cleanup_called_after_extraction(self) -> None:
        """close_job_tab_if_present is called after successful extraction."""
        session = FakeExtractionSession()
        session.set_html(EVOLUTION_PAGE_HTML)
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        adapter = PersistentExtractionAdapter(session)

        adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert session.closed_tab_calls == 1

    def test_mark_job_processed_called_after_success(self) -> None:
        """mark_job_processed is called after successful extraction."""
        session = FakeExtractionSession()
        session.set_html(EVOLUTION_PAGE_HTML)
        adapter = PersistentExtractionAdapter(session)

        adapter.extract_evolutions(
            patient_record="12345",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert adapter._controller.jobs_processed == 1

    def test_session_failure_before_extraction_raises_extraction_error(self) -> None:
        """Session not ready raises ExtractionError before evolution extraction."""
        session = FakeExtractionSession()
        session.set_connected(False)
        adapter = PersistentExtractionAdapter(session)

        with pytest.raises(ExtractionError, match="Session not ready"):
            adapter.extract_evolutions(
                patient_record="12345",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
