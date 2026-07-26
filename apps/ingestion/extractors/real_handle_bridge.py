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
import time
from typing import Any

from apps.ingestion.extractors.errors import is_playwright_timeout_error
from apps.ingestion.extractors.legacy_navigation import (
    NavigationError,
    NavigationTimeoutError,
    _read_and_build_snapshot,
    _remaining_ms,
    build_demographics,
    choose_overlapping_admissions,
    click_evolucao,
    click_internacoes,
    click_visualizar_report,
    ensure_search_screen,
    fill_evolution_dates,
    open_internacao_detail,
    search_patient,
    select_ascending_order,
    wait_for_report_or_no_evolutions,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE,
    DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS,
    EvolutionPdfError,
    EvolutionPdfFlow,
    EvolutionPdfTimeoutError,
    extract_pdf_text,
    normalize_pdf_report_text,
    resolve_pdf_url_from_page,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _bound_ms as _pdf_bound_ms,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _deadline_s as _pdf_deadline_s,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _remaining_ms as _pdf_remaining_ms,
)
from apps.ingestion.extractors.session_controller import SessionHandle
from apps.ingestion.extractors.session_policy import TabCleanupOutcome

logger = logging.getLogger(__name__)

# PSW-S20 R4/R7: constant sanitized message raised when the required
# evolution date inputs cannot be filled. Carries no patient record, date
# value, selector, URL, cookie, credential, or raw exception text.
_EVOLUTION_DATE_FILL_REQUIRED_MESSAGE = (
    "Required evolution date inputs could not be filled."
)

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

    def __init__(
        self,
        handle: SessionHandle,
        *,
        credentials: Any = None,
        login_timeout: int = 60,
    ) -> None:
        self._handle = handle
        self._last_url: str = ""
        # PSW-S19 R3: the bridge owns the sanitized bootstrap boundary so the
        # adapter can re-run login + #tempoSessao readiness after every restart
        # through one lifecycle owner. Credentials are held in memory only.
        self._credentials = credentials
        self._login_timeout = login_timeout

    def supports_real_evolution_actions(self) -> bool:
        """Advertise that this bridge drives the real legacy evolution actions.

        PSW-S20 R1/R2: the adapter selects the action-first evolution path
        ONLY when the session explicitly returns ``True`` here. The real
        legacy UI has no reloadable evolution deep link, so the bridge must be
        navigated through UI actions (search -> admissions -> detail ->
        Evolu\u00e7\u00e3o -> dates -> report -> PDF) rather than a synthetic
        ``/evolutions/...`` URL. Returning a real ``bool`` (not a truthy
        object) lets the adapter's ``is True`` check reject auto-created
        MagicMock capabilities.
        """
        return True

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

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        """Delegate to wrapped handle."""
        return self._handle.close_last_non_root_tab()

    def restart_browser(self) -> None:
        """Delegate to wrapped handle."""
        self._handle.restart_browser()

    def shutdown(self) -> None:
        """Delegate shutdown to the wrapped handle if available."""
        shutdown_fn = getattr(self._handle, "shutdown", None)
        if callable(shutdown_fn):
            shutdown_fn()

    def bootstrap(self) -> None:
        """Re-run the sanitized legacy login on the already-open persistent page.

        PSW-S19 R3: the handle/bridge bootstrap boundary. After a browser
        restart the persistent context is connected but UNAUTHENTICATED; this
        re-runs the canonical login flow (navigate + fill + submit + wait for
        ``#tempoSessao``) through ``bootstrap_legacy_session`` and reuses the
        existing credentials/login selectors — it never duplicates them.

        Raises:
            LegacyBootstrapError: sanitized bootstrap failure (no credential,
                cookie, or raw payload in the message).
        """
        from apps.ingestion.extractors.legacy_session_bootstrap import (
            bootstrap_legacy_session,
        )

        # ``ensure_current_page`` is the sanctioned Playwright escape hatch on
        # the concrete handle; access it defensively since the SessionHandle
        # protocol does not declare it. ``bootstrap_legacy_session`` raises a
        # sanitized ``LegacyBootstrapError`` when no page is available.
        ensure_current_page = getattr(self._handle, "ensure_current_page", None)
        page = ensure_current_page() if callable(ensure_current_page) else None
        bootstrap_legacy_session(
            page,
            credentials=self._credentials,
            login_timeout=self._login_timeout,
        )

    # ------------------------------------------------------------------
    # PSW-S12: real legacy UI action navigation for admissions
    # ------------------------------------------------------------------

    def navigate_to_admissions(self, patient_record: str) -> bool:
        """Navigate the real legacy UI to the admissions table via actions.

        Uses the already-open persistent page (from
        ``ensure_current_page()``) to perform the action sequence:
        1. Ensure search screen is visible.
        2. Fill ``#prontuarioInput`` with the patient record.
        3. Click ``Pesquisa Avan\u00e7ada`` (Advanced Search).
        4. Click ``Interna\u00e7\u00f5es`` (Admissions).
        5. Wait for ``frame_pol`` with admission table rows.
        6. Read rows and build the canonical snapshot.
        7. Update the internal page HTML so ``get_page_html()`` returns
           the synthetic container with real admission data.

        Reuses the already-open persistent session — never launches a new
        browser, never invokes ``subprocess``, never calls ``path2.py``.

        Args:
            patient_record: Patient record (prontu\u00e1rio) string.

        Returns:
            ``True`` if navigation succeeded and snapshot was built,
            ``False`` if the page was unavailable.
        """
        page = self._resolve_active_page()
        if page is None:
            logger.warning(
                "Cannot navigate to admissions: no active page available"
            )
            return False

        try:
            # Step 1: Ensure the search screen is visible.
            ensure_search_screen(page)

            # Step 2-3: Fill prontu\u00e1rio and click advanced search.
            search_patient(page, patient_record=patient_record)

            # Step 4-5: Click Interna\u00e7\u00f5es and wait for table.
            click_internacoes(page)

            # Step 6-7: Read rows and build the canonical snapshot.
            snapshot = _read_and_build_snapshot(page)

            # Build the synthetic container HTML and set it on the handle
            # so subsequent get_page_html() calls return real data.
            json_payload = json.dumps(snapshot, ensure_ascii=False)
            synthetic_html = (
                "<html><body>\n"
                '<div id="tempoSessao">'
                "Tempo: <span>00</span>:<span>29</span>:<span>01</span>"
                "</div>\n"
                f'<div id="admission-snapshot-data">\n{json_payload}\n</div>\n'
                "</body></html>"
            )

            # Inject the synthetic HTML so get_page_html() returns
            # the real data wrapped in the expected container format.
            if hasattr(self._handle, "set_html"):
                self._handle.set_html(synthetic_html)
            else:
                # Fallback: just mark the URL as admissions so
                # get_page_html() falls through to the bridge's
                # container-building path.
                self._last_url = "/consultarInternacoes.xhtml"

            return True

        except NavigationTimeoutError:
            # PSW-S17 R2/R3: a typed navigation/wait timeout MUST propagate
            # so the adapter and command record ("timeout", True). It must
            # NOT be collapsed into a fresh unchained ExtractionError.
            raise
        except NavigationError:
            # Non-timeout navigation failure: log a constant sanitized
            # message and return False so the adapter raises its own
            # sanitized ExtractionError (no URL, raw text, or patient data).
            logger.warning(
                "Legacy UI navigation to admissions failed (sanitized)"
            )
            return False
        except Exception:
            # Unexpected non-timeout error: best-effort sanitized log + False
            # so the adapter surfaces a sanitized ExtractionError.
            logger.warning(
                "Unexpected error during admissions navigation (sanitized)"
            )
            return False

    # ------------------------------------------------------------------
    # PSW-S16: real legacy demographics action navigation
    # ------------------------------------------------------------------

    # Constant sanitized messages (PSW-S16 correction: no raw text leaks).
    _DEMOGRAPHICS_TIMEOUT_MESSAGE = (
        "Demographics extraction timeout must be positive."
    )
    _DEMOGRAPHICS_NO_PAGE_MESSAGE = (
        "No active page available for demographics extraction."
    )
    _DEMOGRAPHICS_NAV_MESSAGE = (
        "Demographics legacy action navigation failed."
    )
    _DEMOGRAPHICS_UNEXPECTED_MESSAGE = (
        "Unexpected failure during demographics extraction."
    )

    def extract_demographics_via_legacy_actions(
        self,
        *,
        patient_record: str,
        timeout: int = 120,
    ) -> dict[str, str]:
        """Extract demographics by navigating the real legacy UI action flow.

        Reuses the already-open persistent page/context (never a new browser,
        subprocess, or second login) to perform the action sequence modeled
        on the working demographics script:

        1. Ensure the patient search screen is visible.
        2. Fill ``#prontuarioInput`` and click ``Pesquisa Avan\u00e7ada``.
        3. Click ``Dados do Paciente`` in the POL tree menu.
        4. Wait for ``frame_pol`` Cadastro readiness (R6).
        5. Read every demographic field into an in-memory dict.

        The returned dict uses the external keys consumed by
        :func:`~apps.ingestion.services.upsert_patient_demographics`.

        Fail-closed (PSW-S16 correction R1): no active page, search/nav
        failure, global field-read failure, or an unexpected exception raise
        a constant-message ``NavigationError`` instead of returning ``{}``.
        Raw exception text is never logged or exposed.

        Timeout (PSW-S16 R5): ``timeout`` (seconds) is a single monotonic
        budget shared across all action phases; each phase receives only the
        remaining budget, so the advertised timeout is never multiplied.

        Args:
            patient_record: Patient record (prontu\u00e1rio) string. Normalized
                to digits-only before search.
            timeout: Overall budget in seconds for the whole action sequence.

        Returns:
            Normalized in-memory demographics dict.

        Raises:
            NavigationError: On any sanitized navigation/read/timeout failure
                or unexpected exception. The message is constant and never
                contains patient data, field values, HTML, URLs, cookies,
                credentials, or raw Playwright exception text.
        """
        if timeout <= 0:
            raise NavigationError(self._DEMOGRAPHICS_TIMEOUT_MESSAGE)

        page = self._resolve_active_page()
        if page is None:
            raise NavigationError(self._DEMOGRAPHICS_NO_PAGE_MESSAGE)

        deadline_s = time.monotonic() + timeout
        try:
            ensure_search_screen(page, timeout_ms=_remaining_ms(deadline_s))
            search_patient(
                page,
                patient_record=patient_record,
                timeout_ms=_remaining_ms(deadline_s),
            )
            return build_demographics(page, timeout_ms=_remaining_ms(deadline_s))
        except NavigationError:
            # Already a constant sanitized message; propagate unchanged.
            raise
        except Exception:
            # Wrap any unexpected failure in a constant sanitized message.
            # Suppress the raw chain so no underlying text can leak.
            raise NavigationError(self._DEMOGRAPHICS_UNEXPECTED_MESSAGE) from None

    # ------------------------------------------------------------------
    # PSW-S13: real legacy evolution action navigation (full-sync)
    # ------------------------------------------------------------------

    def extract_evolutions_via_legacy_actions(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Extract evolutions by navigating the real legacy UI action flow.

        Performs the full JSP/PrimeFaces action sequence for evolution
        extraction, reusing the already-open persistent page/context:

        1. Navigate to admissions table (via PSW-S12 action navigation).
        2. Select admissions overlapping the requested date window.
        3. For each overlapping admission:
           a. Open admission detail via UI actions.
           b. Click \u201cEvolu\u00e7\u00e3o\u201d button.
           c. Fill date inputs (DD/MM/YYYY).
           d. Select ascending order (\u201cCrescente\u201d).
           e. Click visualize/generate report.
           f. Wait for report page or detect no-evolutions.
           g. If report: download PDF through existing context, extract
              text with PyMuPDF, normalise into the 5-key contract.
        4. Return all collected events.

        Never invokes subprocess, ``sync_playwright()``, or a new
        browser/context. Reuses the already-open handle and its page
        (from ``ensure_current_page()``).

        Args:
            patient_record: Patient record (prontu\u00e1rio) string.
            start_date: Window start in ``YYYY-MM-DD``.
            end_date: Window end in ``YYYY-MM-DD``.
            timeout: Overall hint in seconds for waits/downloads.

        Returns:
            List of normalised evolution dicts (possibly empty).

        Raises:
            EvolutionPdfError: On any sanitised failure during the
                evolution action flow (e.g. no overlapping admission,
                detail not found, evolution button disabled, PDF
                download failure, invalid PDF).
        """
        page = self._resolve_active_page()
        if page is None:
            logger.warning(
                "Cannot extract evolutions via legacy actions: "
                "no active page available"
            )
            return []

        # PSW-S17 R2/R3: typed navigation/wait timeouts MUST propagate as
        # typed timeouts so the run records ("timeout", True). Non-timeout
        # NavigationError failures keep the legacy empty-result behavior.
        # Step 1: Ensure search screen visible (reuse PSW-S12 helpers)
        try:
            ensure_search_screen(page)
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: search screen not available (sanitized)"
            )
            return []

        # Step 2: Search for the patient
        try:
            search_patient(page, patient_record=patient_record)
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: patient search failed (sanitized)"
            )
            return []

        # Step 3: Click Interna\u00e7\u00f5es
        try:
            click_internacoes(page)
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: Interna\u00e7\u00f5es click failed (sanitized)"
            )
            return []

        # Step 4: Read admissions and select overlapping ones
        try:
            admissions = _read_and_build_snapshot(page)
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: admissions snapshot failed (sanitized)"
            )
            return []

        overlap_failed = False
        try:
            overlapping = choose_overlapping_admissions(
                admissions,
                start_date=start_date,
                end_date=end_date,
            )
        except NavigationError:
            # PSW-S17 post-31dd3c0 (D22): a constant sanitized wrapper raised
            # OUTSIDE the handler so neither ``__cause__`` nor ``__context__``
            # carries the raw NavigationError. Raising ``from None`` inside
            # the handler only suppresses *display* of the context; the raw
            # reference would still be attached.
            overlap_failed = True
        if overlap_failed:
            raise EvolutionPdfError(
                "Nenhuma interna\u00e7\u00e3o com interse\u00e7\u00e3o "
                "foi encontrada para o intervalo solicitado."
            )

        if not overlapping:
            return []

        # Step 5: For each overlapping admission, open details and
        # generate the evolution report.
        # PSW-S17 post-cbf50c1 (D17/R1): the caller ``timeout`` is an UPPER
        # BOUND shared by the report wait, URL resolution, and download.
        all_events: list[dict[str, Any]] = []
        deadline_s = _pdf_deadline_s(timeout)

        for idx, admission in enumerate(overlapping):
            if idx > 0:
                # Re-navigate to admissions (no multi-admission optimisations)
                try:
                    click_internacoes(page)
                    admissions = _read_and_build_snapshot(page)
                except NavigationTimeoutError:
                    raise
                except NavigationError:
                    logger.warning(
                        "Evolution action flow: re-navigation failed (sanitized)"
                    )
                    continue

            admission_key = admission.get("admissionKey") or ""

            # Step 5a: Open admission detail
            try:
                open_internacao_detail(
                    page,
                    admission_key=admission_key,
                )
            except NavigationTimeoutError:
                raise
            except NavigationError:
                logger.warning(
                    "Evolution action flow: detail open failed (sanitized)"
                )
                continue

            # Step 5b: Click Evolu\u00e7\u00e3o
            try:
                click_evolucao(page)
            except NavigationTimeoutError:
                raise
            except NavigationError:
                logger.warning(
                    "Evolution action flow: Evolu\u00e7\u00e3o click failed (sanitized)"
                )
                continue

            # Step 5c: Fill dates (convert ISO to DD/MM/YYYY).
            # PSW-S20 R4: the date inputs are REQUIRED for a correct report
            # window. A fill failure (input present but not fillable) OR
            # absent inputs MUST stop report generation with a typed sanitized
            # EvolutionPdfError — never continue with default/unbounded dates.
            # The wrapper is raised OUTSIDE the ``except`` handler so neither
            # ``__cause__`` nor ``__context__`` carries the raw NavigationError.
            from apps.ingestion.extractors.persistent_evolution_pdf import (  # noqa: PLC0415
                _format_br_date,
            )

            br_start = _format_br_date(start_date)
            br_end = _format_br_date(end_date)
            dates_filled = False
            date_fill_failed = False
            try:
                dates_filled = fill_evolution_dates(
                    page,
                    start_date_br=br_start,
                    end_date_br=br_end,
                )
            except NavigationTimeoutError:
                raise
            except NavigationError:
                date_fill_failed = True
            if date_fill_failed or not dates_filled:
                raise EvolutionPdfError(_EVOLUTION_DATE_FILL_REQUIRED_MESSAGE)

            # Step 5d: Select ascending order
            try:
                select_ascending_order(page)
            except NavigationTimeoutError:
                raise
            except Exception:
                logger.debug(
                    "Evolution action flow: ascending order select "
                    "failed (no-op)"
                )

            # Step 5e: Click visualize
            try:
                click_visualizar_report(page)
            except NavigationTimeoutError:
                raise
            except NavigationError:
                logger.warning(
                    "Evolution action flow: visualize click failed (sanitized)"
                )
                continue

            # Step 5f: Wait for report or detect no-evolutions.
            # PSW-S17 R2/R3: polling-budget expiry raises a typed
            # NavigationTimeoutError; only an explicit no-evolutions dialog
            # may yield the False (skip) result. The wait is bounded by the
            # remaining caller budget (never a flat 120s that exceeds it).
            try:
                report_ready = wait_for_report_or_no_evolutions(
                    page,
                    timeout_ms=_pdf_bound_ms(deadline_s, 120_000),
                )
            except NavigationTimeoutError:
                raise
            if not report_ready:
                logger.debug(
                    "Evolution action flow: explicit no-evolutions dialog "
                    "for this admission (sanitized)"
                )
                continue

            # Step 5g: Download PDF through existing context. URL resolution
            # and download share the remaining caller budget (D17/R1).
            try:
                pdf_url = self._resolve_pdf_url_from_report_page(
                    page, deadline_s
                )
            except EvolutionPdfTimeoutError:
                # PSW-S17 post-cbf50c1 (D17): typed bounded-locator timeout
                # MUST propagate; it must not be swallowed as a generic
                # URL-resolution failure.
                raise
            except Exception:
                logger.warning(
                    "Evolution action flow: PDF URL resolution failed (sanitized)"
                )
                continue

            if not pdf_url:
                continue

            try:
                pdf_bytes = self._download_pdf(
                    page,
                    pdf_url,
                    deadline_s,
                )
            except EvolutionPdfTimeoutError:
                raise
            except Exception:
                logger.warning(
                    "Evolution action flow: PDF download failed (sanitized)"
                )
                continue

            # Step 5h: Extract text and normalise (D21: deadline-checked
            # boundaries; typed timeouts propagate, non-timeout
            # EvolutionPdfError skips this admission).
            try:
                raw_text = extract_pdf_text(pdf_bytes)
            except EvolutionPdfTimeoutError:
                raise
            except EvolutionPdfError:
                logger.warning(
                    "Evolution action flow: PDF text extraction "
                    "failed (sanitized)"
                )
                continue
            # After extraction / before normalization.
            _pdf_remaining_ms(deadline_s)
            try:
                events = normalize_pdf_report_text(
                    raw_text,
                    admission_key=admission_key,
                )
            except EvolutionPdfTimeoutError:
                raise
            except EvolutionPdfError:
                logger.warning(
                    "Evolution action flow: PDF text normalization "
                    "failed (sanitized)"
                )
                continue
            # After normalization.
            _pdf_remaining_ms(deadline_s)
            all_events.extend(events)

        return all_events

    def _resolve_pdf_url_from_report_page(
        self, page: Any, deadline_s: float | None = None
    ) -> str | None:
        """Resolve a PDF URL from the report page via bounded locator ops.

        PSW-S17 post-cbf50c1 (D17/R1): this MUST NOT call the unbounded
        ``page.content()``. It delegates to the single shared resolver
        (:func:`resolve_pdf_url_from_page`) which reads the PDF object
        ``data`` attribute with a bounded Playwright timeout and falls back
        to viewer frame URLs. A bounded timeout raises
        :class:`EvolutionPdfTimeoutError`.

        Args:
            page: A Playwright ``Page`` object with a rendered report.
            deadline_s: Shared monotonic deadline (seconds). Defaults to a
                conservative 120-second budget when the caller has none.

        Returns:
            The PDF URL string, or ``None`` if unresolvable.

        Raises:
            EvolutionPdfTimeoutError: on a bounded locator timeout or
                deadline expiry.
        """
        if deadline_s is None:
            deadline_s = _pdf_deadline_s(120)
        base_url = self._safe_page_url(page)
        return resolve_pdf_url_from_page(
            page, deadline_s=deadline_s, base_url=base_url
        )

    def _download_pdf(
        self,
        page: Any,
        pdf_url: str,
        deadline_s: float,
    ) -> bytes:
        """Download PDF bytes through the existing browser context.

        PSW-S17 post-31dd3c0 (D21): the shared monotonic ``deadline_s`` is
        observed around ``request.get()`` and ``response.body()``. A fake or
        implementation that ignores its supplied timeout and overruns the
        deadline is caught at the next boundary as
        ``EvolutionPdfTimeoutError``; a public real Playwright timeout is
        classified to the same typed error with a constant sanitized
        message. Boundary checks detect/ classify an overrun after a
        non-timeout-capable operation returns; they do not interrupt it.

        Args:
            page: A Playwright ``Page`` object.
            pdf_url: The PDF URL to download (used only for the request;
                never logged or surfaced).
            deadline_s: Shared monotonic deadline (seconds).

        Returns:
            Raw PDF bytes.

        Raises:
            EvolutionPdfTimeoutError: on a Playwright/request timeout or
                deadline expiry.
            EvolutionPdfError: any other download failure.
        """
        context = getattr(page, "context", None)
        request = getattr(context, "request", None) if context is not None else None
        if request is None:
            raise EvolutionPdfError(
                "Browser context unavailable for PDF download"
            )

        # Pre-get boundary: _pdf_bound_ms checks the deadline and bounds it.
        timeout_ms = _pdf_bound_ms(deadline_s, DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS)
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
                    "Evolution action flow: PDF download request failed "
                    "(sanitized, non-timeout)"
                )
        if get_outcome == "timeout":
            raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE)
        if get_outcome == "failed":
            raise EvolutionPdfError(
                "Falha ao baixar o PDF do relatório de evolução"
            )
        assert response is not None  # get_outcome == "ok" implies a response

        # After request.get(): catch a fake that ignored its timeout.
        _pdf_remaining_ms(deadline_s)

        if not getattr(response, "ok", False):
            raise EvolutionPdfError(
                "Falha ao baixar o PDF do relatório de evolução"
            )
        # Immediately before response.body().
        _pdf_remaining_ms(deadline_s)
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
            raise EvolutionPdfError(
                "Falha ao ler o corpo do PDF do relatório de evolução"
            )
        # Immediately after response.body().
        _pdf_remaining_ms(deadline_s)

        return bytes(body or b"")

    @staticmethod
    def _safe_page_url(page: Any) -> str:
        """Safely extract the page URL (never leaks payloads)."""
        try:
            return str(page.url or "")
        except Exception:
            return ""

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

        Returns ``None`` only when no getter is available OR every available
        getter returned ``None``.
        """
        for getter_name in ("ensure_current_page", "current_page"):
            getter = getattr(self._handle, getter_name, None)
            if callable(getter):
                page = getter()
                if page is not None:
                    return page
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
