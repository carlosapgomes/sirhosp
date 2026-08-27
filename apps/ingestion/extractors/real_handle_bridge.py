"""Real Handle Bridge for legacy UI extraction (PSW-S9).

Provides a :class:`RealHandleBridge` that wraps a real
``PlaywrightSessionHandle`` (or any ``SessionHandle``) and translates
real legacy UI DOM data into the synthetic container format expected by
:class:`~persistent_extraction_adapter.PersistentExtractionAdapter`.

The real legacy UI does NOT produce ``<div id="admission-snapshot-data">``
or ``<div id="evolution-data">`` containers. This bridge renders the
extracted data inside those synthetic containers so the existing adapter
can consume it. RPAP-S1: the admissions snapshot is captured from the
``frame_pol`` iframe and held in job-scoped bridge memory; it is never
re-read from the top-level ``page.content()`` (which lacks the iframe
table) and never requires the fake-only ``set_html()``.

Design (per ``design.md`` Decision 9 and PSW-S9 scope):
- Bridge is a thin wrapper implementing the ``SessionHandle`` protocol.
- ``get_page_html()`` serves the captured admissions snapshot from bridge
  memory; for evolution pages it extracts data from the real legacy HTML
  structure and wraps it in the expected synthetic container format.
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
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from apps.ingestion.extractors.errors import (
    ExtractionTimeoutError,
    is_playwright_timeout_error,
)
from apps.ingestion.extractors.legacy_navigation import (
    SEL_FRAME_POL,
    NavigationError,
    NavigationTimeoutError,
    _read_and_build_snapshot,
    _remaining_ms,
    build_chunks_for_interval,
    build_demographics,
    choose_overlapping_admissions,
    click_evolucao,
    click_internacoes,
    click_visualizar_report,
    ensure_search_screen,
    fill_evolution_dates,
    go_back_to_detail_from_report,
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
    _format_br_date,
    assert_pdf_response_signature,
    extract_pdf_text,
    normalize_pdf_report_text,
    read_locator_attribute,
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

# PSW-S22 R2/R6: the real legacy report page exposes a JSF ``#printLinks``
# form whose POST returns the PDF bytes when no direct PDF URL is resolvable.
# Selectors are isolated here so they are testable with fakes and never
# coupled to the portal web layer. The constant sanitized message is raised
# when the form, its ``action``, or the ``javax.faces.ViewState`` hidden
# input is missing (BEFORE any request is attempted). It carries no URL,
# cookie, credential, patient data, or raw HTML.
_PRINT_LINKS_FORM_SELECTOR = "#printLinks"
_PRINT_LINKS_VIEWSTATE_SELECTOR = (
    '#printLinks input[name="javax.faces.ViewState"]'
)
_PRINT_LINKS_FORM_ACTION_ATTR = "action"
_PRINT_LINKS_VIEWSTATE_ATTR = "value"
_EVOLUTION_PDF_FORM_UNRESOLVED_MESSAGE = (
    "Evolution report download form could not be resolved"
)


def _coerce_admission_date(value: Any, fallback: date) -> date:
    """Parse an admission date (ISO ``YYYY-MM-DD`` or BR ``DD/MM/YYYY``).

    PSW-S21 R5: admissions come from the canonical snapshot as ISO strings.
    Open-ended admissions (empty ``admissionEnd``) and any unparseable value
    fall back to the requested bound, mirroring ``path2``'s
    ``admission_end = current_admission["admissionEnd"] or requested_end``
    semantics. This never raises so the per-admission window stays bounded
    even for partial/defensive inputs.
    """
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return fallback


def _log_recoverable_chunk_failure(
    reason: str, chunk_start: date, chunk_end: date
) -> None:
    """Log a recoverable per-chunk failure with its bounded ISO window only.

    PSW-S21-C1 R8: records exactly the bounded operational window
    (``window_start``/``window_end``) alongside a constant sanitized reason so
    the responsible bounded chunk is identifiable without patient data. Accepts
    ONLY a constant reason and the chunk dates; never an exception or
    identifier. The formatted record never carries patient record, admission
    key, ward/bed, event/PDF content, URL, selector, cookie, credential, HTML,
    or raw exception type/text.
    """
    logger.warning(
        "%s window_start=%s window_end=%s",
        reason,
        chunk_start.isoformat(),
        chunk_end.isoformat(),
    )

# ---------------------------------------------------------------------------
# URL patterns for page-type detection
# ---------------------------------------------------------------------------

_EVOLUTIONS_URL_PATTERNS: list[str] = [
    "relatorioAnaEvoInternacaoPdf",
    "consultaDetalheInternacao",
    "/evolutions/",
    "evolucao",
]

# ---------------------------------------------------------------------------
# Regex patterns for extracting data from legacy DOM
# ---------------------------------------------------------------------------

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

def _extract_block(html: str, pattern: re.Pattern[str]) -> str:
    """Return the first regex match group from ``html``, or empty string.

    Used to preserve page fragments (session counter, renewal popup) when
    rebuilding page HTML for the adapter.
    """
    match = pattern.search(html)
    return match.group(1) if match else ""


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
    overrides ``get_page_html()``. RPAP-S1: after
    ``navigate_to_admissions()`` reads the admission table inside
    ``frame_pol``, the bridge keeps that normalized snapshot in job-scoped
    memory and ``get_page_html()`` returns exactly it — even though the
    concrete handle has no fake-only ``set_html()`` and the top-level
    ``page.content()`` never contains the iframe table. Evolution data is
    still extracted from the real legacy page structure at read time.

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
        # RPAP-S1: job-scoped synthetic container for the admissions snapshot
        # captured from ``frame_pol``. Held in memory ONLY for the current
        # job; cleared at every lifecycle boundary and never persisted.
        self._admissions_snapshot_html: str | None = None
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

        RPAP-S1: when an admissions snapshot was captured from ``frame_pol``
        for the current job, returns exactly that stored payload in the
        ``<div id="admission-snapshot-data">`` container — never a re-read of
        the top-level HTML (which lacks the iframe table). Otherwise, when
        the last opened URL is an evolution page, extracts real legacy data
        from the DOM into the ``<div id="evolution-data">`` container.

        For non-evolution pages (e.g. root/safe-renewal tabs), returns the
        raw HTML unchanged.

        Returns:
            Page HTML string, potentially containing synthetic container
            divs with extracted data as JSON payloads.
        """
        if self._admissions_snapshot_html is not None:
            return self._admissions_snapshot_html

        raw_html = self._handle.get_page_html()

        if not self._last_url:
            return raw_html

        # Determine page type from URL (admissions snapshots are served from
        # bridge memory; only evolution pages are rebuilt from the DOM).
        if self._is_evolution_page():
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
        # RPAP-S1 R2: a new navigation starts a fresh job — any admissions
        # snapshot from the previous job must not survive it.
        self._clear_admissions_snapshot()
        self._last_url = url
        return self._handle.open_tab(url, timeout=timeout)

    def get_tab_classes(self) -> list[str]:
        """Delegate to wrapped handle."""
        return self._handle.get_tab_classes()

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        """Delegate to wrapped handle and drop the job-scoped snapshot.

        RPAP-S1 R2: cleanup is a job boundary — the snapshot is cleared in a
        ``finally`` so it is dropped even when the delegated cleanup fails.
        """
        try:
            return self._handle.close_last_non_root_tab()
        finally:
            self._clear_admissions_snapshot()

    def restart_browser(self) -> None:
        """Restart the handle and discard job state from the old browser.

        RPAP-S1 R2: the snapshot is dropped in a ``finally`` so it is cleared
        even when the delegated restart fails, without masking its error.
        """
        try:
            self._handle.restart_browser()
        finally:
            self._clear_admissions_snapshot()
            self._last_url = ""

    def shutdown(self) -> None:
        """Delegate shutdown to the wrapped handle if available.

        RPAP-S1 R2: the job-scoped snapshot is dropped even when the
        delegated shutdown raises.
        """
        try:
            shutdown_fn = getattr(self._handle, "shutdown", None)
            if callable(shutdown_fn):
                shutdown_fn()
        finally:
            self._clear_admissions_snapshot()

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
        # RPAP-S1 R2: bootstrap re-authenticates a fresh session — the
        # previous job's admissions snapshot must not survive it.
        self._clear_admissions_snapshot()

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
        7. Serialize the snapshot into job-scoped bridge memory so
           ``get_page_html()`` returns the synthetic container with the
           exact captured data (no ``set_html()``, no top-level re-read).

        Reuses the already-open persistent session — never launches a new
        browser, never invokes ``subprocess``, never calls ``path2.py``.

        Args:
            patient_record: Patient record (prontu\u00e1rio) string.

        Returns:
            ``True`` if navigation succeeded and snapshot was built,
            ``False`` if the page was unavailable.
        """
        # RPAP-S1 R2: a new navigation starts a fresh job — any snapshot
        # from the previous job is dropped BEFORE the first UI action.
        self._clear_admissions_snapshot()

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

            # Step 6-7: Read rows and build the canonical snapshot. The
            # table lives ONLY inside ``frame_pol``; the top-level page
            # content() never contains it. RPAP-S1: the bridge serializes
            # the snapshot into job-scoped memory (same container contract
            # the adapter consumes) instead of relying on the fake-only
            # ``set_html()`` or re-reading the top-level HTML.
            snapshot = _read_and_build_snapshot(page)
            self._admissions_snapshot_html = self._build_admissions_snapshot_html(
                snapshot, self._handle.get_page_html()
            )

            return True

        except NavigationTimeoutError:
            # PSW-S17 R2/R3: a typed navigation/wait timeout MUST propagate
            # so the adapter and command record ("timeout", True). It must
            # NOT be collapsed into a fresh unchained ExtractionError.
            raise
        except ExtractionTimeoutError:
            # RPAP-S1: a real Playwright timeout from the top-level content
            # read keeps the typed timeout taxonomy (never a plain False).
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
        # RPAP-S1 R2: this action flow navigates the legacy UI — the
        # previous job's admissions snapshot must not survive it.
        self._clear_admissions_snapshot()

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
        # RPAP-S1 R2: this action flow navigates the legacy UI — the
        # previous job's admissions snapshot must not survive it.
        self._clear_admissions_snapshot()

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
        #
        # PSW-S20-C1 A2: ONE cooperative deadline bounds the COMPLETE action
        # sequence, from the first required UI action through report wait and
        # download. Created before any action; never reset per admission/helper.
        deadline_s = _pdf_deadline_s(timeout)

        # Step 1: Ensure search screen visible (reuse PSW-S12 helpers)
        try:
            ensure_search_screen(page, timeout_ms=_pdf_remaining_ms(deadline_s))
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: search screen not available (sanitized)"
            )
            return []

        # Step 2: Search for the patient
        try:
            search_patient(
                page,
                patient_record=patient_record,
                timeout_ms=_pdf_remaining_ms(deadline_s),
            )
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: patient search failed (sanitized)"
            )
            return []

        # Step 3: Click Interna\u00e7\u00f5es
        try:
            click_internacoes(page, timeout_ms=_pdf_remaining_ms(deadline_s))
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: Interna\u00e7\u00f5es click failed (sanitized)"
            )
            return []

        # Step 4: Read admissions and select overlapping ones
        try:
            admissions = _read_and_build_snapshot(
                page, timeout_ms=_pdf_remaining_ms(deadline_s)
            )
        except NavigationTimeoutError:
            raise
        except NavigationError:
            logger.warning(
                "Evolution action flow: admissions snapshot failed (sanitized)"
            )
            return []

        # PSW-S20-C2: the snapshot is a non-interruptible operation. After it
        # returns, classify an expired shared deadline BEFORE interpreting
        # the snapshot as a selection input — an overrun must not masquerade as
        # an empty/no-overlap functional result. Propagates a typed
        # EvolutionPdfTimeoutError through the PSW-S17 taxonomy.
        _pdf_remaining_ms(deadline_s)

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
        # PSW-S20-C2: overlap selection is non-interruptible. After it returns
        # or raises a functional NavigationError, classify an expired shared
        # deadline BEFORE converting the failure to a no-overlap error or
        # interpreting an empty result. Propagates a typed
        # EvolutionPdfTimeoutError (never caught/wrapped here).
        _pdf_remaining_ms(deadline_s)
        if overlap_failed:
            raise EvolutionPdfError(
                "Nenhuma interna\u00e7\u00e3o com interse\u00e7\u00e3o "
                "foi encontrada para o intervalo solicitado."
            )

        if not overlapping:
            return []

        # PSW-S21 R1/R2/R3: requested window bounds for the per-admission
        # clipping. Each admission is processed over its OWN bounded window
        # (max(requested, admissionStart) .. min(requested, admissionEnd)),
        # then split into at-most-15-day chunks with canonical overlap via the
        # canonical dependency-free chunking module.
        requested_start = _coerce_admission_date(start_date, date.today())
        requested_end = _coerce_admission_date(end_date, date.today())

        # Step 5: For each overlapping admission, open details and generate
        # the evolution report for every bounded chunk. The shared deadline
        # (created above before the first action) bounds every per-admission
        # and per-chunk helper too.
        all_events: list[dict[str, Any]] = []

        for idx, admission in enumerate(overlapping):
            if idx > 0:
                # Re-navigate to admissions (no multi-admission optimisations)
                try:
                    click_internacoes(page, timeout_ms=_pdf_remaining_ms(deadline_s))
                    admissions = _read_and_build_snapshot(
                        page, timeout_ms=_pdf_remaining_ms(deadline_s)
                    )
                except NavigationTimeoutError:
                    raise
                except NavigationError:
                    logger.warning(
                        "Evolution action flow: re-navigation failed (sanitized)"
                    )
                    continue
                # PSW-S20-C2: classify an overrun re-navigation snapshot
                # before the next admission action uses the refreshed state.
                _pdf_remaining_ms(deadline_s)

            # PSW-S21 R5: keep each real admission key on its events and
            # process admissions in deterministic (snapshot) order.
            admission_key = admission.get("admissionKey") or ""

            # PSW-S21 R1/R2: clip the requested window to this admission and
            # build the bounded chunk windows (canonical algorithm).
            adm_start = _coerce_admission_date(
                admission.get("admissionStart"), requested_start
            )
            adm_end = _coerce_admission_date(
                admission.get("admissionEnd"), requested_end
            )
            effective_start = max(requested_start, adm_start)
            effective_end = min(requested_end, adm_end)
            if effective_end < effective_start:
                logger.debug(
                    "Evolution action flow: admission has no effective "
                    "overlap after clipping (sanitized)"
                )
                continue

            chunks = build_chunks_for_interval(effective_start, effective_end)

            # Step 5a: Open admission detail once per admission.
            try:
                open_internacao_detail(
                    page,
                    admission_key=admission_key,
                    timeout_ms=_pdf_remaining_ms(deadline_s),
                )
            except NavigationTimeoutError:
                raise
            except NavigationError:
                logger.warning(
                    "Evolution action flow: detail open failed (sanitized)"
                )
                continue

            # PSW-S21 R6: between consecutive chunks of the SAME admission,
            # restore the detail page before re-opening the evolution modal.
            last_chunk_had_report = False
            for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
                if chunk_idx > 0 and last_chunk_had_report:
                    try:
                        go_back_to_detail_from_report(
                            page, timeout_ms=_pdf_remaining_ms(deadline_s)
                        )
                    except NavigationTimeoutError:
                        raise
                    except NavigationError:
                        _log_recoverable_chunk_failure(
                            "Evolution action flow: between-chunk restore "
                            "failed (sanitized)",
                            chunk_start,
                            chunk_end,
                        )
                        break

                # Step 5b: Click Evolu\u00e7\u00e3o to open the date modal.
                try:
                    click_evolucao(page, timeout_ms=_pdf_remaining_ms(deadline_s))
                except NavigationTimeoutError:
                    raise
                except NavigationError:
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: Evolu\u00e7\u00e3o click "
                        "failed (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    break

                # Step 5c: Fill the BOUNDED chunk dates (convert to DD/MM/YYYY).
                # PSW-S20 R4: the date inputs are REQUIRED for a correct
                # report window. A fill failure (input present but not
                # fillable) OR absent inputs MUST stop report generation with
                # a typed sanitized EvolutionPdfError — never continue with
                # default/unbounded dates. Raised OUTSIDE the ``except``
                # handler so neither ``__cause__`` nor ``__context__`` carries
                # the raw NavigationError.
                br_start = _format_br_date(chunk_start.isoformat())
                br_end = _format_br_date(chunk_end.isoformat())
                dates_filled = False
                date_fill_failed = False
                try:
                    dates_filled = fill_evolution_dates(
                        page,
                        start_date_br=br_start,
                        end_date_br=br_end,
                        timeout_ms=_pdf_remaining_ms(deadline_s),
                    )
                except NavigationTimeoutError:
                    raise
                except NavigationError:
                    date_fill_failed = True
                if date_fill_failed or not dates_filled:
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: required date inputs could "
                        "not be filled (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    raise EvolutionPdfError(_EVOLUTION_DATE_FILL_REQUIRED_MESSAGE)

                # Step 5d: Select ascending order (optional no-op on failure).
                try:
                    select_ascending_order(
                        page, timeout_ms=_pdf_remaining_ms(deadline_s)
                    )
                except NavigationTimeoutError:
                    raise
                except Exception:
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: ascending order select failed (no-op)",
                        chunk_start,
                        chunk_end,
                    )

                # Step 5e: Click visualize.
                try:
                    click_visualizar_report(
                        page, timeout_ms=_pdf_remaining_ms(deadline_s)
                    )
                except NavigationTimeoutError:
                    raise
                except NavigationError:
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: visualize click "
                        "failed (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    break

                # Step 5f: Wait for report or detect no-evolutions.
                # PSW-S17 R2/R3: polling-budget expiry raises a typed
                # NavigationTimeoutError; only an explicit no-evolutions
                # dialog may yield the False (skip) result.
                # PSW-S21 R7: a genuine empty chunk returns no fake events
                # and does NOT discard events already collected.
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
                        "for this chunk (sanitized)"
                    )
                    last_chunk_had_report = False
                    continue

                # Step 5g: Acquire PDF bytes through the existing context.
                # PSW-S22 R1/R2: a valid direct PDF URL uses an authenticated
                # GET; otherwise the authenticated ``#printLinks`` JSF form
                # POST fallback is attempted. PSW-S17 post-cbf50c1 (D17): a
                # typed bounded-locator timeout during URL resolution MUST
                # propagate as a typed timeout.
                try:
                    pdf_url = self._resolve_pdf_url_from_report_page(
                        page, deadline_s
                    )
                except EvolutionPdfTimeoutError:
                    raise
                except Exception:
                    # Non-timeout resolution failure: fall through to the
                    # ``#printLinks`` form POST fallback (PSW-S22 R2) rather
                    # than skipping the chunk.
                    pdf_url = None

                try:
                    if pdf_url:
                        pdf_bytes = self._download_pdf(
                            page, pdf_url, deadline_s
                        )
                    else:
                        pdf_bytes = self._download_pdf_via_print_links_form(
                            page, deadline_s
                        )
                except EvolutionPdfTimeoutError:
                    raise
                except Exception:
                    # R6: typed sanitized failures (missing form/action/
                    # ViewState, non-success HTTP, non-PDF body) are
                    # recoverable per-chunk skips that preserve priors.
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: PDF acquisition "
                        "failed (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    last_chunk_had_report = True
                    continue

                # Step 5h: Extract text and normalise (D21: deadline-checked
                # boundaries; typed timeouts propagate, non-timeout
                # EvolutionPdfError skips this chunk but preserves priors).
                try:
                    raw_text = extract_pdf_text(pdf_bytes)
                except EvolutionPdfTimeoutError:
                    raise
                except EvolutionPdfError:
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: PDF text extraction "
                        "failed (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    last_chunk_had_report = True
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
                    _log_recoverable_chunk_failure(
                        "Evolution action flow: PDF text normalization "
                        "failed (sanitized)",
                        chunk_start,
                        chunk_end,
                    )
                    last_chunk_had_report = True
                    continue
                # After normalization.
                _pdf_remaining_ms(deadline_s)
                all_events.extend(events)
                last_chunk_had_report = True

        return all_events

    def _resolve_pdf_url_from_report_page(
        self, page: Any, deadline_s: float | None = None
    ) -> str | None:
        """Resolve a PDF URL from the report iframe via bounded locator ops.

        The legacy report and its PDF ``object`` live inside ``frame_pol``.
        Resolve that frame first and delegate to the single shared resolver
        (:func:`resolve_pdf_url_from_page`), which reads the PDF object
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
        report_owner = self._resolve_report_frame(page)
        if report_owner is None:
            # Preserve the standalone/top-level flow used by older source
            # pages and deterministic fakes.
            report_owner = page
            base_url = self._safe_page_url(page)
        else:
            base_url = self._safe_frame_url(report_owner)
        return resolve_pdf_url_from_page(
            report_owner, deadline_s=deadline_s, base_url=base_url
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
        return self._read_and_validate_pdf_body(response, deadline_s)

    def _read_and_validate_pdf_body(
        self, response: Any, deadline_s: float
    ) -> bytes:
        """Read + classify + validate a PDF response body (shared GET/POST).

        PSW-S17 post-31dd3c0 (D21) + PSW-S22 R5: observes the shared
        monotonic ``deadline_s`` immediately before and after
        ``response.body()``, classifies a public real Playwright timeout as
        :class:`EvolutionPdfTimeoutError` and any other body failure as
        :class:`EvolutionPdfError` (raised OUTSIDE the ``except`` handler so
        neither ``__cause__`` nor ``__context__`` carries the raw exception),
        then validates the content-type (when present) and the ``%PDF-``
        signature before the bytes are returned for parsing.
        """
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
        # PSW-S17 D21: raised OUTSIDE the except handler.
        if body_outcome == "timeout":
            raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE)
        if body_outcome == "failed":
            raise EvolutionPdfError(
                "Falha ao ler o corpo do PDF do relatório de evolução"
            )
        # Immediately after response.body().
        _pdf_remaining_ms(deadline_s)
        body_bytes = bytes(body or b"")
        # PSW-S22 R5: validate content-type + %PDF- signature before parsing.
        assert_pdf_response_signature(response, body_bytes)
        return body_bytes

    # ------------------------------------------------------------------
    # PSW-S22: authenticated #printLinks JSF form POST fallback
    # ------------------------------------------------------------------

    def _download_pdf_via_print_links_form(
        self, page: Any, deadline_s: float
    ) -> bytes:
        """PSW-S22 R2: authenticated JSF POST fallback via ``#printLinks``.

        Used when no valid direct PDF URL is resolvable. Parses the form
        ``action`` and the ``javax.faces.ViewState`` hidden input through
        bounded locator operations (no ``page.content()``) and POSTs the
        required JSF fields through ``page.context.request``. The existing
        authenticated context cookies/session are used implicitly (R3);
        cookie or authorization values are never copied or logged. The
        bounded chunk timeout is propagated to the POST (R4) and the response
        is validated per R5.

        R6: a missing form/action/ViewState surfaces as a typed sanitized
        :class:`EvolutionPdfError` BEFORE any request is attempted. R7: PDF
        bytes stay in memory; no filesystem artifact is created.

        Args:
            page: A Playwright-like ``Page`` with the rendered report.
            deadline_s: Shared monotonic deadline (seconds).

        Returns:
            Raw PDF bytes.

        Raises:
            EvolutionPdfTimeoutError: On a bounded locator/POST timeout or
                deadline expiry.
            EvolutionPdfError: On a missing form/action/ViewState,
                non-success HTTP, or non-PDF body.
        """
        # Pre-parse boundary: deadline check before any locator operation.
        _pdf_remaining_ms(deadline_s)

        # PSW-S22-C1 A: the report and ``#printLinks`` form live inside the
        # ``frame_pol`` iframe (mirrors ``wait_for_report_or_no_evolutions``
        # and the working ``path2.baixar_pdf_via_formulario_relatorio``
        # reference). ``page`` remains the owner of ``context.request``.
        report_frame = self._resolve_report_frame(page)
        if report_frame is None:
            raise EvolutionPdfError(_EVOLUTION_PDF_FORM_UNRESOLVED_MESSAGE)

        action = self._read_print_links_attribute(
            report_frame, _PRINT_LINKS_FORM_SELECTOR,
            _PRINT_LINKS_FORM_ACTION_ATTR, deadline_s,
        )
        view_state = self._read_print_links_attribute(
            report_frame, _PRINT_LINKS_VIEWSTATE_SELECTOR,
            _PRINT_LINKS_VIEWSTATE_ATTR, deadline_s,
        )
        # R6: missing form/action/ViewState -> typed sanitized failure;
        # no request.
        if not action or not view_state:
            raise EvolutionPdfError(_EVOLUTION_PDF_FORM_UNRESOLVED_MESSAGE)

        # PSW-S22-C1 A: resolve a relative action against the report-frame
        # URL, not the top-level page URL.
        action_url = urljoin(self._safe_frame_url(report_frame), action)
        return self._post_print_links_form(
            page, action_url, view_state, deadline_s
        )

    def _resolve_report_frame(self, page: Any) -> Any:
        """Resolve the existing ``frame_pol`` report frame (never raises)."""
        try:
            return page.frame(name=SEL_FRAME_POL)
        except Exception:  # noqa: BLE001 - sanitized
            return None

    def _read_print_links_attribute(
        self,
        owner: Any,
        selector: str,
        attribute: str,
        deadline_s: float,
    ) -> str | None:
        """Read a ``#printLinks`` form attribute from the report frame.

        PSW-S22-C1 A: ``owner`` is the ``frame_pol`` report frame (never the
        top-level page). Returns the attribute value, or ``None`` for
        absence / non-timeout read failure. Raises
        :class:`EvolutionPdfTimeoutError` on a bounded Playwright timeout.
        """
        try:
            locator = owner.locator(selector)
        except Exception:  # noqa: BLE001 - sanitized
            return None
        return read_locator_attribute(locator, attribute, deadline_s)

    def _post_print_links_form(
        self,
        page: Any,
        action_url: str,
        view_state: str,
        deadline_s: float,
    ) -> bytes:
        """POST the ``#printLinks`` JSF form through the existing context.

        PSW-S22 R2/R3/R4: reuses ``page.context.request`` (the existing
        authenticated session) and propagates the bounded deadline. The POST
        body carries only the constant JSF field names and the parsed
        ViewState; no cookie, authorization, patient, URL, or raw-payload
        value is logged or surfaced.
        """
        context = getattr(page, "context", None)
        request = getattr(context, "request", None) if context is not None else None
        if request is None:
            raise EvolutionPdfError(
                "Browser context unavailable for PDF download"
            )

        # Pre-post boundary: _pdf_bound_ms checks the deadline and bounds it.
        timeout_ms = _pdf_bound_ms(deadline_s, DEFAULT_PDF_DOWNLOAD_TIMEOUT_MS)
        form_fields = {
            "printLinks": "printLinks",
            "downloadLinkAjax": "downloadLinkAjax",
            "javax.faces.ViewState": view_state,
        }
        post_outcome = "ok"
        response = None
        try:
            response = request.post(
                action_url, form=form_fields, timeout=timeout_ms
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            post_outcome = (
                "timeout" if is_playwright_timeout_error(exc) else "failed"
            )
            if post_outcome == "failed":
                logger.warning(
                    "Evolution action flow: PDF form POST request failed "
                    "(sanitized, non-timeout)"
                )
        # PSW-S17 D21: raised OUTSIDE the except handler.
        if post_outcome == "timeout":
            raise EvolutionPdfTimeoutError(_EVOLUTION_PDF_DOWNLOAD_TIMEOUT_MESSAGE)
        if post_outcome == "failed":
            raise EvolutionPdfError(
                "Falha ao baixar o PDF do relatório de evolução"
            )
        assert response is not None  # post_outcome == "ok" implies a response

        # After request.post(): catch a fake that ignored its timeout.
        _pdf_remaining_ms(deadline_s)

        if not getattr(response, "ok", False):
            raise EvolutionPdfError(
                "Falha ao baixar o PDF do relatório de evolução"
            )
        return self._read_and_validate_pdf_body(response, deadline_s)

    @staticmethod
    def _safe_page_url(page: Any) -> str:
        """Safely extract the page URL (never leaks payloads)."""
        try:
            return str(page.url or "")
        except Exception:
            return ""

    @staticmethod
    def _safe_frame_url(frame: Any) -> str:
        """Safely extract the report-frame URL (never leaks payloads)."""
        try:
            return str(frame.url or "")
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
    # Private: job-scoped admissions snapshot (RPAP-S1)
    # ------------------------------------------------------------------

    def _clear_admissions_snapshot(self) -> None:
        """Drop the job-scoped admissions snapshot (RPAP-S1 R2).

        Called before every new navigation and after cleanup, restart,
        bootstrap, shutdown, or navigation failure so no later job can
        receive an earlier patient's payload.
        """
        self._admissions_snapshot_html = None

    # ------------------------------------------------------------------
    # Private: page type detection
    # ------------------------------------------------------------------

    def _is_evolution_page(self) -> bool:
        """Detect whether the last URL is an evolution page."""
        url_lower = self._last_url.lower()
        return any(pattern.lower() in url_lower
                   for pattern in _EVOLUTIONS_URL_PATTERNS)

    # ------------------------------------------------------------------
    # Private: container HTML builders
    # ------------------------------------------------------------------

    def _build_admissions_snapshot_html(
        self, snapshot: list[dict[str, Any]], raw_html: str
    ) -> str:
        """Build the synthetic admissions container from the captured snapshot.

        RPAP-S1: the single constructor for the admissions container. The
        JSON payload is the EXACT normalized snapshot read from ``frame_pol``
        and held in bridge memory; only the session counter
        (``#tempoSessao``) and renewal popup (``#casca_renovasession``)
        fragments come from the top-level HTML so controller checks keep
        working. Admission rows are never re-read from top-level
        ``page.content()`` (the iframe table does not exist there).

        Args:
            snapshot: Normalized admission snapshot captured from the iframe.
            raw_html: Top-level page HTML (counter/popup fragments only).

        Returns:
            HTML string with synthetic counter + popup + snapshot container.
        """
        counter_div = _extract_block(raw_html, _TEMPO_SESSAO_RE)
        popup_div = _extract_block(raw_html, _RENEWAL_POPUP_RE)
        json_payload = json.dumps(snapshot, ensure_ascii=False)

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
