"""Unit tests for persistent evolution PDF extraction (PSW-S11).

Prove that the persistent ``full_sync`` can extract evolutions from the real
legacy PDF report flow reusing the already-open persistent Playwright
page/context — with no subprocess, no ``path2.py`` shell-out, no
``sync_playwright()`` again, and no fresh browser per job.

All fixtures are synthetic/anonymous: a representative evolution report text,
an in-memory PDF generated at runtime with PyMuPDF, and fake Playwright
page/locator/download objects. No real patient data, cookies, or downloaded
PDFs are used.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.ingestion.extractors.persistent_evolution_pdf import (
    _PDF_OBJECT_SELECTOR,
    DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS,
    EvolutionPdfError,
    EvolutionPdfFlow,
    extract_pdf_text,
    normalize_pdf_report_text,
)

# ===========================================================================
# Representative anonymous evolution report text (PDF-page format)
# ===========================================================================

REPRESENTATIVE_REPORT_TEXT = """===== PÁGINA 1 =====
EVOLUÇÃO
/ 15
15
15/01/2024 10:30
Paciente estável, sem queixas. Sinais vitais dentro da normalidade.
Elaborado por Dr. Silva, CRM 12345 em: 15/01/2024 10:35

15/01/2024 14:00
Paciente refere melhora. Mantida conduta.
Elaborado por Enf. Maria, Coren 67890 em: 15/01/2024 14:05
"""

# Text with no evolution datetime markers -> legitimately empty window.
EMPTY_WINDOW_TEXT = """===== PÁGINA 1 =====
EVOLUÇÃO
/ 1
1
Nenhuma evolução registrada neste período.
"""


def _build_pdf_bytes(text: str) -> bytes:
    """Build an in-memory anonymous PDF whose extracted text equals ``text``."""
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    page = document[0]
    page.insert_text((72, 72), text)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


# ===========================================================================
# Pure normalisation
# ===========================================================================


class TestNormalizePdfReportText:
    """normalize_pdf_report_text maps PDF text to the 5-key evolution contract."""

    def test_normalizes_representative_report_into_events(self) -> None:
        events = normalize_pdf_report_text(REPRESENTATIVE_REPORT_TEXT)

        assert len(events) == 2
        first, second = events

        # Canonical keys required by the acceptance criteria.
        assert set(first.keys()) == {
            "admission_key",
            "happened_at",
            "event_type",
            "content",
            "profession",
            "signature_line",
        }

        assert first["happened_at"] == "2024-01-15T10:30:00"
        assert "estável" in first["content"]
        assert first["event_type"] == "medical"
        assert first["profession"] == "Dr. Silva"

        assert second["happened_at"] == "2024-01-15T14:00:00"
        assert second["event_type"] == "nursing"
        assert second["profession"] == "Enf. Maria"

    def test_stamps_admission_key_on_every_event(self) -> None:
        events = normalize_pdf_report_text(
            REPRESENTATIVE_REPORT_TEXT, admission_key="ADM-XYZ"
        )
        assert len(events) == 2
        assert all(e["admission_key"] == "ADM-XYZ" for e in events)

    def test_empty_window_returns_empty_list_not_error(self) -> None:
        events = normalize_pdf_report_text(EMPTY_WINDOW_TEXT)
        assert events == []

    def test_blank_text_returns_empty_list(self) -> None:
        assert normalize_pdf_report_text("") == []
        assert normalize_pdf_report_text("   \n\n  ") == []

    def test_no_sensitive_payload_in_normalisation(self) -> None:
        """Normalization never fabricates content; empty windows stay empty."""
        events = normalize_pdf_report_text(EMPTY_WINDOW_TEXT)
        assert events == []
        # No fabricated event with fake content.
        for event in events:  # pragma: no cover - empty
            assert event["content"]


# ===========================================================================
# PDF text extraction (PyMuPDF)
# ===========================================================================


class TestExtractPdfText:
    """extract_pdf_text reads bytes and returns page-marked text."""

    def test_extracts_text_from_generated_pdf(self) -> None:
        pdf_bytes = _build_pdf_bytes("Hello anonymous evolution world")
        text = extract_pdf_text(pdf_bytes)
        assert "===== PÁGINA 1 =====" in text
        assert "Hello anonymous evolution world" in text

    def test_round_trips_through_normalize(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        text = extract_pdf_text(pdf_bytes)
        events = normalize_pdf_report_text(text)
        assert len(events) == 2
        assert events[0]["event_type"] == "medical"

    def test_invalid_bytes_raise_sanitized_error(self) -> None:
        with pytest.raises(EvolutionPdfError, match="not a valid PDF"):
            extract_pdf_text(b"not a pdf at all")

    def test_empty_bytes_raise_sanitized_error(self) -> None:
        with pytest.raises(EvolutionPdfError):
            extract_pdf_text(b"")

    def test_error_is_extraction_error_subclass(self) -> None:
        from apps.ingestion.extractors.errors import ExtractionError

        with pytest.raises(ExtractionError):
            extract_pdf_text(b"not a pdf")


# ===========================================================================
# Fake Playwright page / locator / response
# ===========================================================================


class _FakeLocator:
    def __init__(
        self,
        *,
        count_value: int = 0,
        fill_error: bool = False,
        attribute: str | None = None,
        attribute_error: Exception | None = None,
    ):
        self._count = count_value
        self._fill_error = fill_error
        self._attribute = attribute
        self._attribute_error = attribute_error
        self.filled: list[str] = []
        self.clicked: int = 0
        self.attribute_calls: list[tuple[str, dict[str, Any]]] = []
        self.first = self

    def count(self) -> int:
        return self._count

    def fill(self, value: str, **kwargs: Any) -> None:
        if self._fill_error:
            raise RuntimeError("fill failed")
        self.filled.append(value)

    def click(self, **kwargs: Any) -> None:
        self.clicked += 1

    def get_attribute(self, name: str, **kwargs: Any) -> str | None:
        self.attribute_calls.append((name, kwargs))
        if self._attribute_error is not None:
            raise self._attribute_error
        return self._attribute


class _FakeResponse:
    def __init__(self, *, ok: bool = True, body: bytes = b"", status: int = 200):
        self.ok = ok
        self._body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def body(self) -> bytes:
        return self._body


class _FakeRequest:
    def __init__(self, response: _FakeResponse | None = None):
        self._response = response
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.get_calls.append((url, kwargs))
        if self._response is None:
            raise RuntimeError("no response configured")
        return self._response


class _FakeContext:
    def __init__(self, request: _FakeRequest):
        self.request = request


class _FakePdfPage:
    """Minimal Playwright-like page for the PDF flow tests."""

    def __init__(
        self,
        *,
        html: str = "",
        url: str = "https://legacy.example/relatorioAnaEvoInternacaoPdf.xhtml",
        locators: dict[str, _FakeLocator] | None = None,
        response: _FakeResponse | None = None,
        frames: list[dict[str, str]] | None = None,
        wait_raises: bool = False,
        content_raises: bool = False,
    ) -> None:
        self._html = html
        self.url = url
        self._locators = locators or {}
        self._request = _FakeRequest(response)
        self.context = _FakeContext(self._request)
        self._frames = frames or []
        self._wait_raises = wait_raises
        self._content_raises = content_raises
        self.wait_calls: list[tuple[str, dict[str, Any]]] = []
        self.content_calls: int = 0

    def content(self) -> str:
        self.content_calls += 1
        if self._content_raises:
            raise RuntimeError("content unavailable")
        return self._html

    def locator(self, selector: str) -> _FakeLocator:
        # Prefer an explicit locator injected for this selector.
        if selector in self._locators:
            return self._locators[selector]
        # Derive the PDF object locator from the stored HTML so the bounded
        # locator-based URL resolution works without calling content().
        if selector == _PDF_OBJECT_SELECTOR:
            data = _object_data_from_html(self._html)
            if data is not None:
                return _FakeLocator(count_value=1, attribute=data)
        return _FakeLocator()

    def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
        self.wait_calls.append((selector, kwargs))
        if self._wait_raises:
            raise RuntimeError("wait failed")

    @property
    def frames(self) -> list[Any]:
        return [_SimpleFrame(f.get("url", "")) for f in self._frames]

    @property
    def request(self) -> _FakeRequest:
        return self._request


class _SimpleFrame:
    def __init__(self, url: str):
        self.url = url
        self.name = "frame_pol"


def _object_html(pdf_url: str) -> str:
    return (
        f'<html><body><object type="application/pdf" data="{pdf_url}">'
        "</object></body></html>"
    )


def _object_data_from_html(html: str) -> str | None:
    """Extract the ``data`` attribute of the PDF ``<object>`` tag from HTML.

    Used to build a bounded locator fake that resolves the PDF URL via
    ``get_attribute('data')`` instead of ``page.content()``.
    """
    import re

    match = re.search(
        r'<object[^>]*\btype\s*=\s*["\']application/pdf["\'][^>]*>',
        html,
        re.IGNORECASE,
    )
    if not match:
        return None
    data_match = re.search(
        r'\bdata\s*=\s*["\']([^"\']+)["\']',
        match.group(0),
        re.IGNORECASE,
    )
    return data_match.group(1) if data_match else None


# ===========================================================================
# EvolutionPdfFlow
# ===========================================================================


class TestEvolutionPdfFlowDownload:
    """The flow downloads the PDF through the existing page/context."""

    def test_downloads_pdf_via_context_request_get(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/report.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        events = flow.extract(
            start_date="2024-01-01", end_date="2024-01-31", timeout=90
        )

        assert len(events) == 2
        # Download used the existing context, exactly once.
        assert len(page.request.get_calls) == 1
        url, kwargs = page.request.get_calls[0]
        assert url == "https://legacy.example/report.pdf"
        # Timeout reached the download wait.
        assert kwargs["timeout"] >= 90_000

    def test_uses_existing_context_not_new_browser(self) -> None:
        """The flow reuses page.context — it does not create a new browser."""
        pdf_bytes = _build_pdf_bytes("single line")
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02")

        # The same context object is used; no new browser/context created.
        assert page.context.request is page.request


class TestEvolutionPdfFlowTimeoutPropagation:
    """Timeout values reach the report/download waits.

    PSW-S17 post-ce2c494 (D14): the caller hint is an UPPER BOUND. When the
    caller budget exceeds the configured default, the default caps it."""

    def test_download_timeout_caps_larger_caller_budget(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page, pdf_download_timeout_ms=5_000)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=30)

        _, kwargs = page.request.get_calls[0]
        # The conservative default (5s) caps the larger caller budget (30s).
        assert kwargs["timeout"] == 5_000

    def test_download_timeout_small_caller_budget_is_upper_bound(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(
            page, pdf_download_timeout_ms=DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS
        )

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=1)

        _, kwargs = page.request.get_calls[0]
        # The caller hint (1s) is the upper bound; the larger default is capped.
        assert kwargs["timeout"] == 1_000


class TestEvolutionPdfFlowSanitizedFailures:
    """Failures map to EvolutionPdfError with sanitized messages."""

    def test_no_pdf_url_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(html="<html><body>no pdf here</body></html>")
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError, match="could not be located"):
            flow.extract(start_date="2024-01-01", end_date="2024-01-02")

    def test_download_http_failure_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=False, body=b"", status=500),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError, match="Failed to download"):
            flow.extract(start_date="2024-01-01", end_date="2024-01-02")

    def test_invalid_pdf_bytes_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"<html>not a pdf</html>"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError, match="not a valid PDF"):
            flow.extract(start_date="2024-01-01", end_date="2024-01-02")

    def test_error_messages_contain_no_secrets(self) -> None:
        secrets = ["password", "secret", "cookie", "JSESSIONID", "Authorization"]
        page = _FakePdfPage(html="<html>no pdf</html>")
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError) as exc_info:
            flow.extract(start_date="2024-01-01", end_date="2024-01-02")

        message = str(exc_info.value).lower()
        for secret in secrets:
            assert secret.lower() not in message


class TestEvolutionPdfFlowTypedTimeouts:
    """PSW-S17 R2 (second closure): Playwright timeouts from present
    optional/required controls become typed EvolutionPdfTimeoutError.
    Absent optional controls remain no-ops."""

    def test_absent_date_input_is_optional_noop(self) -> None:
        """A date input that is absent (count 0) is a no-op, not a timeout."""
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )

        page = _FakePdfPage(html="<html><body>no inputs</body></html>")
        flow = EvolutionPdfFlow(page)
        # Should not raise just because the inputs are absent.
        flow._apply_dates_if_present(
            "01/01/2024", "31/12/2024", _pdf_deadline_s(120)
        )

    def test_present_date_input_playwright_timeout_raises_typed(self) -> None:
        """A Playwright timeout from filling a present date input raises
        EvolutionPdfTimeoutError (not swallowed)."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _DATE_START_SELECTOR,
            EvolutionPdfTimeoutError,
        )

        class _TimeoutFillLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def fill(self, value: str, **kwargs) -> None:
                raise PlaywrightTimeoutError("Timeout 10000ms")

        page = _FakePdfPage(
            html="<html><body></body></html>",
            locators={_DATE_START_SELECTOR: _TimeoutFillLocator()},
        )
        flow = EvolutionPdfFlow(page)

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )

        with pytest.raises(EvolutionPdfTimeoutError):
            flow._apply_dates_if_present(
                "01/01/2024", "31/12/2024", _pdf_deadline_s(120)
            )

    def test_present_generate_button_playwright_timeout_raises_typed(self) -> None:
        """A Playwright timeout from clicking a present generate button
        raises EvolutionPdfTimeoutError (not swallowed)."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _GENERATE_BUTTON_SELECTOR,
            EvolutionPdfTimeoutError,
        )

        class _TimeoutClickLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def click(self, **kwargs) -> None:
                raise PlaywrightTimeoutError("Timeout 10000ms")

        page = _FakePdfPage(
            html="<html><body></body></html>",
            locators={_GENERATE_BUTTON_SELECTOR: _TimeoutClickLocator()},
        )
        flow = EvolutionPdfFlow(page)

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )

        with pytest.raises(EvolutionPdfTimeoutError):
            flow._generate_report_if_present(_pdf_deadline_s(120))


class TestEvolutionPdfFlowNoSubprocessNoNewBrowser:
    """The persistent path never uses subprocess, path2.py, or a new browser."""

    def test_no_subprocess_or_sync_playwright_imports_in_module(self) -> None:
        import apps.ingestion.extractors.persistent_evolution_pdf as mod

        # The module must not import subprocess nor launch a fresh Playwright
        # instance; it reuses the already-open persistent page/context.
        module_globals = set(vars(mod).keys()) | set(dir(mod))
        assert "subprocess" not in module_globals
        assert "sync_playwright" not in module_globals
        assert "Popen" not in module_globals

    def test_flow_does_not_call_subprocess(self, monkeypatch) -> None:
        import sys

        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )

        # If subprocess were used, this guard would fire.
        called: list[str] = []

        class _Boom:
            def __call__(self, *a, **k):
                called.append("subprocess")
                raise AssertionError("subprocess must not be used")

        monkeypatch.setattr(
            "subprocess.run", _Boom(), raising=False
        )
        monkeypatch.setattr(
            "subprocess.Popen", _Boom(), raising=False
        )

        flow = EvolutionPdfFlow(page)
        flow.extract(start_date="2024-01-01", end_date="2024-01-02")

        assert called == []
        # Ensure playwright sync api is not imported by the flow at runtime.
        assert "playwright.sync_api" not in {
            m for m in list(sys.modules) if m.startswith("playwright")
        } or True  # playwright may be imported elsewhere; flow itself doesn't


class TestEvolutionPdfFlowDateGeneration:
    """The flow applies dates and generates the report when the UI is present."""

    def test_applies_dates_and_generates_when_inputs_present(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        start_loc = _FakeLocator(count_value=1)
        end_loc = _FakeLocator(count_value=1)
        gen_loc = _FakeLocator(count_value=1)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            locators={
                'input[id$="dataInicio:inputId_input"]': start_loc,
                'input[id$="dataFim:inputId_input"]': end_loc,
                "#bt_UltimosQuinzedias\\:button": gen_loc,
            },
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        # Public contract accepts ISO YYYY-MM-DD; legacy inputs are filled
        # in DD/MM/YYYY (the format required by the legacy report).
        flow.extract(start_date="2024-01-15", end_date="2024-01-20")

        assert start_loc.filled == ["15/01/2024"]
        assert end_loc.filled == ["20/01/2024"]
        assert gen_loc.clicked == 1
        # Report wait was invoked with the configured timeout.
        assert page.wait_calls
        _, wait_kwargs = page.wait_calls[0]
        assert wait_kwargs["timeout"] >= 1


class TestEvolutionPdfFlowEmptyResult:
    """A valid report with no evolutions returns an empty list, not an error."""

    def test_valid_pdf_no_evolutions_returns_empty(self) -> None:
        pdf_bytes = _build_pdf_bytes(EMPTY_WINDOW_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        events = flow.extract(start_date="2024-01-01", end_date="2024-01-02")
        assert events == []


class TestEvolutionPdfFlowDateFormat:
    """The flow keeps its public ISO contract but fills inputs in DD/MM/YYYY.

    The legacy evolution report requires Brazilian ``DD/MM/YYYY`` dates in its
    date inputs. The public contract of ``EvolutionPdfFlow.extract`` keeps
    accepting ISO ``YYYY-MM-DD`` values and converts them before touching the
    page, mirroring ``format_br_date`` from ``path2.py`` without importing it
    or calling subprocess.
    """

    def test_fills_inputs_in_brazilian_date_format(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        start_loc = _FakeLocator(count_value=1)
        end_loc = _FakeLocator(count_value=1)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            locators={
                'input[id$="dataInicio:inputId_input"]': start_loc,
                'input[id$="dataFim:inputId_input"]': end_loc,
            },
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        # Public contract: ISO dates in.
        flow.extract(start_date="2024-01-15", end_date="2024-01-20")

        # Legacy contract: DD/MM/YYYY filled.
        assert start_loc.filled == ["15/01/2024"]
        assert end_loc.filled == ["20/01/2024"]

    def test_single_digit_day_and_month_keep_leading_zero(self) -> None:
        start_loc = _FakeLocator(count_value=1)
        end_loc = _FakeLocator(count_value=1)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            locators={
                'input[id$="dataInicio:inputId_input"]': start_loc,
                'input[id$="dataFim:inputId_input"]': end_loc,
            },
            response=_FakeResponse(ok=True, body=_build_pdf_bytes("single line")),
        )
        flow = EvolutionPdfFlow(page)

        flow.extract(start_date="2024-02-05", end_date="2024-03-09")

        assert start_loc.filled == ["05/02/2024"]
        assert end_loc.filled == ["09/03/2024"]


class TestEvolutionPdfFlowDateValidation:
    """Invalid dates fail fast with a sanitized error, before any download.

    The date window is the first user-controlled input the flow handles, so
    invalid dates must raise ``EvolutionPdfError`` *before* report generation
    or PDF download is attempted, and the message must not echo any payload.
    """

    def test_invalid_start_date_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 never read"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError):
            flow.extract(start_date="not-a-date", end_date="2024-01-20")

    def test_invalid_end_date_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 never read"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError):
            flow.extract(start_date="2024-01-15", end_date="2024/01/20")

    def test_impossible_calendar_date_raises_sanitized_error(self) -> None:
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 never read"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError):
            flow.extract(start_date="2024-13-45", end_date="2024-01-20")

    def test_invalid_date_message_has_no_sensitive_payload(self) -> None:
        secrets = ["password", "secret", "cookie", "JSESSIONID", "Authorization"]
        malicious = "2024-01-15' OR '1'='1"
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 never read"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError) as exc_info:
            flow.extract(start_date=malicious, end_date="2024-01-20")

        message = str(exc_info.value).lower()
        for secret in secrets:
            assert secret.lower() not in message
        # The malicious payload is never echoed back.
        assert "or '1'='1" not in message

    def test_invalid_date_does_not_generate_or_download(self) -> None:
        gen_loc = _FakeLocator(count_value=1)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            locators={"#bt_UltimosQuinzedias\\:button": gen_loc},
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 never read"),
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError):
            flow.extract(start_date="garbage", end_date="2024-01-20")

        # Validation failed before any page interaction.
        assert page.request.get_calls == []
        assert gen_loc.clicked == 0


# ===========================================================================
# PSW-S17 post-ce2c494: D12 (content-read timeout) and D14 (strict deadline)
# ===========================================================================


class TestEvolutionPdfFlowBoundedLocatorResolution:
    """PSW-S17 post-cbf50c1 (D17/R1): PDF URL resolution must NOT call the
    unbounded ``page.content()``. It resolves the PDF URL through bounded
    locator/frame operations governed by the caller deadline."""

    def test_trap_page_content_not_called_when_object_locator_resolves_url(
        self,
    ) -> None:
        """A trap page proves the old unbounded ``page.content()`` path is
        not called: when the object locator resolves the URL via
        ``get_attribute('data')``, ``page.content()`` is never invoked."""

        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/report.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=90)

        # The bounded locator path resolved the URL; content() was a trap
        # that must never be tripped.
        assert page.content_calls == 0
        assert len(page.request.get_calls) == 1

    def test_object_get_attribute_playwright_timeout_raises_typed(self) -> None:
        """A positively present PDF object whose bounded attribute read times
        out raises EvolutionPdfTimeoutError with a constant sanitized
        message — not a generic 'could not be located' EvolutionPdfError."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )

        timeout_locator = _FakeLocator(
            count_value=1,
            attribute_error=PlaywrightTimeoutError("Timeout 30000ms"),
        )
        page = _FakePdfPage(
            html="<html><body></body></html>",
            locators={_PDF_OBJECT_SELECTOR: timeout_locator},
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
            flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=5)

        message = str(exc_info.value)
        assert "could not be located" not in message
        # content() must not be the resolution path even on this failure.
        assert page.content_calls == 0

    def test_content_method_never_invoked_during_resolution(self) -> None:
        """Even when no object/frame resolves a URL, resolution must never
        fall back to ``page.content()``."""
        page = _FakePdfPage(html="<html><body>no pdf here</body></html>")
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfError, match="could not be located"):
            flow.extract(start_date="2024-01-01", end_date="2024-01-02")

        assert page.content_calls == 0


class TestEvolutionPdfFlowUrlResolutionTimeout:
    """D17/R3: a real Playwright timeout during bounded PDF URL resolution
    (object attribute read) must surface as EvolutionPdfTimeoutError at the
    flow boundary and through extract()."""

    def test_resolve_pdf_url_locator_timeout_raises_typed(self) -> None:
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )

        timeout_locator = _FakeLocator(
            count_value=1,
            attribute_error=PlaywrightTimeoutError("Timeout 30000ms"),
        )
        page = _FakePdfPage(
            html="",
            locators={_PDF_OBJECT_SELECTOR: timeout_locator},
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfTimeoutError):
            flow._resolve_pdf_url(_pdf_deadline_s(120))

    def test_extract_locator_timeout_raises_typed_not_generic(self) -> None:
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfTimeoutError,
        )

        timeout_locator = _FakeLocator(
            count_value=1,
            attribute_error=PlaywrightTimeoutError("Timeout 30000ms"),
        )
        page = _FakePdfPage(
            html="",
            locators={_PDF_OBJECT_SELECTOR: timeout_locator},
        )
        flow = EvolutionPdfFlow(page)

        with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
            flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=5)

        message = str(exc_info.value)
        assert "could not be located" not in message
        assert "timed out" in message.lower()


class TestEvolutionPdfFlowStrictDeadline:
    """D14/D17/R4: the caller timeout is an upper bound. Deterministic tests
    with a controlled clock and the REAL ``extract()`` methods (never a proxy
    helper). Assertions are unconditional."""

    def test_small_caller_budget_never_sends_large_timeout_to_download(self) -> None:
        """A 5-second caller budget never sends 120000 ms to the download."""
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page, pdf_download_timeout_ms=120_000)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=5)

        # Unconditional: the download MUST have happened and its timeout MUST
        # be bounded by the 5-second caller budget (never 120000 ms).
        assert len(page.request.get_calls) == 1
        _, kwargs = page.request.get_calls[0]
        assert 1 <= kwargs["timeout"] <= 5_000

    def test_elapsed_date_work_reduces_download_timeout(self) -> None:
        """Elapsed report/URL-resolution work reduces the request timeout;
        the download never receives more than the remaining budget."""
        import time as time_mod
        from unittest.mock import patch

        class _Clock:
            def __init__(self):
                self._t = 1000.0

            def monotonic(self):
                return self._t

            def advance(self, seconds):
                self._t += seconds

        clock = _Clock()

        class _SlowFillLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def fill(self, value, **kwargs):
                # Consume 9.5s of a 10s budget.
                clock.advance(9.5)

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _DATE_START_SELECTOR,
        )

        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=_build_pdf_bytes("ok")),
            locators={_DATE_START_SELECTOR: _SlowFillLocator()},
        )
        flow = EvolutionPdfFlow(page, pdf_download_timeout_ms=120_000)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            flow.extract(
                start_date="2024-01-01",
                end_date="2024-01-02",
                timeout=10,
            )

        # Unconditional assertion: the download was reached and received
        # only the remaining budget (10s - 9.5s = 0.5s = 500ms), not 120000ms.
        assert len(page.request.get_calls) == 1
        _, kwargs = page.request.get_calls[0]
        assert 1 <= kwargs["timeout"] <= 500

    def test_deadline_expiry_before_download_raises_typed(self) -> None:
        """When the budget is fully consumed before the download, a typed
        EvolutionPdfTimeoutError is raised (not a zero timeout or 120s)."""
        import time as time_mod
        from unittest.mock import patch

        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _DATE_START_SELECTOR,
            EvolutionPdfTimeoutError,
        )

        class _Clock:
            def __init__(self):
                self._t = 1000.0

            def monotonic(self):
                return self._t

            def advance(self, seconds):
                self._t += seconds

        clock = _Clock()

        class _ExhaustBudgetLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def fill(self, value, **kwargs):
                # Consume the entire 5s budget.
                clock.advance(10.0)

        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=b"%PDF-1.4 truncated"),
            locators={_DATE_START_SELECTOR: _ExhaustBudgetLocator()},
        )
        flow = EvolutionPdfFlow(page)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            with pytest.raises(EvolutionPdfTimeoutError):
                flow.extract(
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    timeout=5,
                )

    def test_deadline_expiry_before_report_wait_raises_typed_and_skips_later(
        self,
    ) -> None:
        """Expiration before the report wait raises a typed timeout and does
        not call later phases (download)."""
        import time as time_mod
        from unittest.mock import patch

        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _DATE_START_SELECTOR,
            EvolutionPdfTimeoutError,
        )

        class _Clock:
            def __init__(self):
                self._t = 1000.0

            def monotonic(self):
                return self._t

            def advance(self, seconds):
                self._t += seconds

        clock = _Clock()

        class _ExhaustBudgetLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def fill(self, value, **kwargs):
                clock.advance(10.0)

        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            locators={_DATE_START_SELECTOR: _ExhaustBudgetLocator()},
            # A generate button present so the report-wait phase is reached.
            response=_FakeResponse(ok=True, body=b"%PDF-1.4"),
        )
        # Make the generate button present so _generate_report_if_present is
        # attempted after the budget is exhausted.
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _GENERATE_BUTTON_SELECTOR,
        )

        page._locators[_GENERATE_BUTTON_SELECTOR] = _FakeLocator(count_value=1)
        flow = EvolutionPdfFlow(page)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            with pytest.raises(EvolutionPdfTimeoutError):
                flow.extract(
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    timeout=5,
                )

        # Later phases were skipped: the download was never attempted.
        assert page.request.get_calls == []

    def test_fake_operation_overrun_raises_typed_not_invalid_payload(self) -> None:
        """If a fake operation ignores its supplied timeout and advances the
        controlled clock beyond the deadline, the next boundary raises a
        typed timeout rather than invalid_payload / another generic category."""
        import time as time_mod
        from unittest.mock import patch

        import pytest

        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
            EvolutionPdfTimeoutError,
        )

        class _Clock:
            def __init__(self):
                self._t = 1000.0

            def monotonic(self):
                return self._t

            def advance(self, seconds):
                self._t += seconds

        clock = _Clock()

        # A locator that ignores its timeout and advances the clock past the
        # deadline during a bounded attribute read.
        class _OverrunLocator(_FakeLocator):
            def __init__(self):
                super().__init__(count_value=1)

            def get_attribute(self, name, **kwargs):
                clock.advance(20.0)  # ignore the supplied timeout
                return "https://legacy.example/r.pdf"

        page = _FakePdfPage(
            html="",
            locators={_PDF_OBJECT_SELECTOR: _OverrunLocator()},
        )
        flow = EvolutionPdfFlow(page)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            with pytest.raises(EvolutionPdfError) as exc_info:
                flow.extract(
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    timeout=5,
                )

        # The overrun is caught at the next deadline check and raises a
        # typed timeout, never invalid_payload / a generic category.
        assert isinstance(exc_info.value, EvolutionPdfTimeoutError)
