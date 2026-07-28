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
import math
import re
import time
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

_DEFAULT_ACTION_TIMEOUT_MS = 30_000
"""Conservative cap (ms) for a single Playwright fill/click in the PDF flow."""

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

# PSW-S22 R5/R6: constant sanitized message raised when the downloaded
# response is not a PDF (bad content-type or missing ``%PDF-`` signature).
# Carries no URL, cookie, credential, patient data, or raw body text.
_INVALID_PDF_MESSAGE = "Downloaded report content is not a valid PDF"


# ---------------------------------------------------------------------------
# PSW-S17 post-ce2c494 (D14): strict single-deadline helpers.
# The caller's ``timeout`` (seconds) is an UPPER BOUND, not a lower bound.
# A 5-second caller budget must never yield a 120-second download. Every
# phase of ``extract()`` shares one monotonic deadline; expiration raises
# ``EvolutionPdfTimeoutError`` with constant text. No phase receives zero.
# ---------------------------------------------------------------------------


def _deadline_s(timeout_s: int | float) -> float:
    """Return a monotonic deadline (seconds) for a caller budget."""
    return time.monotonic() + max(1, int(timeout_s))


def _remaining_ms(deadline_s: float) -> int:
    """Strictly-positive remaining ms; raise typed timeout on expiry.

    Uses ``ceil`` so a small positive remainder is never collapsed to zero
    (Playwright treats ``timeout=0`` as *disabled*). An exhausted deadline
    raises ``EvolutionPdfTimeoutError``.
    """
    remaining = deadline_s - time.monotonic()
    if remaining <= 0:
        raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE)
    return max(1, math.ceil(remaining * 1000))


def _bound_ms(deadline_s: float, default_ms: int) -> int:
    """Return a strictly-positive timeout bounded by both default and budget.

    ``default_ms`` is a conservative cap; the remaining budget may be smaller.
    Expired deadline raises typed timeout (never returns zero).
    """
    return min(default_ms, _remaining_ms(deadline_s))


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
# PSW-S22: authenticated response validation primitives
# ===========================================================================


def _response_content_type(response: Any) -> str:
    """Best-effort ``content-type`` header read (never leaks; never raises).

    Used by :func:`assert_pdf_response_signature` to validate the response
    content type when the header is present. Returns an empty string when the
    response has no ``headers`` accessor or the header is absent so the caller
    defers to the ``%PDF-`` signature check.
    """
    try:
        headers = getattr(response, "headers", None)
        if not headers:
            return ""
        getter = getattr(headers, "get", None)
        if callable(getter):
            return str(getter("content-type") or "")
        if isinstance(headers, dict):
            return str(headers.get("content-type") or "")
    except Exception:  # noqa: BLE001 - sanitized
        return ""
    return ""


def _is_pdf_compatible_content_type(content_type: str) -> bool:
    """PSW-S22 R5 step 2: PDF-compatible content type when header present.

    An absent/empty header defers to the ``%PDF-`` signature (step 3). A
    ``text/*`` document (HTML/plain error page) is never a PDF and is rejected
    here. Other types (including ``application/pdf`` and common binary
    PDF-serving types such as ``application/octet-stream``) defer to the
    authoritative ``%PDF-`` signature check.
    """
    if not content_type:
        return True
    lowered = content_type.lower()
    if lowered.startswith("text/"):
        return False
    return True


def assert_pdf_response_signature(response: Any, body: bytes) -> None:
    """PSW-S22 R5 steps 2-3: validate content-type and ``%PDF-`` signature.

    HTTP status (step 1) is validated by callers around the body read. This
    helper validates the ``content-type`` header when present and the
    ``%PDF-`` signature on a non-empty body, raising a sanitised
    :class:`EvolutionPdfError` on any violation. It is called AFTER the body
    is retrieved and BEFORE PDF text extraction so HTML/error bytes never
    reach PyMuPDF as if valid.

    Args:
        response: The Playwright-like API response (``headers`` accessor).
        body: Raw response body bytes.

    Raises:
        EvolutionPdfError: If the content-type is a non-PDF text document or
            the body does not begin with ``%PDF-``.
    """
    if not _is_pdf_compatible_content_type(_response_content_type(response)):
        raise EvolutionPdfError(_INVALID_PDF_MESSAGE)
    if not body or not body[:5] == b"%PDF-":
        raise EvolutionPdfError(_INVALID_PDF_MESSAGE)


def read_locator_attribute(
    locator: Any,
    attribute: str,
    deadline_s: float,
    cap_ms: int = _DEFAULT_ACTION_TIMEOUT_MS,
) -> str | None:
    """Read a locator attribute with a bounded Playwright timeout.

    PSW-S22 R2/R4 + PSW-S22-C1: used to read the ``#printLinks`` form
    ``action`` and the ``javax.faces.ViewState`` hidden input ``value``
    through bounded locator operations governed by the shared deadline (no
    ``page.content()``).

    Absence versus timeout is distinguished explicitly so a genuinely
    missing form/input is reported as absence (``None``) rather than
    misclassified as a Playwright attribute-read timeout:

    1. the shared deadline is checked before any locator work;
    2. a non-blocking ``count()`` presence probe runs first;
    3. the deadline is checked immediately after that probe;
    4. a genuinely absent locator (count zero, or a sanitized non-timeout
       probe failure) returns ``None`` WITHOUT reading the attribute;
    5. the attribute is read with the existing bounded timeout only after a
       positive presence probe (``_bound_ms`` re-checks the deadline, so a
       deadline overrun surfaces as a typed timeout in normal flow);
    6. an empty attribute or sanitized non-timeout read failure returns
       ``None``;
    7. a real Playwright attribute-read timeout raises
       :class:`EvolutionPdfTimeoutError`;
    8. the typed timeout is raised OUTSIDE the ``except`` handler so both
       ``__cause__`` and ``__context__`` are ``None`` and no raw exception
       sentinel is retained.
    """
    # 1. deadline check before any locator work.
    _remaining_ms(deadline_s)
    # 2. non-blocking presence probe (Playwright ``count()`` is non-blocking).
    try:
        present = locator.count() > 0
    except Exception:  # noqa: BLE001 - sanitized non-timeout probe failure
        return None
    # 3. deadline check immediately after the probe.
    _remaining_ms(deadline_s)
    # 4. genuinely absent -> None (no attribute read, no timeout).
    if not present:
        return None
    # 5. read the attribute with the bounded timeout only after positive
    #    presence. ``_bound_ms`` re-checks the deadline (overrun -> typed).
    attr_outcome = "ok"
    attr = None
    try:
        attr = locator.first.get_attribute(
            attribute, timeout=_bound_ms(deadline_s, cap_ms)
        )
    except Exception as exc:  # noqa: BLE001 - classified below
        attr_outcome = (
            "timeout" if is_playwright_timeout_error(exc) else "failed"
        )
    # 7/8. typed timeout raised OUTSIDE the except handler.
    if attr_outcome == "timeout":
        raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE)
    if attr_outcome == "failed":
        return None
    # 6. None for an empty attribute.
    return attr if attr else None


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


def _safe_page_url(page: Any) -> str:
    """Best-effort page URL accessor (never leaks payloads; never raises)."""
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:  # noqa: BLE001 - sanitized
        return ""


def _safe_page_frame_urls(page: Any) -> list[str]:
    """Best-effort frame URL accessor (never leaks payloads; never raises)."""
    try:
        frames = getattr(page, "frames", None) or []
    except Exception:  # noqa: BLE001 - sanitized
        return []
    urls: list[str] = []
    for frame in frames:
        try:
            urls.append(str(getattr(frame, "url", "") or ""))
        except Exception:  # noqa: BLE001 - sanitized
            continue
    return urls


def _bounded_locator_count(locator: Any) -> int:
    """Return a locator's presence count, treating access errors as absent."""
    if locator is None:
        return 0
    try:
        return int(locator.count())
    except Exception:  # noqa: BLE001 - treat as absent
        return 0


def _bounded_object_data_attribute(
    locator: Any, deadline_s: float, cap_ms: int
) -> str | None:
    """Read the PDF object ``data`` attribute with a bounded Playwright timeout.

    Raises :class:`EvolutionPdfTimeoutError` on a real Playwright timeout so
    the failure records the timeout category. Returns ``None`` on a
    non-timeout read failure or an empty attribute.
    """
    try:
        attr = locator.first.get_attribute(
            "data", timeout=_bound_ms(deadline_s, cap_ms)
        )
    except Exception as exc:  # noqa: BLE001 - sanitized below
        if is_playwright_timeout_error(exc):
            raise EvolutionPdfTimeoutError(
                _EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE
            ) from None
        logger.warning(
            "Persistent evolution PDF: object data attribute unavailable "
            "(sanitized, non-timeout)"
        )
        return None
    return attr if attr else None


def resolve_pdf_url_from_page(
    page: Any,
    *,
    deadline_s: float,
    base_url: str = "",
    action_timeout_ms: int = _DEFAULT_ACTION_TIMEOUT_MS,
) -> str | None:
    """Resolve a PDF URL through bounded locator/frame operations.

    PSW-S17 post-cbf50c1 (D17/R1): this is the SINGLE shared PDF URL
    resolver used by both :class:`EvolutionPdfFlow` and
    :class:`~apps.ingestion.extractors.real_handle_bridge.RealHandleBridge`.
    It MUST NOT call the unbounded ``page.content()``. It:

    - checks the deadline before any operation;
    - probes the ``<object type="application/pdf">`` presence with a
      non-blocking ``count()`` and deadline checks before/after;
    - once positively present, reads the ``data`` attribute with a bounded
      Playwright timeout (no greater than the remaining budget); a timeout
      raises :class:`EvolutionPdfTimeoutError`;
    - falls back to viewer frame URLs (a non-blocking accessor), checking
      the deadline before and after;
    - returns ``None`` only for a genuine absence with the deadline still
      active (the caller is responsible for checking the deadline before
      converting absence into a generic missing-PDF error).

    Args:
        page: A Playwright-like ``Page`` exposing ``locator()``, ``frames``
            and ``url``.
        deadline_s: Monotonic deadline (seconds) shared across phases.
        base_url: Optional explicit base URL; defaults to ``page.url``.
        action_timeout_ms: Conservative per-action cap (ms).

    Returns:
        The resolved PDF URL, or ``None`` on genuine absence.

    Raises:
        EvolutionPdfTimeoutError: On deadline expiry or a bounded
            Playwright timeout during the attribute read.
    """
    # Deadline check before any operation.
    _remaining_ms(deadline_s)
    resolved_base = base_url or _safe_page_url(page)

    # Strategy 1: bounded <object type="application/pdf" data="..."> attribute.
    try:
        obj_locator = page.locator(_PDF_OBJECT_SELECTOR)
    except Exception:  # noqa: BLE001 - sanitized
        obj_locator = None
    # Non-blocking presence probe; check deadline before and after a
    # non-timeout-capable operation.
    _remaining_ms(deadline_s)
    obj_count = _bounded_locator_count(obj_locator)
    _remaining_ms(deadline_s)
    if obj_count > 0:
        data_attr = _bounded_object_data_attribute(
            obj_locator, deadline_s, action_timeout_ms
        )
        if data_attr:
            return urljoin(resolved_base, data_attr)

    # Strategy 2: viewer frame URLs (a non-blocking accessor). Check the
    # deadline before and after accessing frames.
    _remaining_ms(deadline_s)
    frame_urls = _safe_page_frame_urls(page)
    _remaining_ms(deadline_s)
    viewer_url = _resolve_pdf_url_from_viewer(frame_urls, resolved_base)
    if viewer_url:
        return viewer_url

    # Genuine absence; the caller checks the deadline before converting this
    # to a generic missing-PDF error.
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

        PSW-S17 post-ce2c494 (D14): the caller ``timeout`` is an UPPER BOUND.
        A single monotonic deadline bounds every phase (date fills, report
        generation, report-content read, download). Each phase receives a
        strictly-positive bounded timeout no greater than the remaining
        caller budget; expiration raises :class:`EvolutionPdfTimeoutError`.

        Args:
            start_date: Window start in ``YYYY-MM-DD``.
            end_date: Window end in ``YYYY-MM-DD``.
            admission_key: Admission key to stamp on events (may be empty).
            timeout: Overall budget in seconds (upper bound for all phases).

        Returns:
            Normalised evolution dicts (possibly empty).

        Raises:
            EvolutionPdfError: On any sanitised non-timeout failure.
            EvolutionPdfTimeoutError: On any Playwright/deadline timeout.
        """
        if self._page is None:
            raise EvolutionPdfError("No active page for evolution PDF flow")

        # Validate + convert dates before any page interaction.
        br_start_date = _format_br_date(start_date)
        br_end_date = _format_br_date(end_date)

        # Single monotonic deadline shared by all phases (D14).
        deadline_s = _deadline_s(timeout)

        # Steps 1-2: only interact when the legacy filter UI is present.
        self._apply_dates_if_present(br_start_date, br_end_date, deadline_s)
        self._generate_report_if_present(deadline_s)

        # Step 3: resolve the PDF URL from the rendered report.
        pdf_url = self._resolve_pdf_url(deadline_s)
        if not pdf_url:
            # An optional PDF object/embed that is genuinely absent remains
            # an absence, but deadline expiry must be checked before
            # converting it to a generic missing-PDF error (D17/R1).
            _remaining_ms(deadline_s)
            raise EvolutionPdfError(
                "Evolution report PDF could not be located on the page"
            )

        # Step 4: download bounded by the remaining budget; _download checks
        # the deadline before (via _bound_ms) and after request.get/body.
        pdf_bytes = self._download(pdf_url, deadline_s)

        # Step 5: extract + normalise. Each non-timeout-capable operation is
        # checked against the shared deadline on return (the post-body check
        # in _download also serves as the pre-extraction boundary).
        raw_text = extract_pdf_text(pdf_bytes)
        _remaining_ms(deadline_s)
        events = normalize_pdf_report_text(raw_text, admission_key=admission_key)
        _remaining_ms(deadline_s)
        return events

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _apply_dates_if_present(
        self, br_start_date: str, br_end_date: str, deadline_s: float
    ) -> None:
        """Fill the legacy date inputs when present (D14: bounded by deadline)."""
        start_input = self._page.locator(_DATE_START_SELECTOR)
        if self._locator_count(start_input) > 0:
            try:
                start_input.first.fill(
                    br_start_date, timeout=_bound_ms(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
                )
            except Exception as exc:  # noqa: BLE001 - sanitized below
                if is_playwright_timeout_error(exc):
                    raise EvolutionPdfTimeoutError(
                        _EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE
                    ) from None
                logger.warning(
                    "Persistent evolution PDF: start date input not "
                    "fillable (sanitized, non-timeout)"
                )
        end_input = self._page.locator(_DATE_END_SELECTOR)
        if self._locator_count(end_input) > 0:
            try:
                end_input.first.fill(
                    br_end_date, timeout=_bound_ms(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
                )
            except Exception as exc:  # noqa: BLE001 - sanitized below
                if is_playwright_timeout_error(exc):
                    raise EvolutionPdfTimeoutError(
                        _EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE
                    ) from None
                logger.warning(
                    "Persistent evolution PDF: end date input not "
                    "fillable (sanitized, non-timeout)"
                )

    def _generate_report_if_present(self, deadline_s: float) -> None:
        """Click the report generate button when present (D14: bounded)."""
        button = self._page.locator(_GENERATE_BUTTON_SELECTOR)
        if self._locator_count(button) == 0:
            return
        try:
            button.first.click(timeout=_bound_ms(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS))
            self._wait_for_report(deadline_s)
        except EvolutionPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - sanitized below
            if is_playwright_timeout_error(exc):
                raise EvolutionPdfTimeoutError(
                    _EVOLUTION_PDF_REPORT_TIMEOUT_MESSAGE
                ) from None
            logger.warning(
                "Persistent evolution PDF: report generation not applicable "
                "(sanitized, non-timeout)"
            )

    def _wait_for_report(self, deadline_s: float) -> None:
        """Wait for the report/PDF object to render; raise typed timeout."""
        try:
            self._page.wait_for_selector(
                _PDF_OBJECT_SELECTOR,
                timeout=_bound_ms(deadline_s, self._report_wait_timeout_ms),
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

    def _resolve_pdf_url(self, deadline_s: float) -> str | None:
        """Resolve the PDF URL via bounded locator/frame operations.

        PSW-S17 post-cbf50c1 (D17/R1): the URL-resolution path MUST NOT call
        the unbounded ``page.content()``. It resolves the PDF URL through
        bounded locator attribute reads and viewer frame URLs governed by
        the shared caller deadline. A positively present PDF object/embed
        whose bounded read times out raises
        :class:`EvolutionPdfTimeoutError` with a constant sanitized message.
        A genuinely absent object remains an absence (``None``) as long as
        the deadline is still active.
        """
        return resolve_pdf_url_from_page(
            self._page,
            deadline_s=deadline_s,
            base_url=self._safe_url(),
        )

    def _download(self, pdf_url: str, deadline_s: float) -> bytes:
        """Download the PDF bytes through the existing browser context.

        PSW-S17 post-31dd3c0 (D21): the shared monotonic ``deadline_s`` is
        observed around ``request.get()`` and ``response.body()``. A fake or
        implementation that ignores its supplied timeout and overruns the
        deadline is caught at the next boundary as
        ``EvolutionPdfTimeoutError``; a public real Playwright timeout from
        either call is classified to the same typed error with a constant
        sanitized message. All typed wrappers are raised OUTSIDE the
        ``except`` handlers so neither ``__cause__`` nor ``__context__``
        carries a raw exception (raising ``from None`` inside a handler only
        suppresses *display* of the context). Boundary checks detect and
        classify an overrun AFTER a non-timeout-capable local/cached
        operation returns; they do not interrupt it mid-call.
        """
        context = getattr(self._page, "context", None)
        request = getattr(context, "request", None) if context is not None else None
        if request is None:
            raise EvolutionPdfError("Browser context unavailable for PDF download")
        # Pre-get boundary: _bound_ms checks the deadline and bounds the timeout.
        timeout_ms = _bound_ms(deadline_s, self._pdf_download_timeout_ms)
        get_outcome = "ok"
        response = None
        try:
            response = request.get(pdf_url, timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - classified below
            get_outcome = (
                "timeout" if is_playwright_timeout_error(exc) else "failed"
            )
            if get_outcome == "failed":
                logger.warning(
                    "Persistent evolution PDF: download request failed "
                    "(sanitized, non-timeout)"
                )
        if get_outcome == "timeout":
            raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE)
        if get_outcome == "failed":
            raise EvolutionPdfError("Failed to download the evolution report PDF")
        assert response is not None  # get_outcome == "ok" implies a response

        # After request.get(): catch a fake that ignored its timeout.
        _remaining_ms(deadline_s)

        if not getattr(response, "ok", False):
            raise EvolutionPdfError("Failed to download the evolution report PDF")
        # Immediately before response.body().
        _remaining_ms(deadline_s)
        body_outcome = "ok"
        body = b""
        try:
            body = response.body()
        except Exception as exc:  # noqa: BLE001 - classified below
            body_outcome = (
                "timeout" if is_playwright_timeout_error(exc) else "failed"
            )
        if body_outcome == "timeout":
            raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE)
        if body_outcome == "failed":
            raise EvolutionPdfError("Failed to read the evolution report PDF body")
        # Immediately after response.body() (= before PDF text extraction).
        _remaining_ms(deadline_s)
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
