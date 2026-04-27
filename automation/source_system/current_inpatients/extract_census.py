#!/usr/bin/env python3
"""
Versão enxuta para extrair pacientes de todos os setores do Censo.

Fluxo essencial:
1) login
2) abrir Censo
3) listar setores
4) para cada setor: selecionar -> pesquisar -> extrair pacientes (com paginação)
5) salvar JSON/CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Frame, Locator, Page, sync_playwright

# Add parent automation/source_system so we can import shared helpers
_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_SYSTEM_DIR = _CURRENT_DIR.parent
sys.path.insert(0, str(_SOURCE_SYSTEM_DIR))

# Shared helpers from medical_evolution connector
from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais  # noqa: E402

# Configurar timeout — mesmo valor do original
DEFAULT_TIMEOUT_MS = 180000

CENSO_FRAME_NAME = "i_frame_censo_diário_dos_pacientes"

# Diretórios relativos à raiz do projeto sirhosp
# extract_census.py está em automation/source_system/current_inpatients/
# raiz do projeto = 4 níveis acima
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extrai pacientes de todos os setores (versão slim).")
    parser.add_argument("--headless", action="store_true", help="Executa sem UI")
    parser.add_argument("--max-setores", type=int, default=0, help="Limita setores (0 = todos)")
    parser.add_argument("--pause-ms", type=int, default=250, help="Pausa curta entre ações")
    parser.add_argument(
        "--table-timeout-ms",
        type=int,
        default=90000,
        help="Timeout para carga da tabela após Pesquisar (padrão: 90000)",
    )
    parser.add_argument(
        "--search-retries",
        type=int,
        default=2,
        help="Repetições do Pesquisar quando a tabela vem vazia/suspeita (padrão: 2)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretório de saída para CSV/JSON (default: <project_root>/downloads)",
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Gerar apenas CSV (não gerar JSON)",
    )
    return parser.parse_args()


def wait_visible(locator: Locator, timeout: int = 10000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator: Locator, label: str, timeout: int = 10000) -> bool:
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
    except Exception as e:
        print(f"  [!] Clique falhou ({label}): {e}")
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


def click_censo_icon(page: Page) -> None:
    icon = page.locator('[id="_icon_img_20323"]')
    if not safe_click(icon, "ícone do Censo", timeout=15000):
        raise RuntimeError("Não foi possível abrir o Censo.")


def extract_setores(frame: Frame, page: Page) -> list[str]:
    print("[i] Extraindo setores...")
    btn = frame.locator('[id="unidadeFuncional:unidadeFuncional:suggestion_button"]')
    if not safe_click(btn, "abrir dropdown de setores"):
        raise RuntimeError("Falha ao abrir dropdown de setores.")

    wait_ajax_idle(frame, page, timeout_ms=12000)
    page.wait_for_timeout(500)

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

    # Fecha dropdown clicando fora
    try:
        frame.locator("body").click(position={"x": 2, "y": 2}, timeout=1000)
    except Exception:
        pass

    return [s for s in setores if isinstance(s, str)]


def clear_setor(frame: Frame, page: Page) -> None:
    clear_btn = frame.locator('[id="unidadeFuncional:unidadeFuncional:sgClear"]')
    if clear_btn.count() > 0 and wait_visible(clear_btn, timeout=2000):
        safe_click(clear_btn, "limpar setor", timeout=4000)
        wait_ajax_idle(frame, page, timeout_ms=6000)


def select_setor(frame: Frame, page: Page, setor: str) -> bool:
    clear_setor(frame, page)

    btn = frame.locator('[id="unidadeFuncional:unidadeFuncional:suggestion_button"]')
    if not safe_click(btn, "abrir dropdown setor", timeout=10000):
        return False

    wait_ajax_idle(frame, page, timeout_ms=8000)
    page.wait_for_timeout(350)

    result = frame.evaluate(
        """
        (setor) => {
            const panel = document.querySelector('[id="unidadeFuncional:unidadeFuncional:suggestion_panel"]');
            if (!panel) return 'panel-not-found';

            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const nodes = Array.from(panel.querySelectorAll('[role="cell"], td, li'));

            let target = nodes.find((n) => norm(n.textContent) === setor);
            if (!target) {
                target = nodes.find((n) => norm(n.textContent).includes(setor));
            }
            if (!target) return 'not-found';

            target.scrollIntoView({ block: 'center' });
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            target.click();
            return 'ok';
        }
        """,
        setor,
    )

    if result != "ok":
        print(f"  [!] Falha seleção setor '{setor}': {result}")
        return False

    wait_ajax_idle(frame, page, timeout_ms=10000)
    return True


def click_pesquisar(frame: Frame) -> bool:
    btn = frame.locator('[id="bt_pesquisar:button"]')
    return safe_click(btn, "botão Pesquisar", timeout=12000)


def table_state(frame: Frame) -> dict[str, object]:
    try:
        return frame.evaluate(
            """
            () => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const ariaHidden = (el.getAttribute('aria-hidden') || '').toLowerCase() === 'true';
                    return !ariaHidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };

                const tbody = document.querySelector('[id="tabelaCensoDiario:resultList_data"]');
                const rows = tbody ? Array.from(tbody.querySelectorAll('tr')) : [];
                const firstRow = rows[0] || null;
                const firstProntuario = firstRow?.querySelector('span[id$="outProntuario"]')?.textContent || '';
                const firstNome = firstRow?.querySelector('span[id$="outNomeSituacao"]')?.textContent || '';
                const pag = document.querySelector('.ui-paginator-current')?.textContent || '';
                const loading = document.querySelector('#form_loading');
                const emptyRow = tbody?.querySelector('td.ui-datatable-empty-message');
                const hasPatientSpan = !!tbody?.querySelector('span[id$="outProntuario"], span[id$="outNomeSituacao"]');
                const tbodyText = (tbody?.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const emptyByText = rows.length <= 1 && !hasPatientSpan && (
                    tbodyText.includes('nenhum registro') ||
                    tbodyText.includes('não há registro') ||
                    tbodyText.includes('nao ha registro') ||
                    tbodyText.includes('nenhum paciente')
                );

                return {
                    tbodyExists: !!tbody,
                    rowCount: rows.length,
                    paginator: pag.replace(/\\s+/g, ' ').trim(),
                    firstProntuario: (firstProntuario || '').replace(/\\s+/g, ' ').trim(),
                    firstNome: (firstNome || '').replace(/\\s+/g, ' ').trim(),
                    loadingVisible: isVisible(loading),
                    emptyMessage: !!emptyRow || emptyByText,
                };
            }
            """
        )
    except Exception:
        return {
            "tbodyExists": False,
            "rowCount": 0,
            "paginator": "",
            "firstProntuario": "",
            "firstNome": "",
            "loadingVisible": False,
            "emptyMessage": False,
        }


def wait_table_change(frame: Frame, page: Page, before: dict[str, object], timeout_ms: int = 15000) -> None:
    deadline = time.time() + timeout_ms / 1000
    before_sig = (
        before.get("rowCount"),
        before.get("paginator"),
        before.get("firstProntuario"),
        before.get("firstNome"),
        before.get("emptyMessage"),
    )

    while time.time() < deadline:
        now = table_state(frame)
        now_sig = (
            now.get("rowCount"),
            now.get("paginator"),
            now.get("firstProntuario"),
            now.get("firstNome"),
            now.get("emptyMessage"),
        )
        if now_sig != before_sig or now.get("loadingVisible"):
            return
        page.wait_for_timeout(250)


def wait_table_ready(frame: Frame, page: Page, timeout_ms: int = 90000, min_stable_ms: int = 2500) -> int:
    """
    Espera a tabela estabilizar de forma conservadora.
    Mais lento, porém mais confiável para setores grandes.
    """
    deadline = time.time() + timeout_ms / 1000
    last_sig: tuple[object, ...] | None = None
    stable_since: float | None = None
    last_rows = 0

    while time.time() < deadline:
        state = table_state(frame)
        row_count = int(state.get("rowCount") or 0)
        last_rows = row_count

        sig = (
            state.get("rowCount"),
            state.get("paginator"),
            state.get("firstProntuario"),
            state.get("firstNome"),
            state.get("emptyMessage"),
            state.get("loadingVisible"),
        )

        if sig != last_sig:
            last_sig = sig
            stable_since = time.time()
        else:
            ready_surface = bool(state.get("tbodyExists"))
            done_loading = not bool(state.get("loadingVisible"))
            stable_for = (time.time() - stable_since) * 1000 if stable_since else 0

            if ready_surface and done_loading and stable_for >= min_stable_ms:
                return row_count

        page.wait_for_timeout(350)

    return last_rows


def extract_current_page(frame: Frame) -> list[dict[str, str]]:
    rows = frame.evaluate(
        """
        () => {
            const tbody = document.querySelector('[id="tabelaCensoDiario:resultList_data"]');
            if (!tbody) return [];

            const getSpan = (row, suffix) => {
                const span = row.querySelector('span[id$="' + suffix + '"]');
                return (span?.textContent || '').replace(/\\u00a0/g, '').replace(/\\s+/g, ' ').trim();
            };

            const out = [];
            for (const tr of tbody.querySelectorAll('tr')) {
                let qrt = getSpan(tr, 'outQrtoLto');
                if (!qrt) qrt = getSpan(tr, 'outQrtoLtoSpacer');

                const p = {
                    qrt_leito: qrt,
                    prontuario: getSpan(tr, 'outProntuario'),
                    nome: getSpan(tr, 'outNomeSituacao'),
                    esp: getSpan(tr, 'outSiglaEsp'),
                };

                if (p.prontuario || p.nome) out.push(p);
            }
            return out;
        }
        """
    )
    return rows if isinstance(rows, list) else []


def paginator_state(frame: Frame) -> dict[str, str | bool]:
    return frame.evaluate(
        """
        () => {
            const active = document.querySelector('.ui-paginator-page.ui-state-active');
            const next = document.querySelector('.ui-paginator-next');
            const current = document.querySelector('.ui-paginator-current');

            const nextDisabled = !next || (next.className || '').includes('ui-state-disabled') || next.getAttribute('aria-disabled') === 'true';
            return {
                page: (active?.textContent || '').trim(),
                current: (current?.textContent || '').replace(/\\s+/g, ' ').trim(),
                hasNext: !nextDisabled,
            };
        }
        """
    )


def click_next_page(frame: Frame, page: Page, timeout_ms: int = 15000) -> bool:
    before = paginator_state(frame)
    if not before.get("hasNext"):
        return False

    clicked = frame.evaluate(
        """
        () => {
            const next = document.querySelector('.ui-paginator-next');
            if (!next) return false;
            const disabled = (next.className || '').includes('ui-state-disabled') || next.getAttribute('aria-disabled') === 'true';
            if (disabled) return false;
            next.click();
            return true;
        }
        """
    )
    if not clicked:
        return False

    wait_ajax_idle(frame, page, timeout_ms=timeout_ms)

    # Espera troca de página ativa
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        now = paginator_state(frame)
        if now.get("page") != before.get("page"):
            return True
        page.wait_for_timeout(250)

    return True


def extract_all_pages(frame: Frame, page: Page, max_pages: int = 60) -> list[dict[str, str]]:
    all_rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for _ in range(max_pages):
        rows = extract_current_page(frame)
        for r in rows:
            key = f"{r.get('prontuario','')}|{r.get('nome','')}|{r.get('qrt_leito','')}"
            if key not in seen:
                seen.add(key)
                all_rows.append(r)

        state = paginator_state(frame)
        if state.get("current"):
            print(f"    paginador: {state.get('current')}")

        if not click_next_page(frame, page):
            break

    return all_rows


def save_results(results: list[dict], csv_only: bool = False) -> tuple[Path, Path | None]:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    json_path = None
    csv_path = DOWNLOADS_DIR / f"censo-todos-pacientes-slim-{ts}.csv"

    if not csv_only:
        json_path = DOWNLOADS_DIR / f"censo-todos-pacientes-slim-{ts}.json"
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["setor", "qrt_leito", "prontuario", "nome", "esp"])
        w.writeheader()
        for entry in results:
            setor = entry.get("setor", "")
            for p in entry.get("pacientes", []):
                w.writerow(
                    {
                        "setor": setor,
                        "qrt_leito": p.get("qrt_leito", ""),
                        "prontuario": p.get("prontuario", ""),
                        "nome": p.get("nome", ""),
                        "esp": p.get("esp", ""),
                    }
                )

    return json_path, csv_path


def save_debug(page: Page) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"censo-slim-{ts}.png"), full_page=True)
        (DEBUG_DIR / f"censo-slim-{ts}.html").write_text(page.content(), encoding="utf-8")
        frame = page.frame(name=CENSO_FRAME_NAME)
        if frame:
            (DEBUG_DIR / f"censo-slim-{ts}-iframe.html").write_text(frame.content(), encoding="utf-8")
        print(f"[i] Debug salvo em debug/censo-slim-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


def run(
    source_system_url: str,
    username: str,
    password: str,
    headless: bool,
    max_setores: int,
    pause_ms: int,
    table_timeout_ms: int,
    search_retries: int,
    csv_only: bool = False,
) -> None:
    global DOWNLOADS_DIR  # noqa: PLW0603

    with sync_playwright() as pw:
        browser = context = page = None
        try:
            print("[i] Abrindo navegador...")
            browser = pw.chromium.launch(headless=headless, args=["--ignore-certificate-errors"])
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            print(f"[i] Acessando {source_system_url}...")
            page.goto(source_system_url)

            print("[i] Login...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("[i] Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            print("[i] Abrindo Censo...")
            click_censo_icon(page)
            frame = get_censo_frame(page)
            wait_ajax_idle(frame, page, timeout_ms=15000)

            setores = extract_setores(frame, page)
            if not setores:
                raise RuntimeError("Nenhum setor encontrado.")

            if max_setores > 0:
                setores = setores[:max_setores]

            print(f"[i] Total de setores a processar: {len(setores)}")

            results: list[dict] = []

            for i, setor in enumerate(setores, start=1):
                print(f"\n[{i}/{len(setores)}] {setor}")

                try:
                    if not select_setor(frame, page, setor):
                        raise RuntimeError("não conseguiu selecionar setor")

                    page.wait_for_timeout(pause_ms)

                    linhas = 0
                    pacientes: list[dict[str, str]] = []
                    tentativas = max(0, search_retries) + 1

                    for tentativa in range(1, tentativas + 1):
                        if tentativa > 1:
                            print(f"    [i] nova tentativa de pesquisa ({tentativa}/{tentativas})...")

                        before = table_state(frame)
                        if not click_pesquisar(frame):
                            raise RuntimeError("falha no clique de pesquisar")

                        wait_table_change(frame, page, before, timeout_ms=20000)
                        wait_ajax_idle(frame, page, timeout_ms=max(45000, min(table_timeout_ms, 120000)))
                        linhas = wait_table_ready(frame, page, timeout_ms=table_timeout_ms)
                        estado = table_state(frame)

                        print(f"    linhas detectadas: {linhas}")
                        pacientes = extract_all_pages(frame, page)
                        print(f"    pacientes extraídos: {len(pacientes)}")

                        # Aceita resultado quando há pacientes ou quando a tabela sinaliza vazio explícito.
                        if pacientes or bool(estado.get("emptyMessage")):
                            break

                        if tentativa < tentativas:
                            print("    [!] resultado suspeito (0 pacientes sem mensagem explícita de vazio).")

                    results.append({"setor": setor, "pacientes": pacientes})
                except Exception as e:
                    print(f"    [ERRO] {e}")
                    results.append({"setor": setor, "pacientes": [], "erro": str(e)})

            json_path, csv_path = save_results(results, csv_only=csv_only)

            total_pacientes = sum(len(r.get("pacientes", [])) for r in results)
            setores_erro = sum(1 for r in results if r.get("erro"))
            print("\n" + "=" * 70)
            print(f"Setores processados: {len(results)}")
            print(f"Setores com erro:   {setores_erro}")
            print(f"Total pacientes:    {total_pacientes}")
            if json_path:
                print(f"JSON: {json_path}")
            print(f"CSV:  {csv_path}")
            print("=" * 70)

        except Exception as e:
            print(f"[FATAL] {e}")
            if page is not None:
                save_debug(page)
            raise
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
            pw.stop()


def main() -> None:
    args = parse_args()

    # Respect --output-dir if given
    if args.output_dir:
        global DOWNLOADS_DIR  # noqa: PLW0603
        DOWNLOADS_DIR = Path(args.output_dir)

    run(
        source_system_url=os.getenv("SOURCE_SYSTEM_URL", ""),
        username=os.getenv("SOURCE_SYSTEM_USERNAME", ""),
        password=os.getenv("SOURCE_SYSTEM_PASSWORD", ""),
        headless=args.headless,
        max_setores=args.max_setores,
        pause_ms=args.pause_ms,
        table_timeout_ms=args.table_timeout_ms,
        search_retries=args.search_retries,
        csv_only=args.csv_only,
    )


if __name__ == "__main__":
    main()
