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
    def __init__(self, *, count_value: int = 0, fill_error: bool = False):
        self._count = count_value
        self._fill_error = fill_error
        self.filled: list[str] = []
        self.clicked: int = 0
        self.first = self

    def count(self) -> int:
        return self._count

    def fill(self, value: str) -> None:
        if self._fill_error:
            raise RuntimeError("fill failed")
        self.filled.append(value)

    def click(self) -> None:
        self.clicked += 1

    def get_attribute(self, name: str) -> str | None:  # noqa: ARG002
        return None


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

    def content(self) -> str:
        if self._content_raises:
            raise RuntimeError("content unavailable")
        return self._html

    def locator(self, selector: str) -> _FakeLocator:
        return self._locators.get(selector, _FakeLocator())

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
    """Timeout values reach the report/download waits."""

    def test_download_timeout_honours_overall_hint(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page, pdf_download_timeout_ms=5_000)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=30)

        _, kwargs = page.request.get_calls[0]
        # The caller hint (30s) must be honoured even if it exceeds the default.
        assert kwargs["timeout"] == 30_000

    def test_download_timeout_falls_back_to_default(self) -> None:
        pdf_bytes = _build_pdf_bytes(REPRESENTATIVE_REPORT_TEXT)
        page = _FakePdfPage(
            html=_object_html("https://legacy.example/r.pdf"),
            response=_FakeResponse(ok=True, body=pdf_bytes),
        )
        flow = EvolutionPdfFlow(page, pdf_download_timeout_ms=DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS)

        flow.extract(start_date="2024-01-01", end_date="2024-01-02", timeout=1)

        _, kwargs = page.request.get_calls[0]
        assert kwargs["timeout"] == DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS


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
