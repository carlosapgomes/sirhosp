"""Bridge module — provides shared helpers for census extraction scripts.

Self-contained copies of aguardar_pagina_estavel and fechar_dialogos_iniciais
from automation/source_system/medical_evolution/source_system.py, extracted
to avoid pulling in pontelo-specific dependencies (config, processa_evolucoes_txt, pymupdf).
"""

from __future__ import annotations

from playwright.sync_api import Page

DEFAULT_TIMEOUT_MS = 180000
NETWORKIDLE_TIMEOUT_MS = 30000


# ---------------------------------------------------------------------------
# aguardar_pagina_estavel
# ---------------------------------------------------------------------------

def aguardar_pagina_estavel(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)

    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
    except Exception:
        print("Aviso: networkidle não foi atingido dentro do tempo limite; seguindo com a automação.")


# ---------------------------------------------------------------------------
# fechar_dialogos_iniciais + helpers
# ---------------------------------------------------------------------------

def _snapshot_visible_dialogs(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
        const dialogSelectors = [
            '.ui-dialog',
            '#central_pendencias',
            '#msgDocsDialog',
            '#msgCascaDialog',
            '[role="dialog"]'
        ];

        const unique = Array.from(
            new Set(dialogSelectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))))
        );

        const isVisible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            const ariaHidden = (element.getAttribute('aria-hidden') || '').toLowerCase() === 'true';
            const hiddenByStyle =
                style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0';

            return !ariaHidden && !hiddenByStyle && rect.width > 0 && rect.height > 0;
        };

        const parseZIndex = (element) => {
            const raw = window.getComputedStyle(element).zIndex || '0';
            const parsed = Number.parseInt(raw, 10);
            return Number.isFinite(parsed) ? parsed : 0;
        };

        const visibleDialogs = unique
            .filter(isVisible)
            .map((element) => {
                const title =
                    element.querySelector('.ui-dialog-title, .modal-title, h1, h2, h3')?.textContent || '';

                return {
                    id: element.id || null,
                    title: title.trim() || null,
                    zIndex: parseZIndex(element),
                    textSample: (element.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
                };
            })
            .sort((a, b) => b.zIndex - a.zIndex);

        const visibleOverlays = Array.from(document.querySelectorAll('.ui-widget-overlay')).filter(isVisible);

        return {
            visibleCount: visibleDialogs.length,
            overlayCount: visibleOverlays.length,
            visibleDialogs,
        };
    }"""
    )


def _close_top_dialog(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
        const dialogSelectors = [
            '.ui-dialog',
            '#central_pendencias',
            '#msgDocsDialog',
            '#msgCascaDialog',
            '[role="dialog"]'
        ];

        const unique = Array.from(
            new Set(dialogSelectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))))
        );

        const isVisible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            const ariaHidden = (element.getAttribute('aria-hidden') || '').toLowerCase() === 'true';
            const hiddenByStyle =
                style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0';

            return !ariaHidden && !hiddenByStyle && rect.width > 0 && rect.height > 0;
        };

        const parseZIndex = (element) => {
            const raw = window.getComputedStyle(element).zIndex || '0';
            const parsed = Number.parseInt(raw, 10);
            return Number.isFinite(parsed) ? parsed : 0;
        };

        const visibleDialogs = unique.filter(isVisible).sort((a, b) => parseZIndex(b) - parseZIndex(a));
        if (!visibleDialogs.length) {
            return {
                handled: false,
                reason: 'no-visible-dialogs',
                remainingVisible: 0,
            };
        }

        const top = visibleDialogs[0];
        const closeButton = top.querySelector(
            '.ui-dialog-titlebar-close, .ui-dialog-titlebar-icon, button[title*="Fechar"], button[aria-label*="Close"], .close'
        );

        let action = 'none';
        if (closeButton) {
            closeButton.click();
            action = 'close-button';
        } else {
            top.setAttribute('aria-hidden', 'true');
            top.style.display = 'none';
            top.style.visibility = 'hidden';
            top.style.opacity = '0';
            top.style.pointerEvents = 'none';
            action = 'force-hide-top';
        }

        const remainingVisible = unique.filter(isVisible).length;

        const title =
            top.querySelector('.ui-dialog-title, .modal-title, h1, h2, h3')?.textContent?.trim() || null;

        return {
            handled: true,
            action,
            topDialog: {
                id: top.id || null,
                title,
                zIndex: parseZIndex(top),
                textSample: (top.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
            },
            remainingVisible,
        };
    }"""
    )


def _force_hide_dialogs_and_overlays(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
        const selectors = [
            '#central_pendencias',
            '#msgDocsDialog',
            '#msgCascaDialog',
            '.ui-dialog[aria-hidden="false"]',
            '.ui-widget-overlay'
        ];

        let hiddenCount = 0;
        for (const selector of selectors) {
            document.querySelectorAll(selector).forEach((element) => {
                element.setAttribute('aria-hidden', 'true');
                element.style.display = 'none';
                element.style.visibility = 'hidden';
                element.style.opacity = '0';
                element.style.pointerEvents = 'none';
                hiddenCount += 1;
            });
        }

        return { hiddenCount };
    }"""
    )


def fechar_dialogos_iniciais(page: Page) -> None:
    max_ciclos = 12
    pausas_ms = 700
    ciclos_estaveis_necessarios = 2
    ciclos_estaveis = 0

    for ciclo in range(1, max_ciclos + 1):
        snapshot = _snapshot_visible_dialogs(page)
        visible_count = int(snapshot.get("visibleCount") or 0)
        overlay_count = int(snapshot.get("overlayCount") or 0)

        if visible_count == 0 and overlay_count == 0:
            ciclos_estaveis += 1
            if ciclos_estaveis >= ciclos_estaveis_necessarios:
                return

            page.wait_for_timeout(pausas_ms)
            continue

        ciclos_estaveis = 0

        close_result = _close_top_dialog(page)
        if close_result.get("handled"):
            top_dialog = close_result.get("topDialog") or {}
            dialog_id = top_dialog.get("id") or "(sem id)"
            dialog_title = top_dialog.get("title") or "(sem título)"
            action = close_result.get("action") or "desconhecida"
            remaining = close_result.get("remainingVisible")
            print(
                f"Diálogo inicial fechado [{action}]: id={dialog_id} | título={dialog_title} | restantes={remaining}"
            )
        else:
            try:
                page.locator("body").press("Escape")
                print("Aviso: não foi possível fechar via botão; aplicado Escape no body.")
            except Exception:
                pass

        page.wait_for_timeout(pausas_ms)

    force_result = _force_hide_dialogs_and_overlays(page)
    hidden_count = force_result.get("hiddenCount")
    print(
        "Aviso: limite de varredura de diálogos iniciais atingido. "
        f"Elementos ocultados via fallback final: {hidden_count}."
    )
