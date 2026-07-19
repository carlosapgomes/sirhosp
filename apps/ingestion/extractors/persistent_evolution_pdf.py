"""Persistent evolution PDF extraction flow (PSW-S11).

Makes the persistent ``full_sync`` capable of extracting clinical evolutions
from the real legacy PDF report flow, reusing the *already-open* persistent
Playwright session/page/context. It never invokes ``subprocess``, never runs
``path2.py`` as a command, never calls ``sync_playwright()`` again, and never
creates a fresh browser per job.

This module is split into two intentionally separate concerns:

1. **Pure text normalisation** (:func:`normalize_pdf_report_text`) — turns the
   raw text extracted from a legacy evolution PDF into the same evolution
   event dict shape produced by
   :class:`~persistent_extraction_adapter.PersistentExtractionAdapter.extract_evolutions`
   (``admission_key``, ``happened_at``, ``event_type``, ``content``,
   ``profession``). It mirrors the stable, dependency-free parsing pipeline of
   the integrated ``automation/source_system/medical_evolution/path2.py``
   connector (``normalize_pol_report_text`` ->
   ``remove_page_artifacts`` -> ``split_evolutions_by_signature`` ->
   ``build_evolutions_json_payload``).

   .. note::
      ``path2.py`` cannot be imported directly from the Django worker: it
      imports a local ``source_system`` module that itself does
      ``from config import ...``, which collides with the Django ``config``
      package and with the sibling ``automation/source_system/source_system.py``
      (verified during PSW-S11). The parsing functions copied below are pure
      (only ``re``/``datetime``), attributed to ``path2.py`` /
      ``processa_evolucoes_txt.py``, and MUST be kept in sync with those
      sources of truth. They are intentionally minimal — no Playwright, no I/O,
      no CLI — to avoid drift in behaviour.

2. **Interactive PDF acquisition** (:class:`EvolutionPdfFlow`) — given the
   already-open Playwright page/context, applies the date window, generates
   the report, resolves the PDF URL, downloads the bytes through the existing
   context (``page.context.request.get``), extracts text with PyMuPDF, and
   normalises it. All failures are mapped to a sanitised
   :class:`EvolutionPdfError` (no credentials, cookies, raw HTML, or
   patient-identifying data in messages).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    is_playwright_timeout_error,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_REPORT_WAIT_TIMEOUT_MS = 30_000
"""Default wait (ms) for report-generation / PDF-URL availability polls."""

DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS = 120_000
"""Default timeout (ms) for the authenticated PDF download request."""

# CSS selectors used to drive the legacy evolution report flow. Kept here so
# they are isolated from the SessionHandle protocol and testable with fakes.
_DATE_START_SELECTOR = 'input[id$="dataInicio:inputId_input"]'
_DATE_END_SELECTOR = 'input[id$="dataFim:inputId_input"]'
_GENERATE_BUTTON_SELECTOR = '#bt_UltimosQuinzedias\\:button'
_PDF_OBJECT_SELECTOR = 'object[type="application/pdf"]'


class EvolutionPdfError(ExtractionError):
    """Sanitised error raised when the persistent evolution PDF flow fails.

    Messages never include credentials, cookies, raw page payloads, or
    patient-identifying data. It subclasses :class:`ExtractionError` so the
    command's failure taxonomy classifies it as a recoverable data-level
    failure (a job tab was already opened).
    """


class EvolutionPdfTimeoutError(EvolutionPdfError, ExtractionTimeoutError):
    """Typed timeout raised by the persistent evolution PDF flow.

    PSW-S17 R2/R3: report-render waits and authenticated PDF downloads
    through ``page.context.request.get`` MUST surface as typed timeouts so
    the shared classifier maps the failure to ``("timeout", True)`` instead
    of the generic ``invalid_payload`` bucket. This subclass is both an
    :class:`EvolutionPdfError` (so existing ``except EvolutionPdfError``
    cleanup dispatch still catches it) and an
    :class:`ExtractionTimeoutError` (so the classifier recognises it without
    any cause/context chain walk).
    """


# Constant sanitized timeout messages (PSW-S17 R4: no URL, raw text,
# cookies, credentials, patient data, or admission keys in error text).
_EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE = (
    "Persistent evolution PDF report render timed out."
)
_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE = (
    "Persistent evolution PDF download timed out."
)


# ===========================================================================
# PDF text extraction (PyMuPDF)
# ===========================================================================


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF.

    Mirrors ``extrair_texto_do_pdf`` from ``source_system.py`` but operates on
    in-memory bytes (no temp file) so the persistent worker does not churn the
    filesystem per job.

    Args:
        pdf_bytes: Raw PDF file bytes (must start with ``%PDF-``).

    Returns:
        Concatenated page text, each page prefixed with a
        ``===== PÁGINA N =====`` marker (the format the normaliser expects).

    Raises:
        EvolutionPdfError: If the bytes are not a valid PDF or no text could be
            extracted from any page.
    """
    if not pdf_bytes or not pdf_bytes[:5] == b"%PDF-":
        raise EvolutionPdfError(
            "Downloaded report content is not a valid PDF"
        )

    import pymupdf  # local import: PyMuPDF is a heavy dependency

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning("Persistent evolution PDF: could not open PDF (sanitized)")
        raise EvolutionPdfError("Downloaded report content is not a valid PDF") from None

    pages: list[str] = []
    try:
        for page_number, page in enumerate(document, start=1):
            page_text = (page.get_text("text") or "").strip()
            pages.append(f"===== PÁGINA {page_number} =====\n{page_text}")
    finally:
        document.close()

    result = "\n\n".join(pages).strip()
    if not result:
        raise EvolutionPdfError("No text could be extracted from the report PDF")
    return result


# ===========================================================================
# Pure normalisation pipeline (mirrors path2.py / processa_evolucoes_txt.py)
# ===========================================================================
#
# The functions below are a focused, attributed reproduction of the stable
# parsing pipeline in automation/source_system/medical_evolution/path2.py and
# processa_evolucoes_txt.py. They are pure (re/datetime only) and must stay in
# sync with those sources of truth. See module docstring for the rationale.

# --- from path2.py -------------------------------------------------------

_PAGE_HEADER_BLOCK_RE = re.compile(
    r"(?ms)^(===== PÁGINA \d+ =====)\nEVOLUÇÃO\n(/\s*\d+)\n(\d+)\n"
)
_DATETIME_WITHOUT_SECONDS_RE = re.compile(r"(?m)^(\d{2}/\d{2}/\d{4} \d{2}:\d{2})$")
_DATETIME_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}(?::\d{2})?$")
_EVOLUTION_END_LINE_RE = re.compile(
    r"^Elaborado\b.*\bem:?\s*\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?$",
    re.IGNORECASE,
)
_SIGNATURE_AUTHOR_RE = re.compile(
    r"\bpor[:\s]+(.+?)\s*(?:,|-)?\s*"
    r"(?:Crm|Coren|Crefito|Crefono|Crn\d*|Cro(?:-?[A-Z]{2})?)\b",
    re.IGNORECASE,
)


def _normalize_pol_report_text(raw_text: str) -> str:
    """Normalise raw PDF text (mirrors ``path2.normalize_pol_report_text``)."""
    text = _PAGE_HEADER_BLOCK_RE.sub(r"\1\n\2\n\3\nEVOLUÇÃO\n", raw_text)
    text = _DATETIME_WITHOUT_SECONDS_RE.sub(r"\1:00", text)
    return text


def _normalize_datetime_line(value: str) -> str:
    stripped = value.strip()
    if _DATETIME_LINE_RE.match(stripped) and len(stripped) == 16:
        return f"{stripped}:00"
    return stripped


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _is_evolution_end_line(value: str) -> bool:
    return bool(_EVOLUTION_END_LINE_RE.match(value.strip()))


def _split_evolutions_by_signature(cleaned_lines: list[str]) -> list[list[str]]:
    """Split cleaned lines into evolution line-lists (mirrors path2)."""
    evolutions: list[list[str]] = []
    current: list[str] = []
    seen_first_datetime = False
    current_closed = False

    for line in cleaned_lines:
        stripped = line.strip()

        if _DATETIME_LINE_RE.match(stripped):
            normalized_dt = _normalize_datetime_line(stripped)
            if not seen_first_datetime:
                current = [normalized_dt]
                seen_first_datetime = True
                current_closed = False
                continue
            if current_closed:
                candidate = _trim_blank_edges(current)
                if candidate:
                    evolutions.append(candidate)
                current = [normalized_dt]
                current_closed = False
                continue
            # Datetime without a preceding end marker: ignore as noise.
            continue

        if not seen_first_datetime:
            continue
        if current_closed:
            continue

        current.append(stripped)
        if stripped and _is_evolution_end_line(stripped):
            current_closed = True

    candidate = _trim_blank_edges(current)
    if candidate:
        evolutions.append(candidate)
    return evolutions


def _find_signature_line(evolution_lines: list[str]) -> str | None:
    for line in reversed(evolution_lines):
        if _is_evolution_end_line(line):
            return line.strip()
    return None


def _extract_initial_datetime(evolution_lines: list[str]) -> datetime:
    for line in evolution_lines:
        stripped = _normalize_datetime_line(line)
        if _DATETIME_LINE_RE.match(stripped):
            return datetime.strptime(stripped, "%d/%m/%Y %H:%M:%S")
    raise EvolutionPdfError("Evolution block is missing its date/time marker")


def _build_evolution_content(
    evolution_lines: list[str], signature_line: str | None
) -> str:
    lines = _trim_blank_edges(evolution_lines)
    if lines and _DATETIME_LINE_RE.match(_normalize_datetime_line(lines[0])):
        lines = lines[1:]
    if signature_line and lines and lines[-1].strip() == signature_line:
        lines = lines[:-1]
    return "\n".join(_trim_blank_edges(lines)).strip()


def _classify_evolution_type(signature_line: str | None, content: str) -> str:
    signature_lowered = (signature_line or "").casefold()
    content_lowered = content.casefold()
    if "crm" in signature_lowered:
        return "medical"
    if "coren" in signature_lowered:
        return "nursing"
    if "crefito" in signature_lowered:
        return "phisiotherapy"
    if "crn" in signature_lowered:
        return "nutrition"
    if "crefono" in signature_lowered:
        return "speech_therapy"
    if "cro" in signature_lowered:
        return "dentistry"
    if "odontologia" in content_lowered or "odontolog" in content_lowered:
        return "dentistry"
    return "other"


def _extract_created_by(signature_line: str | None) -> str:
    if not signature_line:
        return ""
    match = _SIGNATURE_AUTHOR_RE.search(signature_line)
    if match:
        return match.group(1).strip(" ,-:")
    fallback = re.search(
        r"\bpor[:\s]+(.+?)\s+em:?\s*\d{2}/\d{2}/\d{4}",
        signature_line,
        re.IGNORECASE,
    )
    if fallback:
        return fallback.group(1).strip(" ,-:")
    return ""


# --- from processa_evolucoes_txt.py --------------------------------------

_PAGE_HEADER_RE = re.compile(r"^===== PÁGINA \d+ =====$")
_PAGE_TOTAL_RE = re.compile(r"^/\s*\d+$")
_PAGE_NUMBER_RE = re.compile(r"^\d+$")
_EVOLUTION_DATETIME_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$")
_SHORT_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _peek_next_nonblank(lines: list[str], start_index: int) -> str | None:
    for index in range(start_index, len(lines)):
        candidate = lines[index].strip()
        if candidate:
            return candidate
    return None


def _remove_page_artifacts(text: str) -> list[str]:
    """Strip pagination artifacts (mirrors ``processa_evolucoes_txt``)."""
    lines = text.splitlines()
    cleaned: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if _PAGE_HEADER_RE.match(stripped):
            i += 1
            if i < len(lines) and _PAGE_TOTAL_RE.match(lines[i].strip()):
                i += 1
            if i < len(lines) and _PAGE_NUMBER_RE.match(lines[i].strip()):
                i += 1
            if i < len(lines) and lines[i].strip() == "EVOLUÇÃO":
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        if (
            stripped == "EVOLUÇÃO"
            and i + 1 < len(lines)
            and lines[i + 1].strip() == "Identificação"
        ):
            i += 2
            while i < len(lines):
                current = lines[i].strip()
                i += 1
                if current.startswith("Código:"):
                    while i < len(lines) and not lines[i].strip():
                        i += 1
                    break
            continue

        if _SHORT_TIME_RE.match(stripped):
            previous_line = cleaned[-1].strip() if cleaned else ""
            next_nonblank = _peek_next_nonblank(lines, i + 1)
            if previous_line.startswith("Elaborado e assinado por"):
                i += 1
                continue
            if next_nonblank and _EVOLUTION_DATETIME_RE.match(next_nonblank):
                i += 1
                continue

        cleaned.append(stripped)
        i += 1

    return cleaned


# ===========================================================================
# Public normalisation entry point
# ===========================================================================


def normalize_pdf_report_text(
    raw_text: str,
    *,
    admission_key: str = "",
) -> list[dict[str, Any]]:
    """Normalise raw evolution-PDF text into the adapter evolution contract.

    Runs the path2-equivalent pipeline (normalise page headers -> remove
    pagination artifacts -> split by signature -> build payload) and maps the
    result to the five-key evolution dict shape used by
    :func:`PersistentExtractionAdapter.extract_evolutions`:
    ``admission_key``, ``happened_at``, ``event_type``, ``content``,
    ``profession``.

    Args:
        raw_text: Raw text extracted from the legacy evolution PDF (with
            ``===== PÁGINA N =====`` page markers).
        admission_key: Admission key to stamp on every event. The persistent
            flow does not perform per-admission table selection, so callers
            may pass an empty string; admission resolution then falls back to
            period matching in the shared ingestion service.

    Returns:
        List of normalised evolution dicts. Returns an empty list — not an
        error — when the report text contains no evolution markers (i.e. the
        window genuinely has no evolutions).
    """
    if not raw_text or not raw_text.strip():
        return []

    normalized = _normalize_pol_report_text(raw_text)
    cleaned = _remove_page_artifacts(normalized)
    evolution_blocks = _split_evolutions_by_signature(cleaned)
    if not evolution_blocks:
        return []

    events: list[dict[str, Any]] = []
    for block in evolution_blocks:
        signature_line = _find_signature_line(block)
        try:
            happened_at = _extract_initial_datetime(block).isoformat()
        except EvolutionPdfError:
            logger.warning("Persistent evolution PDF: skipping block without datetime")
            continue
        content = _build_evolution_content(block, signature_line)
        events.append(
            {
                "admission_key": admission_key,
                "happened_at": happened_at,
                "event_type": _classify_evolution_type(signature_line, content),
                "content": content,
                "profession": _extract_created_by(signature_line),
                "signature_line": signature_line or "",
            }
        )
    return events


# ===========================================================================
# Interactive PDF acquisition flow
# ===========================================================================


def _resolve_pdf_url_from_object(html: str, base_url: str) -> str | None:
    """Extract a PDF URL from an ``<object type="application/pdf" data="...">``."""
    match = re.search(
        r'<object[^>]*\btype\s*=\s*["\']application/pdf["\'][^>]*>',
        html,
        re.IGNORECASE,
    )
    if not match:
        return None
    object_tag = match.group(0)
    data_match = re.search(r'\bdata\s*=\s*["\']([^"\']+)["\']', object_tag, re.IGNORECASE)
    if not data_match:
        return None
    return urljoin(base_url, data_match.group(1))


def _resolve_pdf_url_from_viewer(frame_urls: list[str], base_url: str) -> str | None:
    """Extract a PDF URL from a viewer frame URL (``.pdf`` or ``file=`` param)."""
    for frame_url in frame_urls:
        if not frame_url:
            continue
        parsed = urlparse(frame_url)
        if parsed.path.lower().endswith(".pdf"):
            return urljoin(frame_url, frame_url)
        file_candidates = parse_qs(parsed.query).get("file", [])
        for candidate in file_candidates:
            return urljoin(frame_url, candidate)
    return None


def _format_br_date(iso_date: str) -> str:
    """Convert a ``YYYY-MM-DD`` date string to the legacy ``DD/MM/YYYY`` format.

    Mirrors ``format_br_date`` from
    ``automation/source_system/medical_evolution/path2.py`` but operates on the
    adapter's ISO string contract (the legacy connector consumes ``date``
    objects). Raises a sanitized :class:`EvolutionPdfError` for malformed or
    impossible calendar dates so the flow fails fast *before* any page
    interaction — the legacy evolution report requires ``DD/MM/YYYY`` in its
    date inputs and would otherwise yield an empty/wrong report.

    Args:
        iso_date: Date in the public ISO ``YYYY-MM-DD`` contract.

    Returns:
        The same date formatted as ``DD/MM/YYYY`` for the legacy inputs.

    Raises:
        EvolutionPdfError: If ``iso_date`` is not a valid ``YYYY-MM-DD``
            calendar date. The message is generic and never echoes the input.
    """
    try:
        parsed = datetime.strptime(iso_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise EvolutionPdfError(
            "Invalid date value for the evolution report window"
        ) from None
    return parsed.strftime("%d/%m/%Y")


class EvolutionPdfFlow:
    """Drive the legacy evolution PDF flow on an already-open page.

    Reuses the persistent page/context (no new browser, no subprocess). The
    flow is intentionally minimal and defensive:

    1. Apply the start/end date window if the legacy date inputs are present.
    2. Generate the report if a generate/evolution button is present.
    3. Resolve the PDF URL (``<object data>`` then viewer frame URL).
    4. Download the PDF bytes through ``page.context.request.get``.
    5. Extract text with PyMuPDF and normalise it.

    All failures raise :class:`EvolutionPdfError` with sanitised messages.

    Args:
        page: A Playwright-like ``Page`` (mocked in tests). Must expose
            ``content()``, ``locator()``, ``url``, ``frames`` and
            ``context.request.get``.
        report_wait_timeout_ms: Wait budget (ms) for report-generation polls.
        pdf_download_timeout_ms: Timeout (ms) for the PDF download request.
    """

    def __init__(
        self,
        page: Any,
        *,
        report_wait_timeout_ms: int = DEFAULT_REPORT_WAIT_TIMEOUT_MS,
        pdf_download_timeout_ms: int = DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS,
    ) -> None:
        self._page = page
        self._report_wait_timeout_ms = max(1, int(report_wait_timeout_ms))
        self._pdf_download_timeout_ms = max(1, int(pdf_download_timeout_ms))

    def extract(
        self,
        *,
        start_date: str,
        end_date: str,
        admission_key: str = "",
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Run the PDF flow for one date window and return normalised events.

        Args:
            start_date: Window start in ``YYYY-MM-DD`` (public contract). It is
                converted to ``DD/MM/YYYY`` before filling the legacy inputs.
            end_date: Window end in ``YYYY-MM-DD`` (public contract). It is
                converted to ``DD/MM/YYYY`` before filling the legacy inputs.
            admission_key: Admission key to stamp on events (may be empty).
            timeout: Overall hint in seconds; the download wait honours it.

        Returns:
            Normalised evolution dicts (possibly empty).

        Raises:
            EvolutionPdfError: On any sanitised failure — including an invalid
                date window (raised before report generation/download), a
                missing PDF URL, a download failure, or invalid/empty PDF text.
        """
        if self._page is None:
            raise EvolutionPdfError("No active page for evolution PDF flow")

        # The public contract keeps ISO YYYY-MM-DD; the legacy report inputs
        # require DD/MM/YYYY. Validate + convert before any page interaction so
        # invalid windows fail fast without generating or downloading anything.
        br_start_date = _format_br_date(start_date)
        br_end_date = _format_br_date(end_date)

        download_timeout_ms = self._derive_download_timeout_ms(timeout)

        # Steps 1-2: only interact when the legacy filter UI is present.
        self._apply_dates_if_present(br_start_date, br_end_date)
        self._generate_report_if_present()

        # Step 3: resolve the PDF URL from the rendered report.
        pdf_url = self._resolve_pdf_url()
        if not pdf_url:
            raise EvolutionPdfError(
                "Evolution report PDF could not be located on the page"
            )

        # Step 4: download through the existing browser context.
        pdf_bytes = self._download(pdf_url, download_timeout_ms)

        # Step 5: extract + normalise.
        raw_text = extract_pdf_text(pdf_bytes)
        return normalize_pdf_report_text(raw_text, admission_key=admission_key)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _derive_download_timeout_ms(self, timeout_seconds: int) -> int:
        """Pick a download timeout that honours the caller's overall hint."""
        candidate = max(1, int(timeout_seconds)) * 1000
        return max(self._pdf_download_timeout_ms, candidate)

    def _apply_dates_if_present(self, br_start_date: str, br_end_date: str) -> None:
        """Fill the legacy date inputs (``DD/MM/YYYY``) when present (no-op if absent)."""
        try:
            start_input = self._page.locator(_DATE_START_SELECTOR)
            if self._locator_count(start_input) > 0:
                start_input.first.fill(br_start_date)
            end_input = self._page.locator(_DATE_END_SELECTOR)
            if self._locator_count(end_input) > 0:
                end_input.first.fill(br_end_date)
        except EvolutionPdfError:
            raise
        except Exception:  # noqa: BLE001 - sanitized: date UI optional
            logger.warning("Persistent evolution PDF: date inputs not applicable (sanitized)")

    def _generate_report_if_present(self) -> None:
        """Click the report generate button when present (defensive no-op)."""
        try:
            button = self._page.locator(_GENERATE_BUTTON_SELECTOR)
            if self._locator_count(button) > 0:
                button.first.click()
                self._wait_for_report()
        except EvolutionPdfError:
            raise
        except Exception:  # noqa: BLE001 - sanitized: generate UI optional
            logger.warning("Persistent evolution PDF: report generation not applicable (sanitized)")

    def _wait_for_report(self) -> None:
        """Wait for the report/PDF object to render; raise typed timeout.

        PSW-S17 R2/R3: a Playwright timeout while waiting for the report
        object MUST surface as a typed
        :class:`EvolutionPdfTimeoutError` rather than being silently
        treated as best-effort. Non-timeout exceptions remain best-effort
        (the report UI is optional on some pages).
        """
        try:
            self._page.wait_for_selector(
                _PDF_OBJECT_SELECTOR,
                timeout=self._report_wait_timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001 - sanitized below
            if is_playwright_timeout_error(exc):
                raise EvolutionPdfTimeoutError(
                    _EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE
                ) from None
            logger.warning(
                "Persistent evolution PDF: report render wait interrupted "
                "(sanitized, non-timeout)"
            )

    def _resolve_pdf_url(self) -> str | None:
        """Resolve the PDF URL from the page content and viewer frames."""
        base_url = self._safe_url()
        try:
            html = self._page.content()
        except Exception:  # noqa: BLE001 - sanitized below
            logger.warning("Persistent evolution PDF: page content unavailable (sanitized)")
            html = ""

        url = _resolve_pdf_url_from_object(html, base_url)
        if url:
            return url

        frame_urls = self._safe_frame_urls()
        return _resolve_pdf_url_from_viewer(frame_urls, base_url)

    def _download(self, pdf_url: str, timeout_ms: int) -> bytes:
        """Download the PDF bytes through the existing browser context.

        PSW-S17 R2/R3: a Playwright/playwright-request timeout MUST surface
        as :class:`EvolutionPdfTimeoutError` so the run/attempt records
        ``failure_reason=timeout``. Other download failures remain
        :class:`EvolutionPdfError`.
        """
        context = getattr(self._page, "context", None)
        request = getattr(context, "request", None) if context is not None else None
        if request is None:
            raise EvolutionPdfError("Browser context unavailable for PDF download")
        try:
            response = request.get(pdf_url, timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - sanitized below
            if is_playwright_timeout_error(exc):
                raise EvolutionPdfTimeoutError(
                    _EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE
                ) from None
            logger.warning(
                "Persistent evolution PDF: download request failed "
                "(sanitized, non-timeout)"
            )
            raise EvolutionPdfError("Failed to download the evolution report PDF") from None

        if not getattr(response, "ok", False):
            raise EvolutionPdfError("Failed to download the evolution report PDF")
        try:
            body = response.body()
        except Exception as exc:  # noqa: BLE001 - sanitized below
            if is_playwright_timeout_error(exc):
                raise EvolutionPdfTimeoutError(
                    _EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE
                ) from None
            raise EvolutionPdfError("Failed to read the evolution report PDF body") from None
        return bytes(body or b"")

    # ------------------------------------------------------------------
    # Defensive page accessors (never leak raw payloads)
    # ------------------------------------------------------------------

    @staticmethod
    def _locator_count(locator: Any) -> int:
        try:
            return int(locator.count())
        except Exception:  # noqa: BLE001 - treat as absent
            return 0

    def _safe_url(self) -> str:
        try:
            return str(self._page.url or "")
        except Exception:  # noqa: BLE001 - sanitized
            return ""

    def _safe_frame_urls(self) -> list[str]:
        try:
            frames = self._page.frames or []
        except Exception:  # noqa: BLE001 - sanitized
            return []
        urls: list[str] = []
        for frame in frames:
            try:
                urls.append(str(getattr(frame, "url", "") or ""))
            except Exception:  # noqa: BLE001 - sanitized
                continue
        return urls
