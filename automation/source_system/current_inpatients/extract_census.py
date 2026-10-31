#!/usr/bin/env python3
"""
Extrai pacientes de todos os setores do Censo diretamente do DOM.

Fluxo:
1) login
2) abrir Censo
3) listar setores
4) para cada setor: selecionar -> pesquisar -> aplicar página longa -> ler DOM
   (datas enriquecidas pelo tooltip associado à própria célula) -> paginar
5) salvar CSV consolidado e resumo agregado de completude

A exportação XLSX e o parser de planilha permanecem apenas como referência de
laboratório/regressão; o caminho operacional não os chama e não possui fallback.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from playwright.sync_api import Frame, Page, sync_playwright

# Add project and automation roots for shared helpers in standalone subprocesses.
_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_SYSTEM_DIR = _CURRENT_DIR.parent
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SOURCE_SYSTEM_DIR))

from proxy_config import get_playwright_proxy  # noqa: E402
from source_system import fechar_dialogos_iniciais  # noqa: E402

from apps.ingestion.extractors.legacy_session_bootstrap import (  # noqa: E402
    LegacyLoginCredentials,
    bootstrap_legacy_session,
)

DEFAULT_TIMEOUT_MS = 180000

CENSO_FRAME_NAME = "i_frame_censo_diário_dos_pacientes"

# Bounded number of dropdown scroll+read rounds while collecting sectors.
MAX_SETOR_PANEL_SCROLLS = 20

SUMMARY_FILENAME = "censo-extraction-summary.json"
SUMMARY_VERSION = 1

# Fixed, aggregate-safe helper diagnostics. Raw browser exception text must
# never reach producer stdout (design D7 / extraction transport privacy).
CLICK_JS_FALLBACK_FAILED_REASON = "click_js_fallback_failed"
SETOR_ITEM_CLICK_FAILED_REASON = "setor_item_click_failed"

# Fixed structural reasons for DOM acquisition. These are the only reason
# strings allowed in logs, failure summaries and stage metrics.
CENSUS_TABLE_MISSING_REASON = "census_table_missing"
REQUIRED_COLUMN_MISSING_REASON = "required_column_missing"
UNSUPPORTED_ROW_REASON = "unsupported_row_structure"
HEADERS_CHANGED_REASON = "headers_changed"
TOOLTIP_MISSING_REASON = "tooltip_not_ready"
TOOLTIP_AMBIGUOUS_REASON = "tooltip_ambiguous"
TOOLTIP_INVALID_REASON = "tooltip_invalid"
TOOLTIP_DATE_MISMATCH_REASON = "tooltip_date_mismatch"
PAGE_SIZE_UNSUPPORTED_REASON = "page_size_unsupported"
PAGE_SIZE_NOT_APPLIED_REASON = "page_size_not_applied"
PAGINATION_FIRST_PAGE_REASON = "pagination_not_first_page"
PAGINATION_STATE_REASON = "pagination_state_unknown"
PAGINATION_PROGRESS_REASON = "pagination_no_progress"
PAGINATION_LIMIT_REASON = "pagination_limit"
SOURCE_TOTAL_MISMATCH_REASON = "source_total_mismatch"
SECTOR_NOT_FOUND_REASON = "sector_not_found"
SECTOR_AMBIGUOUS_REASON = "sector_ambiguous"
SECTOR_SELECTION_MISMATCH_REASON = "sector_selection_mismatch"
SECTOR_IDENTITY_UNAVAILABLE_REASON = "sector_identity_unavailable"

# The established parser contract: exactly the eleven table fields. Sector
# metadata is added separately by the caller.
PRODUCTION_FIELDS = (
    "qrt_leito",
    "prontuario",
    "nome",
    "esp",
    "dt_int",
    "tempo",
    "idade",
    "convenio",
    "dt_mvt",
    "alta",
    "origem",
)

# Semantic header aliases (accent/punctuation/case insensitive). The first
# occurrence wins, which is the export-contract variant for repeated headers.
_FIELD_ALIASES = {
    "qrtleito": "qrt_leito",
    "prontuario": "prontuario",
    "nomesituacao": "nome",
    "nome": "nome",
    "idade": "idade",
    "dtint": "dt_int",
    "esp": "esp",
    "dtmvt": "dt_mvt",
    "alta": "alta",
    "origem": "origem",
    "tempo": "tempo",
    "convenio": "convenio",
}

NATIVE_PAGE_SIZE = 100
MAX_SECTOR_PAGES = 50
TOOLTIP_READY_TIMEOUT_MS = 10_000
TOOLTIP_POLL_INTERVAL_MS = 200
SOURCE_DATETIME_FORMAT = "%d/%m/%Y %H:%M"
SOURCE_DATETIME_PATTERN = (
    r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$"
)

DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"


class CensusExtractionError(RuntimeError):
    """Sector extraction failed with a fixed, aggregate-safe reason code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai pacientes de todos os setores diretamente do DOM."
    )
    parser.add_argument("--headless", action="store_true", help="Executa sem UI")
    parser.add_argument("--max-setores", type=int, default=0, help="Limita setores (0 = todos)")
    parser.add_argument("--pause-ms", type=int, default=250, help="Pausa curta entre ações")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretório de saída (default: <project_root>/downloads)",
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Gerar apenas CSV (não gerar JSON)",
    )
    return parser.parse_args()


def wait_visible(locator, timeout: int = 10000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator, label: str, timeout: int = 10000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        print(f"  [!] Não visível para clique: {label}")
        return False

    target = locator.first
    for force in (False, True):
        try:
            target.click(timeout=timeout, force=force)
            return True
        except Exception:
            continue

    try:
        target.evaluate("el => el.click()")
        return True
    except Exception:
        print(
            f"  [!] Clique falhou ({label}):"
            f" motivo={CLICK_JS_FALLBACK_FAILED_REASON}"
        )
        return False


def get_censo_frame(page: Page, timeout_ms: int = 60000) -> Frame:
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        frame = page.frame(name=CENSO_FRAME_NAME)
        if frame is not None:
            try:
                frame.locator("body").first.wait_for(state="attached", timeout=1500)
                return frame
            except Exception:
                pass
        page.wait_for_timeout(300)
    raise RuntimeError("Timeout aguardando iframe do Censo.")


def wait_ajax_idle(frame: Frame, page: Page, timeout_ms: int = 30000) -> bool:
    """Aguarda fila AJAX esvaziar e loading dialog sumir."""
    stable = 0
    deadline = time.time() + timeout_ms / 1000

    while time.time() < deadline:
        try:
            status = frame.evaluate(
                """
                () => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const ariaHidden = (el.getAttribute('aria-hidden') || '').toLowerCase() === 'true';
                        return !ariaHidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                    };

                    const loading = document.querySelector('#form_loading');
                    let queueEmpty = true;
                    try {
                        if (window.PrimeFaces?.ajax?.Queue) {
                            if (typeof window.PrimeFaces.ajax.Queue.isEmpty === 'function') {
                                queueEmpty = window.PrimeFaces.ajax.Queue.isEmpty();
                            } else if (Array.isArray(window.PrimeFaces.ajax.Queue.requests)) {
                                queueEmpty = window.PrimeFaces.ajax.Queue.requests.length === 0;
                            }
                        }
                    } catch (_) {}

                    return {
                        queueEmpty,
                        loadingVisible: isVisible(loading),
                    };
                }
                """
            )
        except Exception:
            status = {"queueEmpty": True, "loadingVisible": False}

        if status.get("queueEmpty") and not status.get("loadingVisible"):
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0

        page.wait_for_timeout(250)

    return False


def census_result_state(
    frame: Frame,
    *,
    arm: bool = False,
) -> dict[str, Any]:
    """Return a sanitized structural state for the current-census result."""
    return frame.evaluate(
        """
        ({ arm }) => {
            const resultSelector =
                '[id$="resultList"], [id$="resultList_data"]';
            const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const ariaHidden = (
                    element.getAttribute('aria-hidden') || ''
                ).toLowerCase() === 'true';
                return (
                    !ariaHidden
                    && style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && rect.width > 0
                    && rect.height > 0
                );
            };
            const isRelevant = (node) => {
                const element = (
                    node instanceof Element
                        ? node
                        : node.parentElement
                );
                return Boolean(
                    element
                    && (
                        element.matches(resultSelector)
                        || element.closest(resultSelector)
                        || element.querySelector(resultSelector)
                        || element.matches('#form_loading')
                        || element.closest('#form_loading')
                    )
                );
            };

            if (arm) {
                window.__sirhospCensusResultWatch?.observer?.disconnect();
                const watch = { revision: 0, observer: null };
                watch.observer = new MutationObserver((mutations) => {
                    if (
                        mutations.some((mutation) => (
                            isRelevant(mutation.target)
                            || Array.from(mutation.addedNodes).some(isRelevant)
                            || Array.from(mutation.removedNodes).some(isRelevant)
                        ))
                    ) {
                        watch.revision += 1;
                    }
                });
                watch.observer.observe(document.documentElement, {
                    subtree: true,
                    childList: true,
                    characterData: true,
                    attributes: true,
                    attributeFilter: ['class', 'style', 'aria-hidden'],
                });
                window.__sirhospCensusResultWatch = watch;
            }

            const tbody = document.querySelector(
                '[id$="resultList_data"]'
            );
            const rows = tbody ? Array.from(tbody.querySelectorAll('tr')) : [];
            const firstRowCellCount = rows[0]
                ? rows[0].querySelectorAll('td').length
                : 0;
            const normalizedText = (
                tbody?.textContent || ''
            ).replace(/\\s+/g, ' ').trim();
            let contentHash = 2166136261;
            for (let index = 0; index < normalizedText.length; index += 1) {
                contentHash ^= normalizedText.charCodeAt(index);
                contentHash = Math.imul(contentHash, 16777619);
            }
            const emptyMessage = normalizedText.includes('Nenhum registro');
            const hasPatientRows = (
                rows.length > 0
                && firstRowCellCount > 1
                && !emptyMessage
            );
            const loading = document.querySelector('#form_loading');
            let queueEmpty = true;
            try {
                const queue = window.PrimeFaces?.ajax?.Queue;
                if (typeof queue?.isEmpty === 'function') {
                    queueEmpty = queue.isEmpty();
                } else if (Array.isArray(queue?.requests)) {
                    queueEmpty = queue.requests.length === 0;
                }
            } catch (_) {}

            return {
                tbody_exists: Boolean(tbody),
                row_count: rows.length,
                first_row_cell_count: firstRowCellCount,
                content_hash: contentHash >>> 0,
                revision: (
                    window.__sirhospCensusResultWatch?.revision || 0
                ),
                queue_empty: queueEmpty,
                loading_visible: isVisible(loading),
                empty_message: emptyMessage,
                has_patient_rows: hasPatientRows,
            };
        }
        """,
        {"arm": arm},
    )


def _census_result_signature(state: dict[str, Any]) -> tuple[object, ...]:
    return (
        state.get("revision"),
        state.get("tbody_exists"),
        state.get("row_count"),
        state.get("first_row_cell_count"),
        state.get("content_hash"),
        state.get("empty_message"),
        state.get("has_patient_rows"),
    )


def wait_for_census_result_refresh(
    frame: Frame,
    page: Page,
    before: dict[str, Any],
    *,
    timeout_ms: int = 60_000,
    stable_ms: int = 750,
) -> dict[str, Any]:
    """Wait for a fresh, settled result instead of accepting stale rows."""
    deadline = time.monotonic() + timeout_ms / 1000
    before_signature = _census_result_signature(before)
    fresh_seen = False
    stable_signature: tuple[object, ...] | None = None
    stable_since = 0.0

    while time.monotonic() < deadline:
        state = census_result_state(frame)
        signature = _census_result_signature(state)
        if signature != before_signature:
            fresh_seen = True

        settled = (
            state.get("queue_empty", True)
            and not state.get("loading_visible")
            and state.get("tbody_exists")
            and (
                state.get("has_patient_rows")
                or state.get("empty_message")
            )
        )
        if fresh_seen and settled:
            now = time.monotonic()
            if signature != stable_signature:
                stable_signature = signature
                stable_since = now
            elif (now - stable_since) * 1000 >= stable_ms:
                return state
            if stable_ms == 0:
                return state
        else:
            stable_signature = None

        page.wait_for_timeout(250)

    raise RuntimeError(
        "Timeout aguardando resultado atualizado do setor."
    )


def _result_has_patients(state: dict[str, Any]) -> bool:
    if state.get("has_patient_rows"):
        return True
    if state.get("empty_message"):
        return False
    raise RuntimeError("Tabela censitária atualizada sem resultado reconhecível.")


_READ_HEADERS_JS = r"""
() => {
    const body = document.querySelector('[id$="resultList_data"]');
    if (!body) return null;
    const table = body.closest('table');
    if (!table) return null;
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    return Array.from(table.querySelectorAll('thead th'), (th) =>
        clean(th.querySelector('.ui-column-title')?.textContent || th.textContent)
    );
}
"""

_READ_PAGE_JS = r"""
(options) => {
    const body = document.querySelector('[id$="resultList_data"]');
    if (!body) return { table_found: false };
    const table = body.closest('table');
    if (!table) return { table_found: false };
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        const ariaHidden = (
            element.getAttribute('aria-hidden') || ''
        ).toLowerCase() === 'true';
        return (
            !ariaHidden
            && style.display !== 'none'
            && style.visibility !== 'hidden'
            && rect.width > 0
            && rect.height > 0
        );
    };
    const datetime = /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/;
    const headers = Array.from(
        table.querySelectorAll('thead th'),
        (th) => clean(
            th.querySelector('.ui-column-title')?.textContent || th.textContent
        )
    );
    const headerCount = headers.length;
    const widgets = Object.values(window.PrimeFaces?.widgets || {});
    const tooltipWidgets = widgets.filter((widget) =>
        window.PrimeFaces?.widget?.Tooltip
        && widget instanceof window.PrimeFaces.widget.Tooltip
    );
    const candidatesFor = (cell) => {
        if (!cell) return [];
        const nodes = [cell, ...cell.querySelectorAll('*')];
        const ids = new Set(nodes.map((node) => node.id).filter(Boolean));
        const candidates = [];
        for (const node of nodes) {
            for (const attribute of [
                'title',
                'data-original-title',
                'aria-label',
                'data-tooltip',
                'data-title',
            ]) {
                const value = clean(node.getAttribute(attribute));
                if (datetime.test(value)) candidates.push(value);
            }
        }
        for (const widget of tooltipWidgets) {
            const target = widget.cfg?.target;
            const targetId = typeof target === 'string'
                ? target.replace(/^#/, '').replace(/\\/g, '')
                : '';
            const targetNode = widget.target?.[0];
            if (!ids.has(targetId) && !nodes.includes(targetNode)) continue;
            for (const element of [
                document.getElementById(widget.cfg?.id),
                widget.jq?.[0],
            ]) {
                const value = clean(element?.textContent);
                if (datetime.test(value)) candidates.push(value);
            }
        }
        return [...new Set(candidates)];
    };
    const textOf = (cell) => {
        const clone = cell.cloneNode(true);
        clone
            .querySelectorAll('.ui-tooltip, script, style')
            .forEach((node) => node.remove());
        return clean(clone.textContent);
    };
    const rows = [];
    let unsupportedRows = 0;
    let emptyMessage = false;
    for (const row of body.querySelectorAll(':scope > tr')) {
        const cells = Array.from(row.querySelectorAll(':scope > td'));
        if (cells.length === 1 && cells[0].colSpan > 1) {
            if (clean(cells[0].textContent).includes('Nenhum registro')) {
                emptyMessage = true;
            } else {
                unsupportedRows += 1;
            }
            continue;
        }
        if (cells.length !== headerCount) {
            unsupportedRows += 1;
            continue;
        }
        const values = {};
        for (const field of options.fields) {
            values[field] = textOf(cells[options.indices[field]]);
        }
        rows.push({
            values,
            dt_int_candidates: candidatesFor(cells[options.indices.dt_int]),
            dt_mvt_candidates: candidatesFor(cells[options.indices.dt_mvt]),
        });
    }
    const root = body.closest('.ui-datatable') || table.parentElement;
    const dataTable = widgets.find((widget) => widget.tbody?.[0] === body);
    const paginator = dataTable?.getPaginator?.();
    const config = paginator?.cfg || dataTable?.cfg?.paginator || {};
    const next = root.querySelector('.ui-paginator-next');
    const active = root.querySelector('.ui-paginator-page.ui-state-active');
    const sizeSelect = root.querySelector('.ui-paginator-rpp-options');
    return {
        table_found: true,
        headers,
        rows,
        unsupported_rows: unsupportedRows,
        empty_message: emptyMessage,
        page_index: /^\d+$/.test(clean(active?.textContent))
            ? Number(clean(active.textContent)) - 1
            : null,
        selected_page_size: Number(sizeSelect?.value) || null,
        page_size_options: Array.from(
            root.querySelectorAll('.ui-paginator-rpp-options option'),
            (option) => Number(option.value)
        ).filter((value) => Number.isInteger(value) && value > 0),
        expected_rows: Number.isFinite(config.rowCount)
            ? config.rowCount
            : null,
        next_present: Boolean(next),
        next_enabled: Boolean(
            next
            && !next.classList.contains('ui-state-disabled')
            && next.getAttribute('aria-disabled') !== 'true'
        ),
    };
}
"""

_PAGE_STATE_JS = r"""
() => {
    const body = document.querySelector('[id$="resultList_data"]');
    if (!body) return { table_found: false };
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    const root = body.closest('.ui-datatable');
    if (!root) return { table_found: false };
    const widgets = Object.values(window.PrimeFaces?.widgets || {});
    const dataTable = widgets.find((widget) => widget.tbody?.[0] === body);
    const paginator = dataTable?.getPaginator?.();
    const config = paginator?.cfg || dataTable?.cfg?.paginator || {};
    const next = root.querySelector('.ui-paginator-next');
    const active = root.querySelector('.ui-paginator-page.ui-state-active');
    const sizeSelect = root.querySelector('.ui-paginator-rpp-options');
    return {
        table_found: true,
        page_index: /^\d+$/.test(clean(active?.textContent))
            ? Number(clean(active.textContent)) - 1
            : null,
        selected_page_size: Number(sizeSelect?.value) || null,
        page_size_options: Array.from(
            root.querySelectorAll('.ui-paginator-rpp-options option'),
            (option) => Number(option.value)
        ).filter((value) => Number.isInteger(value) && value > 0),
        expected_rows: Number.isFinite(config.rowCount)
            ? config.rowCount
            : null,
        next_present: Boolean(next),
        next_enabled: Boolean(
            next
            && !next.classList.contains('ui-state-disabled')
            && next.getAttribute('aria-disabled') !== 'true'
        ),
    };
}
"""

_SET_PAGE_SIZE_JS = r"""
(size) => {
    const body = document.querySelector('[id$="resultList_data"]');
    const root = body?.closest('.ui-datatable');
    const select = root?.querySelector('.ui-paginator-rpp-options');
    if (!select) return false;
    select.value = String(size);
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
}
"""

_CLICK_NEXT_PAGE_JS = r"""
() => {
    const body = document.querySelector('[id$="resultList_data"]');
    const root = body?.closest('.ui-datatable');
    const next = root?.querySelector(
        '.ui-paginator-next:not(.ui-state-disabled)'
    );
    if (!next) return false;
    next.click();
    return true;
}
"""

_READ_SETOR_SUGGESTIONS_JS = r"""
() => {
    const panel = document.querySelector(
        '[id="unidadeFuncional:unidadeFuncional:suggestion_panel"]'
    );
    if (!panel) return [];
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
            style.display !== 'none'
            && style.visibility !== 'hidden'
            && rect.width > 0
            && rect.height > 0
        );
    };
    const nodes = Array.from(
        panel.querySelectorAll('a, li, div[role="cell"], td')
    );
    nodes.forEach((node) =>
        node.removeAttribute('data-sirhosp-suggestion')
    );
    const seen = new Set();
    const result = [];
    for (const node of nodes) {
        const text = clean(node.textContent);
        if (!text || !isVisible(node) || seen.has(text)) continue;
        seen.add(text);
        const index = String(result.length);
        node.setAttribute('data-sirhosp-suggestion', index);
        result.push({ text, index });
    }
    return result;
}
"""


def _normalize_text(value: Any) -> str:
    """Collapse HTML whitespace like the established spreadsheet parser."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _identity_key(value: str | None) -> str:
    """Accent/case/whitespace insensitive key for native sector identity."""
    text = unicodedata.normalize("NFKD", value or "").casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.split())


def parse_setor_identity(label: str | None) -> dict[str, str] | None:
    """Split a native sector label into ``code - description`` identity."""
    text = normalize_setor_label(label)
    if " - " not in text:
        return None
    code, description = text.split(" - ", 1)
    code = code.strip()
    description = description.strip()
    if not code or not description:
        return None
    return {
        "code": code,
        "description": description,
        "code_key": _identity_key(code).replace(" ", ""),
        "description_key": _identity_key(description),
    }


def _confirm_selected_setor(
    requested: str, info: dict[str, str]
) -> None:
    """Reject an autocomplete result that is not the requested native sector.

    The identity combines the code actually selected in the input with the
    native description label. A call made with a description-only query (used
    by diagnostic probes) must match the selected description uniquely.
    """
    selected_code = normalize_setor_label(info.get("codigo"))
    selected_name = normalize_setor_label(info.get("nome"))
    if not selected_name:
        raise CensusExtractionError(SECTOR_IDENTITY_UNAVAILABLE_REASON)

    selected_description_key = _identity_key(selected_name)
    requested_identity = parse_setor_identity(requested)

    if requested_identity is None:
        requested_key = _identity_key(normalize_setor_label(requested))
        if not requested_key or requested_key not in selected_description_key:
            raise CensusExtractionError(SECTOR_SELECTION_MISMATCH_REASON)
        return

    if _identity_key(selected_code).replace(" ", "") != (
        requested_identity["code_key"]
    ):
        raise CensusExtractionError(SECTOR_SELECTION_MISMATCH_REASON)
    if selected_description_key != requested_identity["description_key"]:
        raise CensusExtractionError(SECTOR_SELECTION_MISMATCH_REASON)


def _compact_header(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").casefold()
    return "".join(
        char for char in text if not unicodedata.combining(char)
    ).replace(" ", "").replace("/", "").replace(".", "").replace("-", "")


def map_census_headers(headers: Iterable[str]) -> dict[str, int]:
    """Map semantic census fields dynamically; first occurrence wins.

    Repeated ``Alta``/``Origem`` headers reproduce the source variants. The
    first occurrence is the export-contract field, even when it is hidden.
    Visibility is never used to choose between variants.
    """
    mapping: dict[str, int] = {}
    for index, header in enumerate(headers):
        field = _FIELD_ALIASES.get(_compact_header(header))
        if field is None or field in mapping:
            continue
        mapping[field] = index
    if any(field not in mapping for field in PRODUCTION_FIELDS):
        raise CensusExtractionError(REQUIRED_COLUMN_MISSING_REASON)
    return mapping


def read_census_headers(frame: Frame) -> list[str]:
    headers = frame.evaluate(_READ_HEADERS_JS)
    if not headers:
        raise CensusExtractionError(CENSUS_TABLE_MISSING_REASON)
    return [str(header) for header in headers]


def _parse_source_datetime(value: str) -> datetime | None:
    if not value or not re.fullmatch(SOURCE_DATETIME_PATTERN, value):
        return None
    try:
        return datetime.strptime(value, SOURCE_DATETIME_FORMAT)
    except ValueError:
        return None


def _display_date_matches(displayed: str, candidate: str) -> bool:
    if displayed == candidate:
        return True
    if len(displayed) == 5 and displayed[2] == "/":
        return candidate.startswith(displayed + "/")
    if len(displayed) == 10:
        return candidate.startswith(displayed + " ")
    return False


def enrich_source_timestamp(
    displayed: str, candidates: Iterable[str]
) -> str:
    """Return the unique full timestamp associated with one display cell.

    A genuinely empty display remains empty. A displayed date with no ready
    associated timestamp signals :data:`TOOLTIP_MISSING_REASON` so the caller
    can poll within its bounded interval. Multiple distinct values, invalid
    calendar values and date disagreements reject the sector.
    """
    display = _normalize_text(displayed)
    if not display:
        return ""

    distinct = sorted(
        {
            _normalize_text(candidate)
            for candidate in candidates
            if _normalize_text(candidate)
        }
    )
    if len(distinct) > 1:
        raise CensusExtractionError(TOOLTIP_AMBIGUOUS_REASON)
    if not distinct:
        raise CensusExtractionError(TOOLTIP_MISSING_REASON)

    value = distinct[0]
    if _parse_source_datetime(value) is None:
        raise CensusExtractionError(TOOLTIP_INVALID_REASON)
    if not _display_date_matches(display, value):
        raise CensusExtractionError(TOOLTIP_DATE_MISMATCH_REASON)
    return value


def _normalize_prontuario(value: Any) -> str:
    text = _normalize_text(value)
    return text.replace(".", "").replace("/", "").strip()


def _normalize_idade(value: Any) -> str:
    text = _normalize_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _normalize_tempo(value: Any) -> int | None:
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _normalize_alta(value: Any) -> str:
    text = _normalize_text(value)
    if text in {"0", "0.0"}:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _is_eligible_dom_row(prontuario: str, nome: str) -> bool:
    """Apply the established parser eligibility: omit only both-empty rows."""
    return bool(prontuario or nome)


def _build_dom_patient(
    values: dict[str, str],
    *,
    setor_codigo: str,
    setor_nome: str,
) -> dict[str, Any]:
    return {
        "setor_codigo": setor_codigo,
        "setor": setor_nome,
        "qrt_leito": _normalize_text(values.get("qrt_leito")),
        "prontuario": _normalize_prontuario(values.get("prontuario")),
        "nome": _normalize_text(values.get("nome")),
        "esp": _normalize_text(values.get("esp")),
        "dt_int": values.get("dt_int", ""),
        "tempo": _normalize_tempo(values.get("tempo")),
        "idade": _normalize_idade(values.get("idade")),
        "convenio": _normalize_text(values.get("convenio")),
        "dt_mvt": values.get("dt_mvt", ""),
        "alta": _normalize_alta(values.get("alta")),
        "origem": _normalize_text(values.get("origem")),
    }


def read_census_page(
    frame: Frame, mapping: dict[str, int]
) -> dict[str, Any]:
    payload = frame.evaluate(
        _READ_PAGE_JS,
        {"fields": list(PRODUCTION_FIELDS), "indices": mapping},
    )
    if not payload.get("table_found"):
        raise CensusExtractionError(CENSUS_TABLE_MISSING_REASON)
    return payload


def _read_page_with_tooltip_readiness(
    frame: Frame, page: Page, mapping: dict[str, int]
) -> dict[str, Any]:
    deadline = time.monotonic() + TOOLTIP_READY_TIMEOUT_MS / 1000
    while True:
        payload = read_census_page(frame, mapping)
        if payload.get("unsupported_rows"):
            raise CensusExtractionError(UNSUPPORTED_ROW_REASON)
        try:
            for row in payload["rows"]:
                values = row["values"]
                values["dt_int"] = enrich_source_timestamp(
                    values.get("dt_int", ""),
                    row.get("dt_int_candidates", []),
                )
                values["dt_mvt"] = enrich_source_timestamp(
                    values.get("dt_mvt", ""),
                    row.get("dt_mvt_candidates", []),
                )
        except CensusExtractionError as exc:
            if (
                exc.reason != TOOLTIP_MISSING_REASON
                or time.monotonic() >= deadline
            ):
                raise
            page.wait_for_timeout(TOOLTIP_POLL_INTERVAL_MS)
            continue
        return payload


def census_page_state(frame: Frame) -> dict[str, Any]:
    state = frame.evaluate(_PAGE_STATE_JS)
    if not state.get("table_found"):
        raise CensusExtractionError(CENSUS_TABLE_MISSING_REASON)
    return state


def apply_native_page_size(frame: Frame, page: Page) -> dict[str, int]:
    """Apply and verify the native long page before reading rows."""
    state = census_page_state(frame)
    options = sorted(set(state.get("page_size_options") or []))
    supported = [size for size in options if size >= NATIVE_PAGE_SIZE]
    if not supported:
        raise CensusExtractionError(PAGE_SIZE_UNSUPPORTED_REASON)
    chosen = (
        NATIVE_PAGE_SIZE
        if NATIVE_PAGE_SIZE in supported
        else min(supported)
    )
    if state.get("selected_page_size") != chosen:
        previous = census_result_state(frame, arm=True)
        if not frame.evaluate(_SET_PAGE_SIZE_JS, chosen):
            raise CensusExtractionError(PAGE_SIZE_UNSUPPORTED_REASON)
        wait_for_census_result_refresh(frame, page, previous)

    verified = census_page_state(frame)
    if verified.get("selected_page_size") != chosen:
        raise CensusExtractionError(PAGE_SIZE_NOT_APPLIED_REASON)
    if verified.get("page_index") not in (None, 0):
        raise CensusExtractionError(PAGINATION_FIRST_PAGE_REASON)
    return {"requested": NATIVE_PAGE_SIZE, "applied": chosen}


def read_sector_rows(
    frame: Frame,
    page: Page,
    *,
    setor_codigo: str,
    setor_nome: str,
) -> dict[str, Any]:
    """Read every eligible row of the current sector until explicit terminal.

    The page size is applied and verified *after* the search refresh, because
    the source can restore its default. Each page waits a bounded interval for
    its own date tooltips. Repeated/non-advancing pages, an unknown terminal
    state, a missing native size or an untrustworthy total reject the sector.
    """
    headers = read_census_headers(frame)
    mapping = map_census_headers(headers)
    page_size = apply_native_page_size(frame, page)

    pacients: list[dict[str, Any]] = []
    omitted = 0
    pages = 0
    expected_page = 0
    source_total: int | None = None

    while True:
        payload = _read_page_with_tooltip_readiness(frame, page, mapping)
        if payload.get("headers") != headers:
            raise CensusExtractionError(HEADERS_CHANGED_REASON)
        if payload.get("page_index") != expected_page:
            raise CensusExtractionError(PAGINATION_PROGRESS_REASON)

        pages += 1
        for row in payload["rows"]:
            values = row["values"]
            prontuario = _normalize_prontuario(values.get("prontuario"))
            nome = _normalize_text(values.get("nome"))
            if not _is_eligible_dom_row(prontuario, nome):
                omitted += 1
                continue
            pacients.append(
                _build_dom_patient(
                    values,
                    setor_codigo=setor_codigo,
                    setor_nome=setor_nome,
                )
            )

        source_total = payload.get("expected_rows")
        if not payload.get("next_present"):
            raise CensusExtractionError(PAGINATION_STATE_REASON)
        if not payload.get("next_enabled"):
            if (
                source_total is not None
                and source_total != len(pacients) + omitted
            ):
                raise CensusExtractionError(SOURCE_TOTAL_MISMATCH_REASON)
            break
        if pages >= MAX_SECTOR_PAGES:
            raise CensusExtractionError(PAGINATION_LIMIT_REASON)

        previous = census_result_state(frame, arm=True)
        if not frame.evaluate(_CLICK_NEXT_PAGE_JS):
            raise CensusExtractionError(PAGINATION_STATE_REASON)
        wait_for_census_result_refresh(frame, page, previous)
        expected_page += 1

    return {
        "pacientes": pacients,
        "rows_omitted": omitted,
        "pages": pages,
        "source_total": source_total,
        "page_size": page_size["applied"],
    }


def click_censo_icon(page: Page) -> None:
    icon = page.locator('[id="_icon_img_20323"]')
    if not safe_click(icon, "ícone do Censo", timeout=15000):
        raise RuntimeError("Não foi possível abrir o Censo.")


def _close_setor_dropdown(frame: Frame) -> None:
    """Close the sector dropdown by clicking outside of it."""
    try:
        frame.locator("body").click(position={"x": 2, "y": 2}, timeout=1000)
    except Exception:
        pass


def normalize_setor_label(label: str | None) -> str:
    """Normalize a sector label: strip and collapse internal whitespace."""
    if not isinstance(label, str):
        return ""
    return " ".join(label.split())


def dedupe_setores(labels: Iterable[str | None]) -> list[str]:
    """Normalize and deduplicate sector labels keeping first occurrence order.

    Blank labels are dropped. Order is stable so the caller processes
    sectors in the same order the source system presented them.
    """
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        normalized = normalize_setor_label(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def summarize_sector_results(
    discovered: int,
    results: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Return safe aggregate sector counters for the terminal summary.

    Counters are operational aggregates only: they never include patient
    names, prontuários, credentials or clinical text.
    """
    processed = 0
    empty = 0
    failed = 0
    for result in results:
        processed += 1
        if result.get("erro"):
            failed += 1
        elif not result.get("pacientes"):
            empty += 1
    return {
        "setores_found": int(discovered),
        "setores_processed": processed,
        "setores_empty": empty,
        "setores_with_error": failed,
    }


def format_sector_summary(counters: dict[str, int]) -> str:
    """Format the aggregate sector counters for the terminal summary."""
    return "\n".join(
        f"{label}: {counters.get(key, 0)}"
        for key, label in (
            ("setores_found", "Setores encontrados"),
            ("setores_processed", "Setores processados"),
            ("setores_empty", "Setores sem pacientes"),
            ("setores_with_error", "Setores com erro"),
        )
    )


def build_extraction_summary(
    *,
    discovered: int,
    selected: int,
    results: Iterable[dict[str, Any]],
    rows_omitted: int,
    scope_limited: bool,
    pages_processed: int = 0,
    discovery_complete: bool = True,
) -> dict[str, int | bool]:
    """Build the version-1 aggregate handoff summary.

    Only structural counters are returned. ``pages_processed`` describes
    navigation actually performed by the DOM acquisition for every non-empty
    sector. An empty requested sector is a valid terminal result and counts as
    processed; a sector error is a terminal failure. ``rows_read`` is the sum
    of emitted and omitted rows, so an omitted row is never silently lost.
    """
    entries = list(results)
    processed = len(entries)
    failed = sum(1 for entry in entries if entry.get("erro"))
    empty = sum(
        1
        for entry in entries
        if not entry.get("erro") and not entry.get("pacientes")
    )
    emitted = sum(
        len(entry.get("pacientes") or [])
        for entry in entries
        if not entry.get("erro")
    )
    complete = (
        discovery_complete and processed == selected and failed == 0
    )
    return {
        "summary_version": SUMMARY_VERSION,
        "sectors_discovered": int(discovered),
        "sectors_selected": int(selected),
        "sectors_processed": processed,
        "sectors_empty": empty,
        "sectors_failed": failed,
        "rows_read": emitted + int(rows_omitted),
        "rows_omitted": int(rows_omitted),
        "rows_emitted": emitted,
        "pages_processed": int(pages_processed),
        "scope_limited": bool(scope_limited),
        "scope_complete": bool(complete),
    }



def _read_setores_from_dom(frame: Frame) -> list[str]:
    """Read sector labels currently present in the dropdown DOM."""
    setores = frame.evaluate(
        """
        () => {
            const panel = document.querySelector('[id="unidadeFuncional:unidadeFuncional:suggestion_panel"]');
            const roots = panel ? [panel] : [document];
            const found = [];
            const seen = new Set();

            for (const root of roots) {
                const nodes = root.querySelectorAll('[role="cell"], td, li');
                for (const n of nodes) {
                    const t = (n.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t || t.length < 6) continue;
                    if (!t.includes(' - ')) continue;
                    if (seen.has(t)) continue;
                    seen.add(t);
                    found.push(t);
                }
            }
            return found;
        }
        """
    )
    return [s for s in setores if isinstance(s, str)]


def _scroll_setor_panel(frame: Frame, page: Page) -> bool:
    """Scroll the suggestion panel one bounded step; True when at the bottom.

    PrimeFaces suggestion panels can render rows lazily as the user
    scrolls. Each call advances the scrollable container by a fixed step
    so repeated reads collect the full list without a broad sleep.
    """
    at_bottom = frame.evaluate(
        """
        () => {
            const panel = document.querySelector(
                '[id="unidadeFuncional:unidadeFuncional:suggestion_panel"]');
            if (!panel) return true;
            const candidates = [panel, ...panel.querySelectorAll('*')];
            let target = null;
            for (const el of candidates) {
                const style = window.getComputedStyle(el);
                const overflowY = style.overflowY;
                const scrollable = (
                    el.scrollHeight > el.clientHeight + 1
                    && (overflowY === 'auto' || overflowY === 'scroll')
                );
                if (scrollable) {
                    target = el;
                    break;
                }
            }
            if (!target) return true;
            const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
            if (remaining <= 1) return true;
            target.scrollTop += Math.min(800, remaining);
            return false;
        }
        """
    )
    if at_bottom:
        return True
    page.wait_for_timeout(150)
    return False


def extract_setores(
    frame: Frame,
    page: Page,
    status: dict[str, bool] | None = None,
) -> list[str]:
    """Read the native sector dropdown with bounded lazy-loading scrolls.

    ``status["complete"]`` becomes true only when the scroll container reached
    its explicit bottom. Hitting the bounded scroll limit or two stalled reads
    leaves it false so the caller can fail closed instead of treating a partial
    discovery as the full census scope.
    """
    if status is not None:
        status["complete"] = False
    print("[i] Extraindo setores...")
    btn = frame.locator('[id="unidadeFuncional:unidadeFuncional:suggestion_button"]')
    if not safe_click(btn, "abrir dropdown de setores"):
        raise RuntimeError("Falha ao abrir dropdown de setores.")

    wait_ajax_idle(frame, page, timeout_ms=12000)
    page.wait_for_timeout(500)

    setores = dedupe_setores(_read_setores_from_dom(frame))
    if not setores:
        _close_setor_dropdown(frame)
        return []

    # Some panels render rows lazily on scroll; collect the full list by
    # scrolling in bounded steps and merging every read.
    stale_reads = 0
    complete = False
    for _ in range(MAX_SETOR_PANEL_SCROLLS):
        if _scroll_setor_panel(frame, page):
            complete = True
            break
        more = dedupe_setores(_read_setores_from_dom(frame))
        before = len(setores)
        for label in more:
            if label not in setores:
                setores.append(label)
        if len(setores) == before:
            stale_reads += 1
            if stale_reads >= 2:
                break
        else:
            stale_reads = 0

    _close_setor_dropdown(frame)
    if status is not None:
        status["complete"] = complete
    return setores


def clear_setor(frame: Frame, page: Page) -> None:
    clear_btn = frame.locator('[id="unidadeFuncional:unidadeFuncional:sgClear"]')
    if clear_btn.count() > 0 and wait_visible(clear_btn, timeout=2000):
        safe_click(clear_btn, "limpar setor", timeout=4000)
        wait_ajax_idle(frame, page, timeout_ms=6000)


def select_setor(frame: Frame, page: Page, setor: str) -> bool:
    """Select the native sector by code + normalized description.

    The autocomplete is queried with the full native label and, if the source
    needs it, with the description alone. Among the returned suggestions only
    the exact native identity is accepted; an absent or ambiguous match fails
    instead of clicking the first unrelated item.
    """
    requested_identity = parse_setor_identity(setor)
    requested_key = _identity_key(normalize_setor_label(setor))

    clear_setor(frame, page)

    # Localiza o input do autocomplete e garante que está visível
    input_el = frame.locator(
        '#unidadeFuncional\\:unidadeFuncional\\:suggestion_input'
    )
    if not wait_visible(input_el, timeout=8000):
        print(f"  [!] Input de autocomplete não visível para '{setor}'")
        return False

    # clear_setor pode falhar silenciosamente (botão sgClear não visível
    # ou AJAX pendente), deixando o input disabled com o valor do setor
    # anterior. Nesse caso, força a habilitação e limpeza via JS.
    if not input_el.is_enabled(timeout=3000):
        print("  [!] Input disabled — forçando habilitação via JS")
        frame.evaluate(
            """
            () => {
                const el = document.getElementById(
                    'unidadeFuncional:unidadeFuncional:suggestion_input'
                );
                if (el) {
                    el.removeAttribute('disabled');
                    el.classList.remove('ui-state-disabled');
                    el.value = '';
                }
            }
            """
        )
        page.wait_for_timeout(500)

    panel = frame.locator(
        '#unidadeFuncional\\:unidadeFuncional\\:suggestion_panel'
    )
    queries: list[str] = []
    if normalize_setor_label(setor):
        queries.append(setor)
    if (
        requested_identity is not None
        and requested_identity["description_key"] != requested_key
    ):
        queries.append(requested_identity["description"])

    for query in queries:
        input_el.click()
        input_el.fill("")
        input_el.press_sequentially(query, delay=50)
        if not wait_visible(panel, timeout=12000):
            continue
        page.wait_for_timeout(500)

        suggestions = frame.evaluate(_READ_SETOR_SUGGESTIONS_JS) or []
        matches: list[int] = []
        for suggestion in suggestions:
            text = suggestion.get("text", "")
            identity = parse_setor_identity(text)
            if identity is None:
                continue
            if requested_identity is not None:
                if identity["code_key"] != requested_identity["code_key"]:
                    continue
                if (
                    identity["description_key"]
                    != requested_identity["description_key"]
                ):
                    continue
            elif requested_key not in identity["description_key"]:
                # Description-only queries come from read-only diagnostic
                # probes; ambiguity is still rejected below.
                continue
            matches.append(int(suggestion["index"]))

        if len(matches) > 1:
            print(
                "  [!] Seleção de setor ambígua:"
                f" motivo={SECTOR_AMBIGUOUS_REASON}"
            )
            return False
        if not matches:
            continue

        item = panel.locator(
            f'[data-sirhosp-suggestion="{matches[0]}"]'
        ).first
        try:
            item.click(timeout=5000)
        except Exception:
            # Último recurso: JS click
            try:
                item.evaluate("el => el.click()")
            except Exception:
                print(
                    "  [!] Clique no item falhou:"
                    f" motivo={SETOR_ITEM_CLICK_FAILED_REASON}"
                )
                return False

        wait_ajax_idle(frame, page, timeout_ms=15000)
        return True

    print(f"  [!] Setor não encontrado: motivo={SECTOR_NOT_FOUND_REASON}")
    return False


def click_pesquisar(frame: Frame) -> bool:
    btn = frame.locator('[id="bt_pesquisar:button"]')
    return safe_click(btn, "botão Pesquisar", timeout=12000)


def get_current_setor_info(frame: Frame) -> dict[str, str]:
    """Extract current sector code and full name from the results page."""
    return frame.evaluate(
        """
        () => {
            const input = document.querySelector('#unidadeFuncional\\\\:unidadeFuncional\\\\:suggestion_input');
            const label = document.querySelector('#unidadeFuncional\\\\:unidadeFuncional\\\\:sgDescricaoLabel');
            return {
                codigo: (input?.value || '').trim(),
                nome: (label?.textContent || '').replace(/\\s+/g, ' ').trim(),
            };
        }
        """
    )


# ── Reference-only XLSX export/parse (not used by run) ─────────────


def _click_export_button(frame: Frame, page: Page) -> None:
    """Click the 'Exportar para Arquivo' button using JS.

    Playwright's click() hangs on this PrimeFaces commandButton because
    it triggers an AJAX event that Playwright misinterprets.  Using
    element.click() via JS dispatch avoids the deadlock.

    In sectors with many patients the button is below the fold,
    so we scroll to the bottom of the page first.
    """
    # Aguarda o botão Exportar estar presente no DOM (o paginator pode
    # renderizar após o tbody em datatables muito longos como este).
    try:
        frame.locator('[title="Exportar para Arquivo"]').wait_for(
            state='attached', timeout=15000
        )
    except Exception:
        raise RuntimeError("Botão Exportar não apareceu no DOM após 15s")
    page.wait_for_timeout(300)

    # Scroll agressivo até o final da tabela (setores com 60+ pacientes
    # deixam o botão muito abaixo do fold visível).  window.scrollTo no
    # body do iframe não é suficiente porque o scroll real está no
    # wrapper .ui-datatable-tablewrapper do PrimeFaces.
    frame.evaluate(
        """
        () => {
            // Rola wrappers de datatable até o fim
            const wrappers = document.querySelectorAll(
                '.ui-datatable-tablewrapper, .ui-datatable-scrollable-body'
            );
            for (const w of wrappers) {
                w.scrollTop = w.scrollHeight;
            }
            // Rola também o body e o html
            window.scrollTo(0, document.body.scrollHeight);
            document.documentElement.scrollTop = document.documentElement.scrollHeight;
        }
        """
    )
    page.wait_for_timeout(200)

    # Tecla End como reforço (alcança o fundo mesmo em tabelas muito longas)
    frame.locator('body').press('End')
    page.wait_for_timeout(200)

    # PageDown repetido como último recurso (para datatables que
    # renderizam linhas sob demanda conforme scroll)
    for _ in range(3):
        frame.locator('body').press('PageDown')
        page.wait_for_timeout(150)

    clicked = frame.evaluate(
        """
        () => {
            const btn = document.querySelector(
                '[title="Exportar para Arquivo"]'
            );
            if (!btn) return false;
            btn.scrollIntoView({ block: 'center' });
            btn.click();
            return true;
        }
        """
    )
    if not clicked:
        raise RuntimeError("Não foi possível clicar em Exportar para Arquivo.")
    page.wait_for_timeout(300)


def _click_xls_tudo(frame: Frame, page: Page) -> None:
    """Click the 'XLS (Tudo)' menu item using JS."""
    clicked = frame.evaluate(
        """
        () => {
            const all = document.querySelectorAll('a');
            for (const a of all) {
                if (a.offsetParent === null) continue;
                const t = (a.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (t === 'xls (tudo)') {
                    a.scrollIntoView({ block: 'center' });
                    a.click();
                    return true;
                }
            }
            return false;
        }
        """
    )
    if not clicked:
        raise RuntimeError("Não foi possível clicar em XLS (Tudo).")


def export_setor_xlsx(frame: Frame, page: Page) -> Path:
    """Clica em Exportar para Arquivo → XLS (Tudo) e retorna o path do XLSX baixado.

    Usa JS clicks em vez de Playwright clicks para evitar deadlock com
    eventos AJAX do PrimeFaces. Copia o arquivo para um path estável
    antes de retornar (evita race condition com tempfile do Playwright).
    """
    import shutil

    _click_export_button(frame, page)
    page.wait_for_timeout(500)

    # Prepara o download e clica em "XLS (Tudo)"
    with page.expect_download(timeout=120000) as download_info:
        _click_xls_tudo(frame, page)

    download = download_info.value
    download_path = download.path()
    if download_path is None:
        raise RuntimeError("Download não produziu arquivo no disco.")

    # Copy to a stable path (Playwright may clean up the temp file)
    stable_path = download_path.with_suffix(".stable.xlsx")
    shutil.copy2(download_path, stable_path)

    print(f"    [i] XLSX baixado: {download.suggested_filename} ({stable_path.stat().st_size} bytes)")
    return stable_path


def parse_setor_xlsx(
    xlsx_path: Path,
    setor_codigo: str,
    setor_nome: str,
    counters: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Parseia um XLSX exportado do AGHU e retorna lista de pacientes.

    ``counters`` (optional) receives ``rows_omitted`` for rows dropped by the
    established rule where both prontuário and nome/situação are empty. The
    caller accounts emitted rows from the returned list, so read rows are
    always emitted plus omitted.

    Mapeamento de colunas do AGHU:
        Qrt/Leito → qrt_leito
        Prontuário → prontuario
        Nome/Situação → nome
        Idade → idade
        Dt Int → dt_int (DD/MM)
        Esp → esp
        Médico → medico
        Dt Mvt → dt_mvt
        Alta → alta
        Origem → origem
        Tempo → tempo (numérico)
        Convênio → convenio
        Transferência → transferencia
    """
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise RuntimeError("XLSX sem sheet ativa.")

    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h else "" for h in next(rows_iter)]

    # Build column index mapping
    col_map: dict[str, int] = {}
    col_aliases = {
        "Qrt/Leito": "qrt_leito",
        "Prontuário": "prontuario",
        "Prontuario": "prontuario",
        "Nome/Situação": "nome",
        "Nome": "nome",
        "Idade": "idade",
        "Dt Int": "dt_int",
        "Esp": "esp",
        "Médico": "medico",
        "Dt Mvt": "dt_mvt",
        "Alta": "alta",
        "Origem": "origem",
        "Tempo": "tempo",
        "Convênio": "convenio",
        "ConvÃªnio": "convenio",
        "Transferência": "transferencia",
    }

    for i, h in enumerate(headers):
        if h in col_aliases:
            col_map[col_aliases[h]] = i

    required = {"qrt_leito", "prontuario", "nome"}
    missing = required - set(col_map.keys())
    if missing:
        print(f"    [A] Colunas encontradas: {headers}")
        raise ValueError(f"Colunas obrigatórias ausentes no XLSX: {missing}")

    def _sanitize_prontuario(raw: Any) -> str:
        """Sanitize prontuário: convert number to int→str, remove separators.

        openpyxl returns numeric cells as int or float. A cell with
        19017680.0 becomes "19017680.0" via str(), which breaks the
        downstream worker that receives --patient-record '19017680.0'.
        """
        if raw is None:
            return ""
        if isinstance(raw, (int, float)):
            raw = str(int(raw))
        else:
            raw = str(raw).strip()
        # Remove any remaining dots, slashes, or non-digit separators
        return raw.replace(".", "").replace("/", "").strip()

    pacientes: list[dict[str, Any]] = []
    for row in rows_iter:
        prontuario = _sanitize_prontuario(
            row[col_map["prontuario"]] if col_map["prontuario"] < len(row) else None
        )
        nome = str(row[col_map["nome"]]).strip() if col_map["nome"] < len(row) and row[col_map["nome"]] is not None else ""

        if not prontuario and not nome:
            if counters is not None:
                counters["rows_omitted"] = (
                    counters.get("rows_omitted", 0) + 1
                )
            continue

        qrt_leito = str(row[col_map["qrt_leito"]]).strip() if col_map["qrt_leito"] < len(row) and row[col_map["qrt_leito"]] is not None else ""

        dt_int = ""
        if "dt_int" in col_map and col_map["dt_int"] < len(row) and row[col_map["dt_int"]] is not None:
            dt_int = str(row[col_map["dt_int"]]).strip()

        tempo = None
        if "tempo" in col_map and col_map["tempo"] < len(row) and row[col_map["tempo"]] is not None:
            val = row[col_map["tempo"]]
            try:
                tempo = int(float(val))
            except (ValueError, TypeError):
                pass

        esp = str(row[col_map["esp"]]).strip() if col_map["esp"] < len(row) and row[col_map["esp"]] is not None else ""

        idade = ""
        if "idade" in col_map and col_map["idade"] < len(row) and row[col_map["idade"]] is not None:
            idade = str(int(float(row[col_map["idade"]]))) if isinstance(row[col_map["idade"]], (int, float)) else str(row[col_map["idade"]]).strip()

        convenio = ""
        if "convenio" in col_map and col_map["convenio"] < len(row) and row[col_map["convenio"]] is not None:
            convenio = str(row[col_map["convenio"]]).strip()

        dt_mvt = ""
        if "dt_mvt" in col_map and col_map["dt_mvt"] < len(row) and row[col_map["dt_mvt"]] is not None:
            dt_mvt = str(row[col_map["dt_mvt"]]).strip()

        alta = ""
        if "alta" in col_map and col_map["alta"] < len(row) and row[col_map["alta"]] is not None:
            alta_raw = row[col_map["alta"]]
            # Numeric 0 / 0.0 means "no discharge" — treat as empty
            if isinstance(alta_raw, (int, float)):
                alta = "" if float(alta_raw) == 0.0 else str(int(alta_raw))
            else:
                alta = str(alta_raw).strip()

        origem = ""
        if "origem" in col_map and col_map["origem"] < len(row) and row[col_map["origem"]] is not None:
            origem = str(row[col_map["origem"]]).strip()

        pacientes.append({
            "setor_codigo": setor_codigo,
            "setor": setor_nome,
            "qrt_leito": qrt_leito,
            "prontuario": prontuario,
            "nome": nome,
            "esp": esp,
            "dt_int": dt_int,
            "tempo": tempo,
            "idade": idade,
            "convenio": convenio,
            "dt_mvt": dt_mvt,
            "alta": alta,
            "origem": origem,
        })

    wb.close()
    return pacientes


# ── Output helpers ──────────────────────────────────────────────────


def save_extraction_summary(
    summary: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    """Atomically write the aggregate summary next to the temporary CSV."""
    target_dir = DOWNLOADS_DIR if output_dir is None else output_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    summary_path = target_dir / SUMMARY_FILENAME
    tmp_path = target_dir / f".{SUMMARY_FILENAME}.tmp"
    try:
        tmp_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, summary_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return summary_path


def save_results(
    results: list[dict],
    csv_only: bool = False,
    summary: dict[str, Any] | None = None,
) -> tuple[Path | None, Path, Path | None]:
    """Publish the canonical success CSV and its aggregate summary atomically.

    The CSV is written to a temporary sibling and only receives its canonical
    deterministic ``censo-*.csv`` name after the complete artifact set exists.
    Failure paths never call this function and therefore never publish a
    canonical success CSV.
    """
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    json_path = None
    csv_path = DOWNLOADS_DIR / f"censo-todos-pacientes-{ts}.csv"
    csv_tmp = DOWNLOADS_DIR / f".{csv_path.name}.tmp"
    json_tmp = None
    summary_path = None

    try:
        with csv_tmp.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "setor_codigo", "setor", "qrt_leito", "prontuario", "nome",
                "esp", "dt_int", "tempo", "idade", "convenio", "dt_mvt",
                "alta", "origem",
            ]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for entry in results:
                setor = entry.get("setor", "")
                for p in entry.get("pacientes", []):
                    row = {
                        "setor_codigo": entry.get("setor_codigo", ""),
                        "setor": setor,
                        "qrt_leito": p.get("qrt_leito", ""),
                        "prontuario": p.get("prontuario", ""),
                        "nome": p.get("nome", ""),
                        "esp": p.get("esp", ""),
                        "dt_int": p.get("dt_int", ""),
                        "tempo": p.get("tempo", ""),
                        "idade": p.get("idade", ""),
                        "convenio": p.get("convenio", ""),
                        "dt_mvt": p.get("dt_mvt", ""),
                        "alta": p.get("alta", ""),
                        "origem": p.get("origem", ""),
                    }
                    w.writerow(row)

        if not csv_only:
            json_path = DOWNLOADS_DIR / f"censo-todos-pacientes-{ts}.json"
            json_tmp = DOWNLOADS_DIR / f".{json_path.name}.tmp"
            json_tmp.write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if summary is not None:
            summary_path = save_extraction_summary(summary)

        os.replace(csv_tmp, csv_path)
        if json_tmp is not None and json_path is not None:
            os.replace(json_tmp, json_path)
    except Exception:
        csv_tmp.unlink(missing_ok=True)
        if json_tmp is not None:
            json_tmp.unlink(missing_ok=True)
        if summary_path is not None:
            summary_path.unlink(missing_ok=True)
        raise

    return json_path, csv_path, summary_path


# ── Main flow ───────────────────────────────────────────────────────


def run(
    source_system_url: str,
    username: str,
    password: str,
    headless: bool,
    max_setores: int,
    pause_ms: int,
    csv_only: bool = False,
) -> int:
    with sync_playwright() as pw:
        browser = context = page = None
        try:
            print("[i] Abrindo navegador...")
            _proxy = get_playwright_proxy()
            _launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": ["--ignore-certificate-errors"],
            }
            if _proxy:
                _launch_kwargs["proxy"] = _proxy
            browser = pw.chromium.launch(**_launch_kwargs)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            print(f"[i] Acessando {source_system_url}...")
            print("[i] Login...")
            bootstrap_legacy_session(
                page,
                credentials=LegacyLoginCredentials(
                    url=source_system_url,
                    username=username,
                    password=password,
                ),
                login_timeout=DEFAULT_TIMEOUT_MS // 1000,
            )

            print("[i] Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            print("[i] Abrindo Censo...")
            click_censo_icon(page)
            frame = get_censo_frame(page)
            wait_ajax_idle(frame, page, timeout_ms=15000)

            discovery_status: dict[str, bool] = {"complete": True}
            setores = extract_setores(
                frame, page, status=discovery_status
            )
            if not setores:
                raise RuntimeError("Nenhum setor encontrado.")

            discovered_count = len(setores)
            discovery_complete = bool(
                discovery_status.get("complete", True)
            )
            if not discovery_complete:
                summary = build_extraction_summary(
                    discovered=discovered_count,
                    selected=0,
                    results=[],
                    rows_omitted=0,
                    scope_limited=False,
                    discovery_complete=False,
                )
                failure_summary_path = save_extraction_summary(summary)
                print("    [ERRO] motivo=discovery_incomplete")
                print(f"Resumo: {failure_summary_path}")
                return 1

            if max_setores > 0:
                setores = setores[:max_setores]

            selected_count = len(setores)
            scope_limited = selected_count < discovered_count
            rows_omitted_total = 0
            pages_processed_total = 0

            print(f"[i] Total de setores a processar: {len(setores)}")

            results: list[dict] = []
            _retried: list[str] = []
            _failed: list[str] = []

            for i, setor in enumerate(setores, start=1):
                print(f"\n[{i}/{len(setores)}] {setor}")

                _max_retries = 2
                _last_reason = "sector_extraction_failed"

                for _attempt in range(_max_retries + 1):
                    if _attempt > 0:
                        print(
                            f"    [RETRY {_attempt}/{_max_retries}]"
                            f" motivo={_last_reason}"
                        )
                        page.wait_for_timeout(3000)

                    try:
                        if not select_setor(frame, page, setor):
                            raise CensusExtractionError(
                                "sector_selection_failed"
                            )

                        page.wait_for_timeout(pause_ms)

                        setor_codigo = ""
                        setor_nome_completo = setor

                        previous_result = census_result_state(frame, arm=True)
                        if not click_pesquisar(frame):
                            raise CensusExtractionError(
                                "sector_search_failed"
                            )

                        refreshed_result = wait_for_census_result_refresh(
                            frame,
                            page,
                            previous_result,
                            timeout_ms=60000,
                        )

                        # Extrair código e nome completo após pesquisar
                        setor_info = get_current_setor_info(frame)
                        _confirm_selected_setor(setor, setor_info)
                        setor_codigo = setor_info.get("codigo", "")
                        setor_nome_completo = (
                            setor_info.get("nome") or setor
                        )

                        tem_pacientes = _result_has_patients(
                            refreshed_result
                        )
                        if not tem_pacientes:
                            print("    setor vazio — pulando")
                            results.append({
                                "setor_codigo": setor_codigo,
                                "setor": setor_nome_completo,
                                "pacientes": [],
                            })
                            break  # sai do loop de retry

                        # Aquisição DOM (sem exportação/parse de planilha)
                        sector_rows = read_sector_rows(
                            frame,
                            page,
                            setor_codigo=setor_codigo,
                            setor_nome=setor_nome_completo,
                        )
                        pacientes = sector_rows["pacientes"]
                        omitted = int(sector_rows["rows_omitted"])
                        rows_omitted_total += omitted
                        pages_processed_total += int(sector_rows["pages"])
                        print(
                            f"    pacientes extraídos: {len(pacientes)}"
                        )

                        results.append({
                            "setor_codigo": setor_codigo,
                            "setor": setor_nome_completo,
                            "pacientes": pacientes,
                            "rows_omitted": omitted,
                        })
                        if _attempt > 0:
                            _retried.append(setor)
                        break  # sucesso — sai do loop de retry

                    except Exception as _exc:
                        _last_reason = getattr(
                            _exc, "reason", "sector_extraction_failed"
                        )
                        if _attempt < _max_retries:
                            continue
                        _failed.append(setor)
                        print(f"    [ERRO] motivo={_last_reason}")
                        results.append({
                            "setor_codigo": "",
                            "setor": setor,
                            "pacientes": [],
                            "erro": _last_reason,
                        })

            summary = build_extraction_summary(
                discovered=discovered_count,
                selected=selected_count,
                results=results,
                rows_omitted=rows_omitted_total,
                scope_limited=scope_limited,
                pages_processed=pages_processed_total,
            )
            if summary["scope_complete"]:
                json_path, csv_path, summary_path = save_results(
                    results,
                    csv_only=csv_only,
                    summary=summary,
                )
            else:
                json_path = None
                csv_path = None
                summary_path = save_extraction_summary(summary)

            total_pacientes = sum(len(r.get("pacientes", [])) for r in results)
            print("\n" + "=" * 70)
            print(
                format_sector_summary(
                    summarize_sector_results(
                        discovered=discovered_count,
                        results=results,
                    )
                )
            )
            if _retried:
                print(
                    f"Setores recuperados após retry:"
                    f" {len(_retried)}"
                )
                for s in _retried:
                    print(f"  ✓ {s}")
            if _failed:
                print(
                    f"Setores com falha definitiva:"
                    f" {len(_failed)}"
                )
                for s in _failed:
                    print(f"  ✗ {s}")
            print(f"Total pacientes:    {total_pacientes}")
            if json_path:
                print(f"JSON: {json_path}")
            if csv_path:
                print(f"CSV:  {csv_path}")
            else:
                print("CSV:  não publicado (escopo incompleto)")
            print(f"Resumo: {summary_path}")
            print("=" * 70)

            return 0 if summary["scope_complete"] else 1

        except Exception:
            print("[FATAL] census extraction failed")
            raise
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
            pw.stop()


def main() -> None:
    args = parse_args()

    if args.output_dir:
        global DOWNLOADS_DIR  # noqa: PLW0603
        DOWNLOADS_DIR = Path(args.output_dir)

    try:
        exit_code = run(
            source_system_url=os.getenv("SOURCE_SYSTEM_URL", ""),
            username=os.getenv("SOURCE_SYSTEM_USERNAME", ""),
            password=os.getenv("SOURCE_SYSTEM_PASSWORD", ""),
            headless=args.headless,
            max_setores=args.max_setores,
            pause_ms=args.pause_ms,
            csv_only=args.csv_only,
        )
    except Exception:
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
