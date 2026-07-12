"""Real Handle Bridge for legacy UI extraction (PSW-S9).

Provides a :class:`RealHandleBridge` that wraps a real
``PlaywrightSessionHandle`` (or any ``SessionHandle``) and translates
real legacy UI DOM data into the synthetic container format expected by
:class:`~persistent_extraction_adapter.PersistentExtractionAdapter`.

The real legacy UI does NOT produce ``<div id="admission-snapshot-data">``
or ``<div id="evolution-data">`` containers. This bridge extracts
admission and evolution data from the real DOM structure and renders it
inside those synthetic containers so the existing adapter can consume it.

Design (per ``design.md`` Decision 9 and PSW-S9 scope):
- Bridge is a thin wrapper implementing the ``SessionHandle`` protocol.
- ``get_page_html()`` inspects the current page URL to determine whether
  this is an admissions or evolution page, then extracts data from the
  real legacy HTML structure and wraps it in the expected synthetic
  container format.
- All other protocol methods are delegated to the wrapped handle.
- No new browser, subprocess, or fresh Playwright launch per job.
- Extraction uses regex-based HTML parsing (no external dependency).
- The bridge preserves session counter HTML for controller checks.

Usage::

    from apps.ingestion.extractors.playwright_session_handle import (
        PlaywrightSessionHandle,
    )
    from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

    handle = PlaywrightSessionHandle(...)
    handle.start()
    bridge = RealHandleBridge(handle)

    # Use bridge in adapter:
    adapter = PersistentExtractionAdapter(bridge)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
    EvolutionPdfFlow,
)
from apps.ingestion.extractors.session_controller import SessionHandle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL patterns for page-type detection
# ---------------------------------------------------------------------------

_ADMISSIONS_URL_PATTERNS: list[str] = [
    "consultarInternacoes",
    "/admissions/",
    "internacoes",
]

_EVOLUTIONS_URL_PATTERNS: list[str] = [
    "relatorioAnaEvoInternacaoPdf",
    "consultaDetalheInternacao",
    "/evolutions/",
    "evolucao",
]

# ---------------------------------------------------------------------------
# Regex patterns for extracting data from legacy DOM
# ---------------------------------------------------------------------------

# Match a full <tr ...>...</tr> row, capturing the opening tag attrs
# group(1) = opening tag content (data-ri, data-rk, etc.)
# group(2) = inner row content (<td> cells)
_TR_RE = re.compile(
    r'<tr\b([^>]*)>(.*?)</tr>',
    re.DOTALL | re.IGNORECASE,
)

# Extract data-ri="..." attribute value
_ATTR_DATA_RI_RE = re.compile(
    r'\bdata-ri\s*=\s*["\'](\d*)["\']',
    re.IGNORECASE,
)

# Extract data-rk="..." attribute value
_ATTR_DATA_RK_RE = re.compile(
    r'\bdata-rk\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)

# Extract cell text from <td> elements
_TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

# Extract details link presence
_DETAILS_LINK_RE = re.compile(
    r'<a[^>]*\btitle\s*=\s*["\']Detalhes\s+da\s+Internação["\']',
    re.IGNORECASE,
)

# Script tag with type="application/json" containing evolution data.
# Accepts attributes in any order (id before type or vice versa).
_SCRIPT_JSON_RE = re.compile(
    r'<script[^>]*\bid\s*=\s*["\']evolution-data-json["\']'
    r'[^>]*\btype\s*=\s*["\']application/json["\']'
    r'[^>]*>\s*'
    r'(.*?)'
    r'\s*</script>',
    re.DOTALL | re.IGNORECASE,
)

# Fallback: extract text content from pre.report-text
_PRE_REPORT_RE = re.compile(
    r'<pre[^>]*\bclass\s*=\s*["\'][^"\']*report-text[^"\']*["\'][^>]*>'
    r'(.*?)</pre>',
    re.DOTALL | re.IGNORECASE,
)

# Session counter HTML pattern — extract for preservation
_TEMPO_SESSAO_RE = re.compile(
    r'(<div[^>]*\bid\s*=\s*["\']tempoSessao["\'][^>]*>.*?</div>)',
    re.DOTALL | re.IGNORECASE,
)

# Renewal popup container — preserve so the controller's defensive
# is_renewal_popup_visible() check still works through the bridge.
_RENEWAL_POPUP_RE = re.compile(
    r'(<div[^>]*\bid\s*=\s*["\']casca_renovasession["\'][^>]*>.*?</div>)',
    re.DOTALL | re.IGNORECASE,
)

# Date parsing: BR format DD/MM/YYYY
_BR_DATE_RE = re.compile(r'^\s*(\d{2})/(\d{2})/(\d{4})\s*$')


def _parse_br_date(value: str) -> str | None:
    """Parse a BR-format date (DD/MM/YYYY) and return ISO format (YYYY-MM-DD).

    Args:
        value: Date string in DD/MM/YYYY format.

    Returns:
        ISO-format date string, or ``None`` if the value is empty/invalid.
    """
    stripped = value.strip()
    if not stripped:
        return None
    match = _BR_DATE_RE.match(stripped)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags from a text string."""
    return re.sub(r'<[^>]+>', '', text).strip()


def _extract_block(html: str, pattern: re.Pattern[str]) -> str:
    """Return the first regex match group from ``html``, or empty string.

    Used to preserve page fragments (session counter, renewal popup) when
    rebuilding page HTML for the adapter.
    """
    match = pattern.search(html)
    return match.group(1) if match else ""


def _extract_admission_rows(html: str) -> list[dict[str, Any]]:
    """Extract admission data from legacy internações table rows.

    Parses ``<tr data-ri="..." data-rk="...">`` rows from the
    ``#tabelaInternacoes:resultList_data`` table and returns a list
    of canonical admission dicts.

    Args:
        html: Raw page HTML from the admissions/internações page.

    Returns:
        List of admission dicts with canonical field names.
    """
    # Find the table body
    table_match = re.search(
        r'<tbody[^>]*\bid\s*=\s*["\']tabelaInternacoes:resultList_data["\']'
        r'[^>]*>(.*?)</tbody>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not table_match:
        return []

    table_body = table_match.group(1)

    tr_matches = _TR_RE.findall(table_body)
    if not tr_matches:
        return []

    result: list[dict[str, Any]] = []
    for row_attrs, row_content in tr_matches:
        # Parse data-rk from the opening tag attributes.
        # When data-rk is empty/missing, generate a fallback key
        # (matches path2.py's fallback: "row-{index}").
        data_rk_match = _ATTR_DATA_RK_RE.search(row_attrs)
        raw_rk = data_rk_match.group(1) if data_rk_match else ""
        data_rk = raw_rk or f"row-{len(result)}"

        # Only rows with a details link are valid admissions
        if not _DETAILS_LINK_RE.search(row_content):
            continue

        cells = _TD_RE.findall(row_content)
        cells_text = [_strip_html_tags(c) for c in cells]

        if len(cells_text) < 2:
            continue

        admission_start_iso = _parse_br_date(cells_text[0])
        if admission_start_iso is None:
            continue

        admission_end_raw = cells_text[1] if len(cells_text) > 1 else ""
        admission_end_iso = _parse_br_date(admission_end_raw)

        ward = cells_text[2] if len(cells_text) > 2 else ""
        bed = cells_text[3] if len(cells_text) > 3 else ""

        result.append({
            "admissionKey": data_rk or "",
            "admissionStart": admission_start_iso,
            "admissionEnd": admission_end_iso,
            "ward": ward,
            "bed": bed,
        })

    return result


def _extract_evolution_items(html: str) -> list[dict[str, Any]]:
    """Extract evolution items from legacy evolution page HTML.

    Tries multiple extraction strategies:
    1. Script tag with JSON (<script id="evolution-data-json" type="application/json">)
    2. Fallback: extract page content as single evolution item

    Args:
        html: Raw page HTML from the evolution/report page.

    Returns:
        List of normalized evolution dicts.
    """
    # Strategy 1: Script JSON tag
    script_match = _SCRIPT_JSON_RE.search(html)
    if script_match:
        try:
            raw_json = script_match.group(1)
            data = json.loads(raw_json)
            if isinstance(data, list):
                return [
                    {
                        "admission_key": item.get("admissionKey", item.get("admission_key", "")),
                        "happened_at": item.get("createdAt", item.get("happened_at", "")),
                        "event_type": item.get("type", item.get("event_type", "")),
                        "content": item.get("content", ""),
                        "profession": item.get("createdBy", item.get("profession", "")),
                    }
                    for item in data
                ]
            return []
        except json.JSONDecodeError:
            logger.warning("Failed to parse evolution JSON from script tag")

    # Strategy 2: pre.report-text content
    pre_match = _PRE_REPORT_RE.search(html)
    if pre_match:
        content = pre_match.group(1).strip()
        if content:
            return [{
                "admission_key": "",
                "happened_at": "",
                "event_type": "report",
                "content": content,
                "profession": "",
            }]

    return []


# ---------------------------------------------------------------------------
# RealHandleBridge
# ---------------------------------------------------------------------------


class RealHandleBridge:
    """Bridge that translates real legacy DOM into synthetic container format.

    Wraps a ``SessionHandle`` (typically ``PlaywrightSessionHandle``) and
    overrides ``get_page_html()`` to extract admission or evolution data
    from the real legacy page structure, wrapping it in the synthetic
    container divs expected by the ``PersistentExtractionAdapter``.

    The bridge delegates all other ``SessionHandle`` protocol methods
    to the wrapped handle unchanged.

    Args:
        handle: The real ``SessionHandle`` implementation to wrap.
    """

    def __init__(self, handle: SessionHandle) -> None:
        self._handle = handle
        self._last_url: str = ""

    # ------------------------------------------------------------------
    # SessionHandle protocol
    # ------------------------------------------------------------------

    def get_page_html(self) -> str:
        """Get page HTML with synthetic containers for adapter consumption.

        Inspects the current page context to determine whether this is an
        admissions or evolution page, extracts real legacy data from the
        DOM, and wraps it in ``<div id="admission-snapshot-data">`` or
        ``<div id="evolution-data">`` containers.

        For non-admission/evolution pages (e.g. root/safe-renewal tabs),
        returns the raw HTML unchanged.

        Returns:
            Page HTML string, potentially containing synthetic container
            divs with extracted data as JSON payloads.
        """
        raw_html = self._handle.get_page_html()

        if not self._last_url:
            return raw_html

        # Determine page type from URL
        if self._is_admissions_page():
            return self._build_admission_container_html(raw_html)
        elif self._is_evolution_page():
            return self._build_evolution_container_html(raw_html)

        return raw_html

    def is_connected(self) -> bool:
        """Delegate to wrapped handle."""
        return self._handle.is_connected()

    def click_selector(self, selector: str) -> None:
        """Delegate to wrapped handle."""
        self._handle.click_selector(selector)

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        """Open a tab and track the URL for page-type detection.

        Delegates the actual navigation to the wrapped handle.

        Args:
            url: URL to navigate to.
            timeout: Maximum time in seconds, propagated to the handle.

        Returns:
            ``True`` if the tab opened successfully.
        """
        self._last_url = url
        return self._handle.open_tab(url, timeout=timeout)

    def get_tab_classes(self) -> list[str]:
        """Delegate to wrapped handle."""
        return self._handle.get_tab_classes()

    def close_last_non_root_tab(self) -> None:
        """Delegate to wrapped handle."""
        self._handle.close_last_non_root_tab()

    def restart_browser(self) -> None:
        """Delegate to wrapped handle."""
        self._handle.restart_browser()

    def shutdown(self) -> None:
        """Delegate shutdown to the wrapped handle if available."""
        shutdown_fn = getattr(self._handle, "shutdown", None)
        if callable(shutdown_fn):
            shutdown_fn()

    # ------------------------------------------------------------------
    # PSW-S11: persistent evolution PDF flow
    # ------------------------------------------------------------------

    def extract_evolutions_pdf(
        self,
        *,
        start_date: str,
        end_date: str,
        admission_key: str = "",
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Extract evolutions from the real legacy PDF report flow.

        Reuses the *already-open* persistent Playwright page/context exposed
        by the wrapped handle (``ensure_current_page()`` on the real handle,
        with a ``current_page()`` fallback for compatibility). It never
        launches a fresh browser, never calls ``subprocess``, and never shells
        out to ``path2.py``. The actual navigation/tab opening is performed by
        the adapter (``open_tab``) before this method is called; this method
        only drives the report generation, PDF download, text extraction, and
        normalisation on the current page.

        Used by :class:`PersistentExtractionAdapter` as a fallback when the
        lightweight fast paths (``evolution-data-json`` script and
        ``pre.report-text``) yield no events.

        Args:
            start_date: Window start in ``YYYY-MM-DD``.
            end_date: Window end in ``YYYY-MM-DD``.
            admission_key: Admission key to stamp on events (may be empty).
            timeout: Overall hint in seconds; honoured by the download wait.

        Returns:
            Normalised evolution dicts (possibly empty).

        Raises:
            EvolutionPdfError: On any sanitised PDF-flow failure.
        """
        page = self._resolve_active_page()
        if page is None:
            raise EvolutionPdfError(
                "Persistent handle has no active page for the evolution PDF flow"
            )
        flow = EvolutionPdfFlow(page)
        return flow.extract(
            start_date=start_date,
            end_date=end_date,
            admission_key=admission_key,
            timeout=timeout,
        )

    def _resolve_active_page(self) -> Any:
        """Return the active Playwright page from the wrapped handle.

        The real ``PlaywrightSessionHandle`` exposes ``ensure_current_page()``;
        older fakes/handles may expose ``current_page()``. Prefer the real
        accessor and fall back to the legacy one for compatibility.
        """
        for getter_name in ("ensure_current_page", "current_page"):
            getter = getattr(self._handle, getter_name, None)
            if callable(getter):
                return getter()
        return None

    # ------------------------------------------------------------------
    # Private: page type detection
    # ------------------------------------------------------------------

    def _is_admissions_page(self) -> bool:
        """Detect whether the last URL is an admissions page."""
        url_lower = self._last_url.lower()
        return any(pattern.lower() in url_lower
                   for pattern in _ADMISSIONS_URL_PATTERNS)

    def _is_evolution_page(self) -> bool:
        """Detect whether the last URL is an evolution page."""
        url_lower = self._last_url.lower()
        return any(pattern.lower() in url_lower
                   for pattern in _EVOLUTIONS_URL_PATTERNS)

    # ------------------------------------------------------------------
    # Private: container HTML builders
    # ------------------------------------------------------------------

    def _build_admission_container_html(self, raw_html: str) -> str:
        """Build synthetic admission container HTML from real legacy DOM.

        Extracts session counter (``#tempoSessao``) and the renewal popup
        (``#casca_renovasession``) from raw HTML plus admission data from the
        internações table, then builds a page containing:
        1. The session counter div (for controller health checks).
        2. The renewal popup div (so defensive popup detection still works).
        3. A ``<div id="admission-snapshot-data">`` with JSON payload.

        Args:
            raw_html: Raw page HTML from the legacy admission page.

        Returns:
            HTML string with synthetic counter + popup + snapshot container.
        """
        counter_div = _extract_block(raw_html, _TEMPO_SESSAO_RE)
        popup_div = _extract_block(raw_html, _RENEWAL_POPUP_RE)

        # Extract admissions from the legacy table
        admissions = _extract_admission_rows(raw_html)
        json_payload = json.dumps(admissions, ensure_ascii=False)

        return (
            "<html><body>\n"
            + counter_div + "\n"
            + popup_div + "\n"
            + f'<div id="admission-snapshot-data">\n{json_payload}\n</div>\n'
            + "</body></html>"
        )

    def _build_evolution_container_html(self, raw_html: str) -> str:
        """Build synthetic evolution container HTML from real legacy DOM.

        Extracts session counter, the renewal popup, and evolution data from
        the legacy page, then builds a page containing:
        1. The session counter div.
        2. The renewal popup div.
        3. A ``<div id="evolution-data">`` with JSON payload.

        Args:
            raw_html: Raw page HTML from the legacy evolution page.

        Returns:
            HTML string with synthetic counter + popup + evolution container.
        """
        counter_div = _extract_block(raw_html, _TEMPO_SESSAO_RE)
        popup_div = _extract_block(raw_html, _RENEWAL_POPUP_RE)

        # Extract evolutions from the legacy page
        evolutions = _extract_evolution_items(raw_html)
        json_payload = json.dumps(evolutions, ensure_ascii=False)

        return (
            "<html><body>\n"
            + counter_div + "\n"
            + popup_div + "\n"
            + f'<div id="evolution-data">\n{json_payload}\n</div>\n'
            + "</body></html>"
        )
