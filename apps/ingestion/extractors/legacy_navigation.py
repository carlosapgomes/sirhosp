"""Legacy UI action-based navigation for the persistent real handle (PSW-S12).

Provides focused Playwright-style navigation helpers for the real legacy
Java/JSP/PrimeFaces system. These functions perform action-based UI navigation
modeled after ``automation/source_system/medical_evolution/path2.py``, which
is the known-working automation for this legacy system.

The helpers never shell out to ``path2.py``, never launch a new browser, and
never invoke ``sync_playwright()``. They operate on an already-open Playwright
``Page`` object provided by the persistent session handle.

Design (per PSW-S12 scope):
- Port only the minimal action navigation needed for admissions snapshot
  capture: search screen, prontuário fill, Pesquisa Avançada, Internações,
  frame_pol, table rows.
- Do not copy all of ``path2.py`` — only the admissions-related actions.
- Keep Playwright-specific code behind the real handle/bridge boundary.
- Use the same selectors as ``path2.py`` for behavioral consistency.
"""

from __future__ import annotations

import importlib.util
import logging
import math
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from apps.ingestion.extractors.errors import (
    ExtractionTimeoutError,
    is_playwright_timeout_error,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical selectors (consistent with path2.py)
# ---------------------------------------------------------------------------

SEL_PRONTUARIO_INPUT = "#prontuarioInput"
"""Patient record (prontuário) text input."""

SEL_POL_MENU = "#polMenu"
"""POL menu button (fallback when search screen is not visible)."""

SEL_FRAME_POL = "frame_pol"
"""Name of the iframe containing admissions/evolution content."""

SEL_INTERNACOES_TABLE = "#tabelaInternacoes\\:resultList_data"
"""PrimeFaces table ID for admission rows (with escaped colon)."""

SEL_INTERNACOES_TABLE_ROWS = "#tabelaInternacoes\\:resultList_data > tr"
"""Admission table row selector."""

SEL_INTERNACOES_TABLE_BODY = "tbody#tabelaInternacoes\\:resultList_data"

# ---------------------------------------------------------------------------
# NavigationError
# ---------------------------------------------------------------------------


class NavigationError(Exception):
    """Sanitized error raised when legacy UI navigation fails.

    Messages never include credentials, cookies, or raw page payloads. The
    command layer converts this into a user-facing failure before any run is
    claimed.
    """


class NavigationTimeoutError(NavigationError, ExtractionTimeoutError):
    """Sanitized timeout raised when legacy UI navigation exceeds its budget.

    PSW-S17 R2/R3: persistent navigation and wait timeouts (deadline
    expiration) must reach the shared ``("timeout", True)`` classification.
    This subclass is both a :class:`NavigationError` (so existing
    ``except NavigationError:`` clauses still catch and propagate it
    unchanged) and an :class:`ExtractionTimeoutError` (so
    :func:`apps.ingestion.run_lifecycle.classify_failure_reason` recognizes
    it as a timeout even after a sanitizing wrapper).

    Messages stay constant and sanitized (see ``DEADLINE_EXPIRED_MESSAGE``).
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_patient_record(value: str) -> str:
    """Normalize patient record to digits only.

    Strips non-digit characters from the input (matching path2.py's
    ``normalize_patient_record``).

    Args:
        value: Raw patient record string (e.g. ``"123/45 A"``).

    Returns:
        Digits-only string (e.g. ``"12345"``), or the original stripped
        value if it contains no digits.
    """
    digits_only = re.sub(r"\D", "", value)
    return digits_only or value.strip()


def _parse_cli_date(value: str) -> date:
    """Parse a date string in DD/MM/YYYY or YYYY-MM-DD format."""
    candidate = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    raise NavigationError(f"Invalid date format: {value!r}")


def _parse_br_date(value: str | None) -> date | None:
    """Parse a BR-format date (DD/MM/YYYY) to a ``date`` object.

    Args:
        value: Date string in DD/MM/YYYY format.

    Returns:
        ``date`` object, or ``None`` if the value is empty/invalid.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.strptime(stripped, "%d/%m/%Y").date()
    except ValueError:
        return None


def _format_iso_date(value: date | None) -> str | None:
    """Format a ``date`` object as YYYY-MM-DD string.

    Returns ``None`` for ``None`` input.
    """
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Deadline helpers (PSW-S16 final closure: real, never-zero deadline budget)
# ---------------------------------------------------------------------------
#
# Playwright treats ``timeout=0`` as *disabled* (unbounded), so an expired
# deadline must RAISE rather than be passed as zero. These helpers distinguish:
#   - ``None``: no shared deadline (legacy callers use their own fixed waits);
#   - active deadline: return a strictly-positive remaining/bounded timeout;
#   - expired deadline: raise a constant sanitized ``NavigationError``.

DEADLINE_EXPIRED_MESSAGE = (
    "The demographics action deadline expired before the next step."
)
"""Constant sanitized message raised when a shared deadline is exhausted.

Contains no patient record, selector payload, HTML, URL, cookie, credential,
or raw underlying error text.
"""


def _deadline_s(timeout_ms: int | None) -> float | None:
    """Return a monotonic deadline (seconds) for ``timeout_ms``, or None."""
    if timeout_ms is None:
        return None
    return time.monotonic() + max(0, timeout_ms) / 1000


def _remaining_ms_strict(deadline_s: float) -> int:
    """Strictly-positive remaining ms for a non-None deadline; raise on expiry.

    Uses ``ceil`` so a small positive remainder is never collapsed to zero
    (Playwright treats ``timeout=0`` as *disabled*). An exhausted deadline
    raises ``NavigationTimeoutError(DEADLINE_EXPIRED_MESSAGE)``.

    PSW-S17 R2/R3: the typed timeout (a ``NavigationError`` AND an
    ``ExtractionTimeoutError``) lets existing ``except NavigationError:``
    clauses keep propagating it unchanged while the shared classifier
    recognizes it as ``("timeout", True)``.
    """
    remaining = deadline_s - time.monotonic()
    if remaining <= 0:
        raise NavigationTimeoutError(DEADLINE_EXPIRED_MESSAGE)
    return max(1, math.ceil(remaining * 1000))


def _remaining_ms(deadline_s: float | None) -> int | None:
    """Return strictly-positive milliseconds remaining, or ``None``.

    ``None`` means no shared deadline (caller uses fixed defaults). An active
    deadline returns at least ``1`` ms; an expired deadline raises via
    :func:`_remaining_ms_strict`.
    """
    if deadline_s is None:
        return None
    return _remaining_ms_strict(deadline_s)


def _bound_ms(deadline_s: float | None, default_ms: int) -> int:
    """Return a strictly-positive Playwright timeout for a bounded operation.

    ``None`` deadline -> ``default_ms`` (legacy fixed wait). Active deadline ->
    the smaller of ``default_ms`` and the strictly-positive remaining budget.
    Expired deadline -> raise ``NavigationError`` (never return ``0``).
    """
    if deadline_s is None:
        return default_ms
    return min(default_ms, _remaining_ms_strict(deadline_s))


def _timeout_kwargs(deadline_s: float | None, default_ms: int) -> dict[str, int]:
    """Return ``{"timeout": ms}`` for a bounded click/fill, or ``{}`` to omit.

    When there is no shared deadline, ``{}`` lets Playwright apply its own
    default (backward compatible for non-demographics callers). When a
    deadline is active, returns the bounded remaining timeout; an expired
    deadline raises ``NavigationError`` via ``_bound_ms``.
    """
    if deadline_s is None:
        return {}
    return {"timeout": _bound_ms(deadline_s, default_ms)}


_DEFAULT_ACTION_TIMEOUT_MS = 30000
"""Playwright's default action timeout, used as the cap for bounded click/fill."""

# PSW-S17 R3 (second corrective closure): constant sanitized message for any
# required-action Playwright timeout. Contains no patient record, admission
# key, URL, selector, date value, cookie, credential, or raw exception text.
_REQUIRED_ACTION_TIMEOUT_MESSAGE = (
    "A required legacy UI action timed out."
)


def _raise_required_action_error(
    exc: BaseException,
    *,
    fallback_message: str,
) -> None:
    """Re-raise a required-action exception as a typed/sanitized NavigationError.

    PSW-S17 R3 (second corrective closure): a Playwright timeout from a
    required action (``wait_for``/``click``/``fill``/``goto``) MUST become a
    typed :class:`NavigationTimeoutError`. Other failures become a constant
    sanitized :class:`NavigationError`. The raw chain is suppressed
    (``from None``) so no underlying Playwright text can leak if the
    exception is later logged with traceback.

    Args:
        exc: The caught underlying exception.
        fallback_message: Constant sanitized message for non-timeout failures.

    Raises:
        NavigationTimeoutError: when ``exc`` is a Playwright timeout.
        NavigationError: for any other non-timeout failure.
    """
    if is_playwright_timeout_error(exc):
        raise NavigationTimeoutError(
            _REQUIRED_ACTION_TIMEOUT_MESSAGE
        ) from None
    raise NavigationError(fallback_message) from None


# ---------------------------------------------------------------------------
# Navigation actions
# ---------------------------------------------------------------------------


def ensure_search_screen(page: Any, *, timeout_ms: int | None = None) -> None:
    """Ensure the patient search screen is visible.

    Tries multiple strategies modeled after ``path2.py``'s
    ``ensure_search_screen``:
    1. Check if ``#prontuarioInput`` is already visible.
    2. Try opening ``#polMenu`` (POL menu).
    3. Try the dashboard shortcut.

    All strategies operate on the injected ``page`` (an already-open Playwright
    Page, never a new browser/context).

    Args:
        page: A Playwright ``Page`` object (mocked in tests).

    Raises:
        NavigationError: If the search screen cannot be made visible after
            all fallback attempts.
    """
    deadline_s = _deadline_s(timeout_ms)
    # Strategy 1: Check if already visible
    prontuario = page.locator(SEL_PRONTUARIO_INPUT)
    try:
        prontuario.wait_for(state="visible", timeout=_bound_ms(deadline_s, 5000))
        logger.debug("Search screen already visible via #prontuarioInput.")
        return
    except NavigationError:
        # Deadline expiry must propagate, not trigger a fallback strategy.
        raise
    except Exception:
        logger.debug("#prontuarioInput not immediately visible, trying fallbacks...")

    # Strategy 2: Try the POL menu button (most reliable fallback).
    # PSW-S17 post-ce2c494 (D11): non-blocking presence probe for optional
    # discovery; once present, interaction failures go through the typed
    # required-action mapping and are NOT swallowed as fallback misses.
    pol_menu = page.locator(SEL_POL_MENU)
    if _locator_count(pol_menu) > 0:
        try:
            try:
                # Production-proven legacy path: the PrimeFaces menu can be
                # visible while Playwright's actionability click times out.
                pol_menu.first.evaluate("(element) => element.click()")
            except Exception:
                pol_menu.first.click(
                    **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
                )
            page.wait_for_timeout(_bound_ms(deadline_s, 1800))
            try:
                prontuario.wait_for(state="visible", timeout=_bound_ms(deadline_s, 6000))
                logger.debug("Search screen opened via #polMenu.")
                return
            except NavigationError:
                raise
            except Exception as exc:
                _raise_required_action_error(
                    exc,
                    fallback_message=(
                        "Could not reveal the patient search screen "
                        "after clicking the POL menu."
                    ),
                )
        except NavigationError:
            raise
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message="Could not click the POL menu button.",
            )

    # Strategy 3: Try the dashboard shortcut.
    # PSW-S17 post-ce2c494 (D11): same non-blocking probe + typed mapping.
    dashboard = page.get_by_role(
        "button",
        name=re.compile(r"Clique aqui para acessar o", re.IGNORECASE),
    )
    if _locator_count(dashboard) > 0:
        try:
            dashboard.first.click(
                **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
            )
            page.wait_for_timeout(_bound_ms(deadline_s, 1800))
            try:
                prontuario.wait_for(state="visible", timeout=_bound_ms(deadline_s, 6000))
                logger.debug("Search screen opened via dashboard shortcut.")
                return
            except NavigationError:
                raise
            except Exception as exc:
                _raise_required_action_error(
                    exc,
                    fallback_message=(
                        "Could not reveal the patient search screen "
                        "after clicking the dashboard shortcut."
                    ),
                )
        except NavigationError:
            raise
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message="Could not click the dashboard shortcut.",
            )

    raise NavigationError(
        "Could not make the patient search screen visible. "
        "The legacy page may be in an unexpected state."
    )


def search_patient(
    page: Any,
    *,
    patient_record: str,
    timeout_ms: int | None = None,
) -> None:
    """Fill the patient record field and click the advanced search link.

    Steps modeled after ``path2.py``'s search sequence:
    1. Fill ``#prontuarioInput`` with the normalized patient record.
    2. Click the ``Pesquisa Avançada`` (Advanced Search) link.

    When ``timeout_ms`` is provided, every wait is bounded by the remaining
    budget (PSW-S16 R5); ``None`` preserves the original fixed waits.

    Args:
        page: A Playwright ``Page`` object.
        patient_record: Raw patient record (prontuário) string. Is normalized
            to digits-only internally.
        timeout_ms: Optional overall budget in milliseconds for this step.

    Raises:
        NavigationError: If the input field or search link cannot be found.
    """
    normalized = normalize_patient_record(patient_record)
    deadline_s = _deadline_s(timeout_ms)

    # Step 1: Fill prontuário field
    prontuario = page.locator(SEL_PRONTUARIO_INPUT)
    try:
        prontuario.wait_for(state="visible", timeout=_bound_ms(deadline_s, 15000))
        prontuario.click(**_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS))
        prontuario.fill(
            normalized,
            **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS),
        )
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not fill the patient record field (#prontuarioInput)."
            ),
        )

    # Step 2: Click advanced search link
    try:
        pesquisa_link = page.get_by_role("link", name="Pesquisa Avançada")
        pesquisa_link.wait_for(state="visible", timeout=_bound_ms(deadline_s, 15000))
        pesquisa_link.click(**_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS))
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not find or click the 'Pesquisa Avançada' link."
            ),
        )

    page.wait_for_timeout(_bound_ms(deadline_s, 1200))


def click_internacoes(page: Any, *, timeout_ms: int | None = None) -> None:
    """Click the 'Internações' text element to open the admissions list.

    Modeled after ``path2.py``: waits for the exact text ``"Internações"``
    and clicks it.

    Args:
        page: A Playwright ``Page`` object.

    Raises:
        NavigationTimeoutError: If the wait/click times out (Playwright timeout).
        NavigationError: If the Internações element is not found for other reasons.
    """
    deadline_s = _deadline_s(timeout_ms)
    try:
        internacoes = page.get_by_text("Internações", exact=True)
        internacoes.wait_for(state="visible", timeout=_bound_ms(deadline_s, 15000))
        internacoes.click(**_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS))
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not find or click the 'Internações' element."
            ),
        )

    page.wait_for_timeout(_bound_ms(deadline_s, 500))


def wait_for_admissions_table(
    page: Any,
    timeout_ms: int = 30000,
) -> Any:
    """Wait for the ``frame_pol`` iframe to contain admission table rows.

    Polls for the ``frame_pol`` frame and checks that
    ``#tabelaInternacoes:resultList_data > tr`` rows are attached.

    Modeled after ``path2.py``'s ``wait_internacoes_table()``.

    Args:
        page: A Playwright ``Page`` object.
        timeout_ms: Maximum time to wait in milliseconds.

    Returns:
        The Playwright ``Frame`` object for ``frame_pol`` with table rows
        available.

    Raises:
        NavigationError: If the frame or table is not available within the
            timeout.
    """
    started_at = time.monotonic()

    while True:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        remaining_ms = timeout_ms - elapsed_ms
        if remaining_ms <= 0:
            break

        frame = page.frame(name=SEL_FRAME_POL)
        if frame is not None:
            rows_locator = frame.locator(SEL_INTERNACOES_TABLE_ROWS)
            step_timeout = min(500, max(1, remaining_ms))
            try:
                rows_locator.first.wait_for(
                    state="attached", timeout=step_timeout
                )
                return frame
            except Exception:
                pass

        page.wait_for_timeout(min(500, max(1, remaining_ms)))

    raise NavigationTimeoutError(
        _REQUIRED_ACTION_TIMEOUT_MESSAGE
    )


def read_admissions_rows(page: Any) -> list[dict[str, Any]]:
    """Read admission rows from the table inside ``frame_pol``.

    Evaluates JavaScript on the ``frame_pol`` iframe to extract row data:
    ``data-ri``, ``data-rk``, cell text content, and details-link presence.

    Modeled after ``path2.py``'s ``read_internacoes_rows()``.

    Args:
        page: A Playwright ``Page`` object.

    Returns:
        List of admission dicts with keys:
        - ``admissionKey``: The data-rk attribute (or fallback ``row-{index}``).
        - ``admissionStart``: ``date`` object parsed from the first cell.
        - ``admissionEnd``: Optional ``date`` object from the second cell.
        - ``ward``: String from the third cell.
        - ``bed``: String from the fourth cell.

        Only rows with a details link (``a[title="Detalhes da Internação"]``)
        are included.
    """
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        return []

    rows = frame.eval_on_selector_all(
        SEL_INTERNACOES_TABLE_ROWS,
        """
        (rows) => rows.map((tr) => ({
            dataRi: tr.getAttribute('data-ri'),
            dataRk: tr.getAttribute('data-rk'),
            cells: Array.from(tr.querySelectorAll('td')).map(
                (td) => (td.textContent || '').trim()
            ),
            hasDetailsLink: !!tr.querySelector(
                'a[title="Detalhes da Internação"]'
            ),
        }))
        """,
    )

    if not rows:
        return []

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("hasDetailsLink"):
            continue

        cells = row.get("cells") or []
        if len(cells) < 2:
            continue

        admission_start = _parse_br_date(cells[0])
        if admission_start is None:
            continue

        admission_end = _parse_br_date(cells[1])
        row_index_raw = row.get("dataRi")
        try:
            row_index = int(row_index_raw) if row_index_raw else len(parsed)
        except (TypeError, ValueError):
            row_index = len(parsed)

        data_rk = row.get("dataRk") or f"row-{row_index}"
        ward = cells[2] if len(cells) > 2 else ""
        bed = cells[3] if len(cells) > 3 else ""

        parsed.append({
            "admissionKey": data_rk,
            "admissionStart": admission_start,
            "admissionEnd": admission_end,
            "ward": ward,
            "bed": bed,
        })

    return parsed


# ---------------------------------------------------------------------------
# Evolution navigation helpers (PSW-S13)
# ---------------------------------------------------------------------------

SEL_EVOLUCAO_BUTTON = 'button:has-text("Evolução")'
"""Button that opens the evolution date-picker modal."""

SEL_DATE_START = '[id$="dataInicio:dataInicio:inputId_input"]'
"""Date start input in the evolution modal (DD/MM/YYYY)."""

SEL_DATE_END = '[id$="dataFim:dataFim:inputId_input"]'
"""Date end input in the evolution modal (DD/MM/YYYY)."""

SEL_ORDER_SELECT = (
    '#ordenacaoCrescente\\:ordenacaoCrescente\\:inputId_input'
)
"""Order select inside the evolution modal."""

SEL_VISUALIZAR_BUTTON = '#bt_UltimosQuinzedias\\:button'
"""Button to generate/visualize the evolution report."""

SEL_PRINT_LINKS = '#printLinks'
"""Form with print links in the report page (indicates report is ready)."""

SEL_PDF_OBJECT = 'object[type="application/pdf"]'
"""PDF object element on the report page."""

SEL_DETAILS_LINK = 'a[title="Detalhes da Internação"]'
"""Details link inside admission table rows."""

SEL_NO_EVOLUTIONS_DIALOG = '#msgDialog'
"""Dialog shown when there are no evolutions for a window."""

SEL_DIALOG_CLOSE = '.ui-dialog-titlebar-close'
"""Titlebar close button shared by PrimeFaces dialogs/modals.

PSW-S21-C1: used only by the empty-chunk recovery to dismiss the visible
no-evolutions warning and the evolution modal before restoring the detail page.
"""

SEL_EVOLUTION_MODAL = '#modalEvolucao'
"""PrimeFaces evolution date-picker modal overlay.

PSW-S21-C1: closed by the empty-chunk recovery when it remains visible after
the no-evolutions warning.
"""


# ---------------------------------------------------------------------------
# Canonical chunking (PSW-S21 R1/R4)
# ---------------------------------------------------------------------------
#
# The chunking algorithm lives in exactly one place: the dependency-free
# canonical module ``automation/source_system/medical_evolution/chunking.py``.
# The previous app-local duplicate (``_build_chunks_for_interval`` with its
# ``_CHUNK_DAYS``/``_CHUNK_OVERLAP`` constants) was removed because it was
# unused and drifted from the canonical contract. The wrapper below loads the
# canonical module lazily by file path (no ``sys.path`` mutation, no copied
# algorithm) so both the automation connector and the persistent worker share
# identical chunk boundaries.

_CANONICAL_CHUNKING_FILE = (
    Path(__file__).resolve().parents[3]
    / "automation"
    / "source_system"
    / "medical_evolution"
    / "chunking.py"
)
"""Path to the canonical dependency-free chunking module (single source)."""

_canonical_chunking_cache: Any = None


def _canonical_chunking() -> Any:
    """Lazily load and cache the canonical chunking module by file path.

    Loading lazily (on first chunking need) keeps ``legacy_navigation`` import
    cheap and avoids failing app-wide import if the canonical file is absent
    in a slimmed deployment; the error surfaces at extraction time instead.
    """
    global _canonical_chunking_cache
    if _canonical_chunking_cache is None:
        spec = importlib.util.spec_from_file_location(
            "_canonical_chunking", _CANONICAL_CHUNKING_FILE
        )
        if spec is None or spec.loader is None:
            raise NavigationError(
                "Could not load the canonical chunking module."
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _canonical_chunking_cache = module
    return _canonical_chunking_cache


def build_chunks_for_interval(
    start: date,
    end: date,
) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into at-most-15-day chunks (canonical overlap).

    PSW-S21 R1: delegates to the canonical dependency-free module so the
    chunking algorithm is never copied into the app. Each chunk spans at most
    15 inclusive calendar days with a canonical one-day overlap and
    deterministic, always-progressing bounds (the bounded report windows).

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        List of ``(chunk_start, chunk_end)`` tuples covering the full range.
    """
    return _canonical_chunking().build_chunks_for_interval(start, end)


def choose_overlapping_admissions(
    admissions: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Filter admissions to those overlapping the requested date window.

    An admission overlaps the window when its start <= window end AND
    its (actual or assumed) end >= window start. Open-ended admissions
    (``admissionEnd`` is ``None``) are treated as ending today.

    Modeled after ``path2.choose_target_admissions()`` but operates on
    the canonical snapshot format (ISO strings for dates).

    Args:
        admissions: List of admission dicts in canonical snapshot format.
        start_date: Window start in ``YYYY-MM-DD``.
        end_date: Window end in ``YYYY-MM-DD``.

    Returns:
        Filtered list of overlapping admissions.

    Raises:
        NavigationError: If no admissions overlap the requested window.
    """
    req_start = _parse_cli_date(start_date)
    req_end = _parse_cli_date(end_date)

    selected: list[dict[str, Any]] = []
    for adm in admissions:
        adm_start_str = adm.get("admissionStart") or adm.get("admission_start", "")
        adm_end_str = adm.get("admissionEnd") or adm.get("admission_end")

        if not adm_start_str:
            continue

        adm_start = _parse_cli_date(adm_start_str)
        if adm_end_str:
            adm_end = _parse_cli_date(adm_end_str)
        else:
            adm_end = date.today()

        # Overlap check
        if adm_start <= req_end and adm_end >= req_start:
            selected.append(adm)

    if not selected:
        raise NavigationError(
            "Nenhuma internação com interseção foi encontrada "
            "para o intervalo solicitado."
        )

    return selected


def open_internacao_detail(
    page: Any,
    *,
    admission_key: str,
    timeout_ms: int | None = None,
) -> None:
    """Open the admission detail page by clicking the details link.

    Modeled after ``path2.open_internacao_detail()``. Locates the table
    row with the given ``admission_key`` (``data-rk`` attribute) inside
    ``frame_pol`` and clicks the ``Detalhes da Internação`` link.

    PSW-S17 R6 (second corrective closure): error messages and logs no
    longer include ``admission_key`` or any source identifier.

    Args:
        page: A Playwright ``Page`` object.
        admission_key: The ``data-rk`` value identifying the admission.
            Used only to locate the row; never surfaced in errors/logs.

    Raises:
        NavigationTimeoutError: on Playwright timeout.
        NavigationError: if the row or details link cannot be found.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        raise NavigationError(
            "The admissions iframe was not available when opening "
            "admission details."
        )

    escaped_key = admission_key.replace('"', '\\"')
    row_selector = (
        f'{SEL_INTERNACOES_TABLE_BODY} > '
        f'tr[data-rk="{escaped_key}"]'
    )
    row_locator = frame.locator(row_selector)
    try:
        row_locator.first.wait_for(state="visible", timeout=_bound_ms(deadline_s, 10000))
    except Exception:
        # Fallback: try first row with details link (sanitized log; no key).
        logger.debug(
            "Admission row not found by key; trying first visible "
            "row (sanitized)."
        )
        row_locator = frame.locator(
            f'{SEL_INTERNACOES_TABLE_ROWS}:has({SEL_DETAILS_LINK})'
        )
        try:
            row_locator.first.wait_for(state="visible", timeout=_bound_ms(deadline_s, 5000))
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message=(
                    "Could not locate the admission row in the table."
                ),
            )

    details_row_selector = (
        f'{row_selector} {SEL_DETAILS_LINK}'
    )
    details_link = frame.locator(details_row_selector)
    try:
        details_link.first.wait_for(state="visible", timeout=_bound_ms(deadline_s, 10000))
        details_link.first.click(**_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS))
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not click the admission details link."
            ),
        )

    page.wait_for_timeout(_bound_ms(deadline_s, 1500))


# ---------------------------------------------------------------------------
# HTEFS-S1: resilient, bounded activation of the Evolução action (D2)
# ---------------------------------------------------------------------------
#
# Production evidence: the Evolução button was VISIBLE while Playwright's
# actionability click retried for ~30 s (``_DEFAULT_ACTION_TIMEOUT_MS``). The
# same-element DOM click proven by ``path2.click_with_fallback`` opened the
# flow. The primary Playwright click stays FIRST but gets a short named
# budget; only a primary TIMEOUT with the modal still closed runs the
# controlled DOM fallback on the SAME validated locator. Both routes converge
# on one postcondition: BOTH required date inputs visible.

_EVOLUCAO_CLICK_BUDGET_MS = 5000
"""Short primary-click budget for the Evolução action (HTEFS-S1 R1).

The normal click attempt may not consume ``_DEFAULT_ACTION_TIMEOUT_MS``
(30 s): it is capped at this named constant and always re-bounded by the
remaining shared deadline.
"""

_EVOLUCAO_MODAL_WAIT_MS = 10000
"""Default budget for the shared two-input modal postcondition wait (R4)."""

_EVOLUCAO_DOM_CLICK_JS = "(element) => element.click()"
"""Same-element DOM click expression for the controlled fallback (R2).

Runs on the already-validated button locator — never a global selector, a
new page, or JavaScript that searches for another element.
"""

_EVOLUCAO_ACTION_MESSAGE = "Falha ao acionar o botão Evolução."
"""Constant sanitized message for Evolução click/fallback failures (R5)."""

_EVOLUCAO_MODAL_MISSING_MESSAGE = (
    "Os campos obrigatórios do modal de evolução não ficaram visíveis."
)
"""Constant sanitized message when the two-input postcondition fails (R4/R5)."""

_EVOLUCAO_IFRAME_MISSING_MESSAGE = (
    "O iframe de internações não estava disponível ao acionar "
    "o botão Evolução."
)
"""Constant sanitized message when ``frame_pol`` is absent (R5/R6).

Contains no frame name/selector, URL, date, identity, or raw exception.
"""


def _evolution_dates_visible(frame: Any) -> bool:
    """Return True iff BOTH required evolution date inputs are visible.

    HTEFS-S1 R3/R4: a single non-blocking probe shared by the already-open
    modal check and the fallback decision. One visible input is NOT enough.
    Any locator failure counts as not visible.
    """
    for selector in (SEL_DATE_START, SEL_DATE_END):
        try:
            if not frame.locator(selector).first.is_visible():
                return False
        except Exception:
            return False
    return True


def _wait_evolution_dates_visible(
    frame: Any,
    deadline_s: float | None,
) -> None:
    """Wait for BOTH required evolution date inputs within the deadline.

    HTEFS-S1 R4/R5: the single postcondition of :func:`click_evolucao`. Each
    wait is re-bounded by the remaining shared deadline (never zero); a
    Playwright timeout maps to ``NavigationTimeoutError`` and any other
    failure to a constant sanitized ``NavigationError``.
    """
    for selector in (SEL_DATE_START, SEL_DATE_END):
        try:
            frame.locator(selector).first.wait_for(
                state="visible",
                timeout=_bound_ms(deadline_s, _EVOLUCAO_MODAL_WAIT_MS),
            )
        except NavigationError:
            raise
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message=_EVOLUCAO_MODAL_MISSING_MESSAGE,
            )


def click_evolucao(page: Any, *, timeout_ms: int | None = None) -> None:
    """Activate the 'Evolução' action inside ``frame_pol``.

    HTEFS-S1 (D2): resilient and bounded activation. The production page
    showed the button VISIBLE while Playwright's actionability click retried
    for ~30 s; a controlled same-element DOM click opened the flow. Flow:

    1. Wait for the button to be visible (bounded by the shared deadline).
    2. Primary strategy: ``locator.first.click()`` with the short named
       budget ``_EVOLUCAO_CLICK_BUDGET_MS`` (at most 5 s), always re-bounded
       by the remaining deadline.
    3. If the primary click fails AND both required modal date inputs are
       already visible, the modal is considered open — no second click.
    4. Only a primary-click TIMEOUT with the modal still closed triggers the
       controlled fallback ``evaluate("(element) => element.click()")`` on
       the SAME validated button.
    5. Both routes converge on one postcondition: BOTH ``SEL_DATE_START``
       and ``SEL_DATE_END`` visible within the remaining deadline
       (:func:`_wait_evolution_dates_visible`).

    Never uses ``force=True``, a global selector, ``timeout=0``, a new page,
    or JavaScript that locates another element. Timeout failures raise a
    typed sanitized ``NavigationTimeoutError``; non-timeout failures raise a
    constant sanitized ``NavigationError``.

    Args:
        page: A Playwright ``Page`` object.

    Raises:
        NavigationTimeoutError: on any bounded Playwright timeout or deadline
            expiry (wait, primary click, fallback, or postcondition).
        NavigationError: for non-timeout failures with a constant sanitized
            message.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        raise NavigationError(_EVOLUCAO_IFRAME_MISSING_MESSAGE)

    evo_button = frame.get_by_role("button", name="Evolução")
    try:
        evo_button.first.wait_for(
            state="visible", timeout=_bound_ms(deadline_s, 15000)
        )
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Botão Evolução não encontrado na tela de detalhes "
                "da internação."
            ),
        )

    try:
        evo_button.first.click(
            timeout=_bound_ms(deadline_s, _EVOLUCAO_CLICK_BUDGET_MS)
        )
    except NavigationError:
        raise
    except Exception as exc:
        if _evolution_dates_visible(frame):
            # R3: the modal is already open — the action is done.
            return
        if not is_playwright_timeout_error(exc):
            _raise_required_action_error(
                exc, fallback_message=_EVOLUCAO_ACTION_MESSAGE
            )
        # R2: controlled DOM click on the SAME validated locator.
        try:
            evo_button.first.evaluate(_EVOLUCAO_DOM_CLICK_JS)
        except NavigationError:
            raise
        except Exception as fallback_exc:
            _raise_required_action_error(
                fallback_exc, fallback_message=_EVOLUCAO_ACTION_MESSAGE
            )

    # R4: single shared postcondition — both required inputs visible.
    _wait_evolution_dates_visible(frame, deadline_s)


def fill_evolution_dates(
    page: Any,
    *,
    start_date_br: str,
    end_date_br: str,
    timeout_ms: int | None = None,
) -> bool:
    """Fill date inputs inside the evolution modal with ``DD/MM/YYYY``.

    PSW-S17 R2 (second corrective closure): optional date inputs are probed
    for presence (``count()``); when an input is present, a Playwright
    timeout from its ``wait_for``/DOM-focus/``fill`` path raises a typed
    :class:`NavigationTimeoutError` instead of being swallowed.

    PSW-S20 R4: returns ``True`` ONLY when BOTH the start and end date
    inputs were present and filled. Returning ``False`` (absent iframe or
    either required input) lets the caller fail safely instead of
    generating a report for an unbounded/default window. Modeled after
    ``path2.open_report_for_interval``, which treats the date inputs as
    required.

    Args:
        page: A Playwright ``Page`` object.
        start_date_br: Start date in ``DD/MM/YYYY`` format.
        end_date_br: End date in ``DD/MM/YYYY`` format.

    Returns:
        ``True`` if both date inputs were present and filled; ``False`` if
        the iframe or either required input was absent.

    Raises:
        NavigationTimeoutError: when a present date input times out.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        logger.warning(
            "Evolution date iframe not available (sanitized)."
        )
        return False

    filled_start = False
    # Fill start date (only if the input is present).
    start_input = frame.locator(SEL_DATE_START)
    if _locator_count(start_input) > 0:
        try:
            start_input.first.wait_for(
                state="visible", timeout=_bound_ms(deadline_s, 10000)
            )
            _remaining_ms(deadline_s)
            frame.evaluate(
                """(selector) => {
                    const element = document.querySelector(selector);
                    if (!element) throw new Error("date input unavailable");
                    element.click();
                }""",
                SEL_DATE_START,
            )
            _remaining_ms(deadline_s)
            start_input.first.fill(
                start_date_br,
                **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS),
            )
            filled_start = True
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message=(
                    "Could not fill the evolution start date input."
                ),
            )

    filled_end = False
    # Fill end date (only if the input is present).
    end_input = frame.locator(SEL_DATE_END)
    if _locator_count(end_input) > 0:
        try:
            end_input.first.wait_for(
                state="visible", timeout=_bound_ms(deadline_s, 10000)
            )
            _remaining_ms(deadline_s)
            frame.evaluate(
                """(selector) => {
                    const element = document.querySelector(selector);
                    if (!element) throw new Error("date input unavailable");
                    element.click();
                }""",
                SEL_DATE_END,
            )
            _remaining_ms(deadline_s)
            end_input.first.fill(
                end_date_br,
                **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS),
            )
            filled_end = True
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message=(
                    "Could not fill the evolution end date input."
                ),
            )

    page.wait_for_timeout(_bound_ms(deadline_s, 500))
    return filled_start and filled_end


def _locator_count(locator: Any) -> int:
    """Return the count for a locator, treating access failures as 0.

    PSW-S17 R2 (second corrective closure): a non-blocking presence probe
    for optional elements. Used to decide whether an optional UI control is
    present before attempting required actions on it.
    """
    try:
        return int(locator.count())
    except Exception:
        return 0


def select_ascending_order(page: Any, *, timeout_ms: int | None = None) -> None:
    """Select 'Crescente' in the evolution order dropdown if present.

    Modeled after ``path2.select_order_crescente()``. Uses JS evaluation
    to set the hidden PrimeFaces select value, as direct interaction with
    the visible label may not propagate the change correctly.

    PSW-S17 final closure (D2): the order select is optional. Its presence
    is probed via a non-blocking ``count()`` probe. When absent, the
    function is a documented no-op. When present, a Playwright timeout
    from its ``wait_for``/``evaluate`` raises a typed
    :class:`NavigationTimeoutError` instead of being swallowed as optional
    absence.

    Args:
        page: A Playwright ``Page`` object.

    Raises:
        NavigationTimeoutError: when the order select IS present and a
            Playwright timeout occurs during interaction.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        return

    order_select = frame.locator(SEL_ORDER_SELECT)
    # D2: non-blocking presence probe. Absent → no-op.
    if _locator_count(order_select) == 0:
        return

    # The select IS present. A Playwright timeout from here is a typed
    # timeout, not optional absence.
    try:
        order_select.first.wait_for(state="attached", timeout=_bound_ms(deadline_s, 5000))
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not attach to the ascending-order select."
            ),
        )

    # Evaluate JS to select 'Crescente' option
    try:
        frame.evaluate(
            """
            (selector) => {
                const select = document.querySelector(selector);
                if (!(select instanceof HTMLSelectElement)) return false;
                const option = Array.from(select.options).find(
                    (o) => (o.textContent || '').trim() === 'Crescente'
                );
                if (!option) return false;
                select.value = option.value;
                select.selectedIndex = Array.from(select.options).indexOf(option);
                select.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            """,
            SEL_ORDER_SELECT,
        )
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message="Ascending-order evaluation failed.",
        )

    page.wait_for_timeout(_bound_ms(deadline_s, 500))


def click_visualizar_report(page: Any, *, timeout_ms: int | None = None) -> None:
    """Generate the evolution report through its declared PrimeFaces action.

    The production modal renders a visible button whose Playwright
    actionability click can time out or emit no request. Calling the exact
    ``PrimeFaces.ab`` action declared by that button avoids coordinate-click
    ambiguity while preserving the same JSF source, form, and update target.

    Args:
        page: A Playwright ``Page`` object.

    Raises:
        NavigationTimeoutError: on Playwright timeout.
        NavigationError: If the button is not found.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        raise NavigationError(
            "The admissions iframe was not available when visualizing "
            "the evolution report."
        )

    button = frame.locator(SEL_VISUALIZAR_BUTTON)
    try:
        button.first.wait_for(
            state="visible", timeout=_bound_ms(deadline_s, 15000)
        )
        _remaining_ms(deadline_s)
        frame.evaluate(
            """() => PrimeFaces.ab({
                s: "bt_UltimosQuinzedias:button",
                f: "formModalEvolucao",
                u: "@(#formModalEvolucao)",
                ps: false
            })"""
        )
        _remaining_ms(deadline_s)
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message="Could not generate the evolution report.",
        )

    page.wait_for_timeout(_bound_ms(deadline_s, 1500))


def wait_for_report_or_no_evolutions(
    page: Any,
    timeout_ms: int = 120000,
    poll_ms: int = 500,
) -> bool:
    """Wait for either the report page or detect a no-evolutions dialog.

    Polls for the ``frame_pol`` iframe URL and content. Returns:
    - ``True`` when the report page is detected
      (URL contains ``relatorioAnaEvoInternacaoPdf.xhtml`` AND
      ``#printLinks`` is available).
    - ``False`` ONLY when an explicit no-evolutions dialog is detected.

    PSW-S17 R2/R3 correction: a polling-budget expiry is a TIMEOUT and
    raises :class:`NavigationTimeoutError`; it MUST NOT be conflated with
    the genuine no-evolutions result. Only an observed no-evolutions
    dialog may return ``False``.

    Modeled after ``path2.wait_for_report_page()`` and
    ``detect_no_evolutions_dialog_and_recover()``.

    Args:
        page: A Playwright ``Page`` object.
        timeout_ms: Maximum time to wait in milliseconds.
        poll_ms: Polling interval in milliseconds.

    Returns:
        ``True`` if the report page is ready, ``False`` if an explicit
        no-evolutions dialog is detected.

    Raises:
        NavigationTimeoutError: when the polling budget expires before
            either condition is observed.
    """
    started_at = time.monotonic()

    while True:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        if elapsed_ms >= timeout_ms:
            raise NavigationTimeoutError(
                DEADLINE_EXPIRED_MESSAGE,
            )

        frame = page.frame(name=SEL_FRAME_POL)
        if frame is None:
            page.wait_for_timeout(min(poll_ms, max(1, timeout_ms - elapsed_ms)))
            continue

        try:
            frame_url = frame.url or ""
        except Exception:
            frame_url = ""

        # Check if report page is ready
        if "relatorioAnaEvoInternacaoPdf.xhtml" in frame_url:
            try:
                has_print_links = frame.locator(SEL_PRINT_LINKS).count() > 0
            except Exception:
                has_print_links = False

            if has_print_links:
                return True

        # Check if no-evolutions dialog appeared. The visibility probe is
        # defensive (swallowed), but the recovery runs OUTSIDE the swallow so a
        # typed timeout from recovery propagates through the PSW-S17 taxonomy.
        detected_empty = False
        try:
            dialog = frame.locator(SEL_NO_EVOLUTIONS_DIALOG)
            if dialog.count() > 0:
                try:
                    detected_empty = dialog.first.is_visible()
                except Exception:
                    pass
        except Exception:
            pass

        if detected_empty:
            # PSW-S21-C1: recover the detail-page state (close the no-evolutions
            # warning + evolution modal, wait for detail readiness) within the
            # remaining budget before signalling the genuine empty result, so
            # the next chunk can re-open the evolution modal from detail state.
            _recover_no_evolutions_to_detail(
                page, budget_ms=max(1, timeout_ms - elapsed_ms)
            )
            return False

        page.wait_for_timeout(min(poll_ms, max(1, timeout_ms - elapsed_ms)))


# ---------------------------------------------------------------------------
# Between-chunk restoration (PSW-S21 R6)
# ---------------------------------------------------------------------------
#
# ``consultaDetalheInternacao.xhtml`` is the detail URL fragment shared by
# ``open_internacao_detail`` and the between-chunk restoration helper
# (matches ``path2.open_internacao_detail`` and
# ``path2.go_back_to_detail_from_report``).

_DETAIL_INTERNACAO_FRAGMENT = "consultaDetalheInternacao.xhtml"


def go_back_to_detail_from_report(
    page: Any,
    *,
    timeout_ms: int | None = None,
) -> None:
    """Return from the evolution report to the admission detail page.

    PSW-S21 R6: between consecutive chunks of the SAME admission the report
    page must be left and the detail page restored so the next chunk can
    re-open the evolution modal with a fresh bounded window. Modeled after
    ``path2.go_back_to_detail_from_report()``: click the report's ``Voltar``
    button inside ``frame_pol`` and wait until the detail page
    (``consultaDetalheInternacao.xhtml`` with an available ``Evolução``
    button) is ready again.

    Reuses the already-open persistent page (never a new browser/context).

    Args:
        page: A Playwright ``Page`` object on the report page.
        timeout_ms: Optional remaining budget from the shared cooperative
            deadline.

    Raises:
        NavigationTimeoutError: on a bounded Playwright timeout or deadline
            expiry before the detail page re-appears.
        NavigationError: If ``frame_pol`` is unavailable or the ``Voltar``
            button cannot be clicked.
    """
    deadline_s = _deadline_s(timeout_ms)
    frame = page.frame(name=SEL_FRAME_POL)
    if frame is None:
        raise NavigationError(
            "The admissions iframe was not available when returning "
            "from the evolution report."
        )

    voltar_button = frame.get_by_role("button", name="Voltar")
    try:
        voltar_button.first.wait_for(
            state="visible", timeout=_bound_ms(deadline_s, 30000)
        )
        voltar_button.first.click(
            **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
        )
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not click the report back button to restore "
                "the admission detail page."
            ),
        )

    _wait_for_detail_readiness(page, deadline_s)


def _wait_for_detail_readiness(
    page: Any,
    deadline_s: float | None,
    *,
    poll_ms: int = 500,
    default_budget_ms: int = 180000,
) -> None:
    """Poll ``frame_pol`` until the admission detail page is ready again.

    Ready means the frame URL contains ``consultaDetalheInternacao.xhtml`` AND
    the ``Evolução`` button is available. Bounded by the shared cooperative
    deadline (or a conservative default when there is none); expiry raises a
    typed ``NavigationTimeoutError``.
    """
    budget_ms = (
        _remaining_ms_strict(deadline_s)
        if deadline_s is not None
        else default_budget_ms
    )
    started_at = time.monotonic()

    while True:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        remaining_ms = budget_ms - elapsed_ms
        if remaining_ms <= 0:
            raise NavigationTimeoutError(_REQUIRED_ACTION_TIMEOUT_MESSAGE)

        frame = page.frame(name=SEL_FRAME_POL)
        if frame is not None:
            try:
                frame_url = frame.url or ""
            except Exception:
                frame_url = ""

            if _DETAIL_INTERNACAO_FRAGMENT in frame_url:
                try:
                    has_evolucao = (
                        frame.get_by_role("button", name="Evolução").count() > 0
                    )
                except Exception:
                    has_evolucao = False

                if has_evolucao:
                    return

        page.wait_for_timeout(min(poll_ms, max(1, remaining_ms)))


def _recover_no_evolutions_to_detail(page: Any, *, budget_ms: int) -> None:
    """Close the no-evolutions warning + evolution modal, then restore detail.

    PSW-S21-C1: a genuine empty chunk must leave the admission detail page
    ready for the next chunk. Modeled after the smallest recovery mechanics in
    ``path2.detect_no_evolutions_dialog_and_recover()`` and
    ``path2.close_evolution_modal_if_open()``: dismiss the visible no-evolutions
    warning dialog (frame first, page fallback) and the evolution modal via
    their titlebar close button, then wait for the existing detail-readiness
    condition before the caller returns ``False``.

    Consumes only the remaining ``budget_ms`` passed by the caller. Playwright
    timeouts and deadline expiry convert through the existing sanitized
    ``NavigationTimeoutError``/``NavigationError`` boundaries; best-effort
    close steps that fail for non-timeout reasons are skipped. No selector,
    URL, HTML, warning text, or raw exception text is ever placed in a message.

    Args:
        page: A Playwright ``Page`` object showing the no-evolutions state.
        budget_ms: Remaining milliseconds from the calling wait's budget.

    Raises:
        NavigationTimeoutError: on a bounded close/readiness timeout or
            deadline expiry.
    """
    deadline_s = time.monotonic() + max(0, budget_ms) / 1000.0
    frame = page.frame(name=SEL_FRAME_POL)
    targets = (
        (frame, SEL_NO_EVOLUTIONS_DIALOG),
        (page, SEL_NO_EVOLUTIONS_DIALOG),
        (frame, SEL_EVOLUTION_MODAL),
    )
    for owner, selector in targets:
        if owner is None:
            continue
        try:
            dialog = owner.locator(selector)
            if dialog.count() == 0:
                continue
            target = dialog.first
            if not target.is_visible():
                continue
        except NavigationError:
            raise
        except Exception:
            continue
        close_button = target.locator(SEL_DIALOG_CLOSE)
        try:
            if close_button.count() > 0:
                close_button.first.click(
                    timeout=_bound_ms(deadline_s, 3000)
                )
        except NavigationError:
            raise
        except Exception:
            pass
        try:
            target.wait_for(state="hidden", timeout=_bound_ms(deadline_s, 3000))
        except NavigationError:
            raise
        except Exception:
            pass
    _wait_for_detail_readiness(page, deadline_s)


# ---------------------------------------------------------------------------
# Snapshot building
# ---------------------------------------------------------------------------


def _build_admission_snapshot(
    admissions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build canonical admission snapshot list from parsed admission dicts.

    Converts the ``date`` objects to ISO date strings for adapter
    consumption. Matches the format produced by ``path2.py``'s
    ``_build_admission_snapshot()``.

    Args:
        admissions: List of admission dicts from :func:`read_admissions_rows`.

    Returns:
        List of admission dicts with canonical field names and ISO-formatted
        dates, ready for ``AdmissionSnapshotParser`` consumption.
    """
    snapshot: list[dict[str, Any]] = []
    for admission in admissions:
        snapshot.append({
            "admissionKey": admission.get("admissionKey", ""),
            "admissionStart": _format_iso_date(
                admission.get("admissionStart")
            ),
            "admissionEnd": _format_iso_date(
                admission.get("admissionEnd")
            ),
            "ward": admission.get("ward", ""),
            "bed": admission.get("bed", ""),
        })
    return snapshot


def _read_and_build_snapshot(
    page: Any, *, timeout_ms: int | None = None
) -> list[dict[str, Any]]:
    """Read admission rows from the page and build the canonical snapshot.

    Combined convenience: waits for the admissions table, reads rows, and
    builds the snapshot in one call.

    Args:
        page: A Playwright ``Page`` object with visible admissions table.

    Returns:
        List of canonical admission snapshot dicts.

    Raises:
        NavigationError: If the admissions table is not available.
    """
    if timeout_ms is None:
        wait_for_admissions_table(page)
    else:
        wait_for_admissions_table(page, timeout_ms=timeout_ms)
    rows = read_admissions_rows(page)
    return _build_admission_snapshot(rows)


# ---------------------------------------------------------------------------
# Demographics navigation helpers (PSW-S16)
# ---------------------------------------------------------------------------
#
# Modeled after ``automation/source_system/patient_demographics/
# extract_patient_demographics.py`` but stripped of all CLI/env/login/
# debug-artifact/browser-startup code. These helpers operate on the
# already-open persistent page/context and read demographic fields from
# the ``frame_pol`` Cadastro tab into an in-memory dict consumed by
# ``upsert_patient_demographics``.

SEL_DADOS_DO_PACIENTE = "#accordionPOL .ui-treenode-label span"
"""Tree leaf label span for 'Dados do Paciente' in the POL accordion."""

SEL_DADOS_DO_PACIENTE_FALLBACK = "#accordionPOL span"
"""Broader fallback selector for the 'Dados do Paciente' label."""

SEL_CADASTRO_TAB = "#aba_cadastro"
"""Cadastro tab panel id inside ``frame_pol``."""

_DEMOGRAPHICS_PAUSE_MS = 1500
"""Small pause after clicking 'Dados do Paciente' (matches the script)."""

# Canonical mapping of {demographic_key: CSS_selector} for every field
# consumed by ``upsert_patient_demographics`` (see ``apps/ingestion/services``
# ``field_map`` and the DDD-combined phone keys). Selectors mirror the
# working demographics script. Backslash-escaped colons match PrimeFaces
# component ids.
DEMOGRAPHIC_FIELD_SELECTORS: dict[str, str] = {
    "prontuario": r"#prontuario\:prontuario\:inputId",
    "nome": r"#nome\:nome\:inputId",
    "nome_social": r"#nomeSocial\:nomeSocial\:inputId",
    "data_nascimento": r"#idFieldDataNascimento\:dataDataNascimento_input",
    "sexo": r"#sexo\:sexo\:inputId",
    "genero": r"#genero\:genero\:inputId",
    "nome_mae": r"#nome_mae\:nome_mae\:inputId",
    "nome_pai": r"#nome_pai\:nome_pai\:inputId",
    "raca_cor": r"#cor\:cor\:inputId",
    "naturalidade": r"#naturalidade\:naturalidade\:inputId",
    "nacionalidade": r"#nacionalidade\:nacionalidade\:inputId",
    "estado_civil": r"#estadoCivil\:estadoCivil\:inputId",
    "grau_instrucao": r"#grauInstrucao\:grauInstrucao\:inputId",
    "profissao": r"#profissao\:profissao\:inputId",
    "ddd_fone_residencial": r"#ddd_fone_residencial\:ddd_fone_residencial\:inputId",
    "fone_residencial": r"#foneResidencial\:foneResidencial\:inputId",
    "ddd_fone_celular": r"#ddd_fone_celular\:ddd_fone_celular\:inputId",
    "fone_celular": r"#foneCelular\:foneCelular\:inputId",
    "ddd_fone_recado": r"#ddd_fone_recado\:ddd_fone_recado\:inputId",
    "fone_recado": r"#foneRecado\:foneRecado\:inputId",
    "cns": r"#nroCartaoSaude\:nroCartaoSaude\:inputId",
    "cpf": r"#cpf\:cpf\:inputId",
    "logradouro": r"#logradouro\:logradouro\:inputId",
    "numero": r"#numero\:numero\:inputId",
    "complemento": r"#complemento\:complemento\:inputId",
    "bairro": r"#bairro\:bairro\:inputId",
    "cep": r"#cep\:cep\:inputId",
    "cidade": r"#cidade\:cidade\:inputId",
    "uf": r"#uf\:uf\:inputId",
}
"""Canonical ``{demographic_key: CSS_selector}`` mapping.

Keys are exactly the external keys ``upsert_patient_demographics`` reads
(its ``field_map`` keys plus the three ``ddd_fone_*`` keys used to combine
# phone DDD + number). Values are the input-element selectors inside
# ``frame_pol``.
"""

# Single JS round-trip that reads every demographic input value at once.
# Missing elements yield an empty string, so a sparse page never fails the
# whole extraction (R2: missing/empty values handled safely).
_DEMOGRAPHIC_READ_JS = """
(selectorMap) => {
    const result = {};
    for (const [key, selector] of Object.entries(selectorMap)) {
        const el = document.querySelector(selector);
        let value = '';
        if (el && (el instanceof HTMLInputElement
                   || el instanceof HTMLTextAreaElement
                   || el instanceof HTMLSelectElement)) {
            value = (el.value || '').trim();
        }
        result[key] = value;
    }
    return result;
}
"""


def click_dados_do_paciente(
    page: Any,
    *,
    timeout_ms: int | None = None,
) -> None:
    """Click the 'Dados do Paciente' leaf node in the POL tree menu.

    Modeled after ``extract_patient_demographics.click_dados_do_paciente``.
    Locates the tree-node label span by text and clicks it. Operates on the
    already-open persistent page (never a new browser/context). When
    ``timeout_ms`` is provided, every wait is bounded by the remaining budget
    (PSW-S16 R5).

    Args:
        page: A Playwright ``Page`` object.
        timeout_ms: Optional overall budget in milliseconds for this step.

    Raises:
        NavigationError: If the 'Dados do Paciente' element cannot be found.
    """
    deadline_s = _deadline_s(timeout_ms)
    locator = page.locator(
        SEL_DADOS_DO_PACIENTE,
        has_text=re.compile(r"Dados do Paciente", re.IGNORECASE),
    )
    try:
        locator.first.wait_for(
            state="visible", timeout=_bound_ms(deadline_s, 10000)
        )
    except NavigationError:
        raise
    except Exception:
        # Broader fallback search in the POL accordion.
        locator = page.locator(
            SEL_DADOS_DO_PACIENTE_FALLBACK,
            has_text=re.compile(r"^Dados do Paciente$", re.IGNORECASE),
        )
        try:
            locator.first.wait_for(
                state="visible", timeout=_bound_ms(deadline_s, 5000)
            )
        except NavigationError:
            raise
        except Exception as exc:
            _raise_required_action_error(
                exc,
                fallback_message=(
                    "Could not locate 'Dados do Paciente' in the POL menu."
                ),
            )

    try:
        locator.first.click(
            **_timeout_kwargs(deadline_s, _DEFAULT_ACTION_TIMEOUT_MS)
        )
    except NavigationError:
        raise
    except Exception as exc:
        _raise_required_action_error(
            exc,
            fallback_message=(
                "Could not click 'Dados do Paciente' in the POL menu."
            ),
        )

    page.wait_for_timeout(_bound_ms(deadline_s, _DEMOGRAPHICS_PAUSE_MS))


def wait_for_demographics_frame(
    page: Any,
    *,
    timeout_ms: int | None = None,
) -> Any:
    """Wait for ``frame_pol`` Cadastro readiness and return the frame.

    Polls for the ``frame_pol`` iframe and positively verifies readiness
    (PSW-S16 R6): the Cadastro panel must be **visible** (not merely
    attached) AND the source-identity input must be readable. This matches
    the working script, which waits for visible Cadastro content before
    reading. Optional fields may still be missing/empty.

    Args:
        page: A Playwright ``Page`` object.
        timeout_ms: Optional overall budget in milliseconds for this step.
            Defaults to 15000 ms when not provided (backward compatible).

    Returns:
        The Playwright ``Frame`` object for ``frame_pol`` with the Cadastro
        tab and identity input visible.

    Raises:
        NavigationError: If readiness is not reached within the budget.
    """
    deadline_s = _deadline_s(timeout_ms if timeout_ms is not None else 15000)
    # timeout_ms is always defaulted to 15000 above, so the deadline is a
    # concrete float (never None). Narrow for the strict final-check call.
    assert deadline_s is not None
    identity_selector = DEMOGRAPHIC_FIELD_SELECTORS["prontuario"]
    while True:
        frame = page.frame(name=SEL_FRAME_POL)
        if frame is not None:
            try:
                cadastro = frame.locator(SEL_CADASTRO_TAB)
                # Recompute the budget immediately before the Cadastro wait.
                cadastro.first.wait_for(
                    state="visible",
                    timeout=_bound_ms(deadline_s, 500),
                )
                # Require the identity input to be readable before accepting.
                # Recompute the budget immediately before the identity wait;
                # never reuse the Cadastro timeout.
                identity = frame.locator(identity_selector)
                identity.first.wait_for(
                    state="visible",
                    timeout=_bound_ms(deadline_s, 500),
                )
                # Final expiry check: the identity wait may have consumed the
                # last of the budget. Never return readiness after expiry.
                _remaining_ms_strict(deadline_s)
                return frame
            except NavigationError:
                raise
            except Exception:
                pass
        # Readiness not reached. Recompute the budget immediately before the
        # polling pause; never reuse a value computed before the attempt.
        page.wait_for_timeout(_bound_ms(deadline_s, 500))


def read_demographic_fields(frame: Any) -> dict[str, str]:
    """Read every demographic field value from the Cadastro tab in memory.

    Performs a single JavaScript evaluation on the frame that queries each
    canonical selector and returns its trimmed input value. Missing or
    non-input elements yield an empty string for that field only.

    Fail-closed (PSW-S16 R2): failure of the whole ``frame.evaluate()`` call
    or a non-object result raises a sanitized ``NavigationError``. It is
    never converted into an all-empty success sentinel; that would be
    indistinguishable from a sparse page.

    Args:
        frame: The ``frame_pol`` Playwright ``Frame`` with the Cadastro tab.

    Returns:
        Dict mapping every ``DEMOGRAPHIC_FIELD_SELECTORS`` key to its
        stripped string value (empty string when an optional field is
        missing/unreadable).

    Raises:
        NavigationError: If the global field read fails or returns a
            non-object payload.
    """
    try:
        result = frame.evaluate(
            _DEMOGRAPHIC_READ_JS, DEMOGRAPHIC_FIELD_SELECTORS
        )
    except Exception as exc:
        # PSW-S17 post-ce2c494 (D13): a real Playwright timeout from
        # Frame.evaluate() becomes a typed NavigationTimeoutError; other
        # failures stay ordinary NavigationError. Raw chain suppressed.
        if is_playwright_timeout_error(exc):
            raise NavigationTimeoutError(
                _REQUIRED_ACTION_TIMEOUT_MESSAGE
            ) from None
        raise NavigationError(
            "Could not read demographic fields from the Cadastro tab."
        ) from None
    if not isinstance(result, dict):
        raise NavigationError(
            "Could not read demographic fields from the Cadastro tab."
        )
    return {
        key: (str(result.get(key, "") or "")).strip()
        for key in DEMOGRAPHIC_FIELD_SELECTORS
    }


def build_demographics(
    page: Any,
    *,
    timeout_ms: int | None = None,
) -> dict[str, str]:
    """Click 'Dados do Paciente', wait for readiness, read fields.

    Combined convenience: navigates to the demographics screen and reads
    every demographic field into an in-memory dict in one call. The dict
    uses the external keys ``upsert_patient_demographics`` consumes.

    Deadline boundary: when ``timeout_ms`` is provided, this function
    creates an outer monotonic deadline and propagates ceil-rounded
    positive remaining-millisecond bounds to the action/navigation/
    readiness helpers. Those helpers bound operations that accept timeouts,
    but the readiness helper (:func:`wait_for_demographics_frame`)
    re-bases the received integer value onto a *local* deadline rather
    than reusing one absolute deadline object across every phase;
    millisecond ceiling/rebasing can extend that local deadline by a
    fraction of a millisecond relative to the original outer deadline.

    The readiness helper checks its local deadline before returning the
    frame. ``build_demographics`` performs **no** outer-deadline check at
    the :func:`read_demographic_fields` / ``Frame.evaluate()`` call, and
    synchronous ``Frame.evaluate()`` has no per-call timeout in this path.
    The field read is therefore not guaranteed to start or finish within
    the original ``timeout_ms``.

    With ``timeout_ms=None`` there is no outer shared deadline: legacy
    helper defaults apply and readiness uses its own 15-second budget.

    Args:
        page: A Playwright ``Page`` object on the patient search screen.
        timeout_ms: Optional overall budget in milliseconds.

    Returns:
        Normalized in-memory demographics dict.
    """
    deadline_s = _deadline_s(timeout_ms)
    click_dados_do_paciente(page, timeout_ms=_remaining_ms(deadline_s))
    frame = wait_for_demographics_frame(
        page, timeout_ms=_remaining_ms(deadline_s)
    )
    return read_demographic_fields(frame)


# ---------------------------------------------------------------------------
# Source identity invariant (PSW-S16 correction R3)
# ---------------------------------------------------------------------------

DEMOGRAPHICS_IDENTITY_MESSAGE = (
    "Extracted source identity does not match the requested patient."
)
"""Constant sanitized message for identity mismatches.

Callers raise their own typed error (``ExtractionError`` at the adapter,
validation error at the command) using this constant text. No patient
record, field value, HTML, URL, cookie, or credential is ever included.
"""


def demographics_identity_matches(
    *,
    requested_patient_record: str,
    demographics: Mapping[str, Any],
) -> bool:
    """Return True iff the extracted prontuario positively identifies the
    requested patient under one shared normalization rule.

    The extracted ``demographics["prontuario"]`` must be a non-empty string
    whose normalized form equals the normalized requested record. Both sides
    use :func:`normalize_patient_record`, so formatting-only differences
    (punctuation/whitespace vs digits) are accepted. Optional demographic
    fields are irrelevant to this check.

    Args:
        requested_patient_record: The run's requested patient record.
        demographics: The in-memory extracted demographics dict.

    Returns:
        ``True`` only when the identity positively matches.
    """
    extracted = demographics.get("prontuario")
    if not isinstance(extracted, str) or not extracted.strip():
        return False
    return normalize_patient_record(
        requested_patient_record
    ) == normalize_patient_record(extracted)
