#!/usr/bin/env python3
"""Extract discharged patients from source system as XLS."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    FrameLocator,
    Locator,
    Page,
    sync_playwright,
)

_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_SYSTEM_DIR = _CURRENT_DIR.parent
sys.path.insert(0, str(_SOURCE_SYSTEM_DIR))

from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais  # noqa: E402

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000

PROCURAR_IFRAME_NAME = "i_frame_pesquisar_pacientes_com_alta"
PROCURAR_ICON_SELECTOR = '[id="_icon_img_20341"]'

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extrai relatorio de pacientes com alta do sistema fonte "
            "como arquivo XLS."
        )
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem interface grafica",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretorio de saida para o XLS/JSON",
    )
    parser.add_argument(
        "--source-url",
        type=str,
        required=True,
        help="URL do sistema fonte",
    )
    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="Nome de usuario do sistema fonte",
    )
    parser.add_argument(
        "--password",
        type=str,
        required=True,
        help="Senha do sistema fonte",
    )
    parser.add_argument(
        "--reference-date",
        type=str,
        default=None,
        help="Data de referencia no formato YYYY-MM-DD (padrao: hoje)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Data das altas no formato DD/MM/AAAA (padrao: hoje)",
    )
    return parser.parse_args()


def _today_dd_mm_yyyy() -> str:
    return time.strftime("%d/%m/%Y")


def wait_visible(locator: Locator, timeout: int = 10000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator: Locator, label: str, timeout: int = 15000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        print(f"  [!] Nao visivel para clique: {label}")
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


def click_procurar_icon(page: Page) -> None:
    icon = page.locator(PROCURAR_ICON_SELECTOR)
    if not safe_click(icon, "icone Pesquisar Pacientes Com Alta", timeout=20000):
        raise RuntimeError(
            "Nao foi possivel clicar no icone Pesquisar Pacientes Com Alta."
        )
    print("[i] icone Pesquisar Pacientes Com Alta clicado.")


def get_frame_locator(page: Page) -> FrameLocator:
    return page.frame_locator(f'iframe[name="{PROCURAR_IFRAME_NAME}"]')


def wait_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    print("[i] Aguardando iframe pesquisar pacientes com alta carregar...")
    frame_locator = get_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000
    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(
                state="attached", timeout=2000
            )
            print("[i] Iframe pesquisar pacientes com alta carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)
    raise RuntimeError("Timeout aguardando iframe pesquisar pacientes com alta.")


def fill_date_field(
    frame_locator: FrameLocator,
    page: Page,
    field_id: str,
    date_value: str,
    label: str,
) -> None:
    print(f"[i] Preenchendo {label}: {date_value}")
    selector = f'input[id="{field_id}"]'
    date_input = frame_locator.locator(selector)
    if not wait_visible(date_input, timeout=10000):
        raise RuntimeError(f"Campo de data {label} nao encontrado.")
    date_input.click()
    date_input.fill("")
    page.wait_for_timeout(200)
    date_input.type(date_value, delay=50)
    page.wait_for_timeout(300)
    date_input.press("Tab")
    page.wait_for_timeout(500)
    print(f"  [i] {label} preenchido: {date_value}")


def click_exportar_arquivo(frame_locator: FrameLocator) -> None:
    """Clica no botao Exportar para Arquivo para abrir o menu."""
    # PrimeFaces button: text inside <span class="ui-button-text ui-c">
    btn = frame_locator.locator("button").filter(has_text="Exportar para Arquivo")
    if not safe_click(btn, "botao Exportar para Arquivo", timeout=20000):
        raise RuntimeError("Nao foi possivel clicar em Exportar para Arquivo.")
    print("[i] Botao Exportar para Arquivo clicado (menu aberto).")


def click_xls_option(page: Page, frame_locator: FrameLocator) -> bytes:
    """Clica na opcao XLS (Tudo) e retorna o conteudo do download."""
    xls_link = frame_locator.locator("a").filter(has_text="XLS (Tudo)")
    if not wait_visible(xls_link, timeout=10000):
        raise RuntimeError("Link XLS (Tudo) nao encontrado no menu.")

    print("[i] Disparando download do XLS...")
    with page.expect_download(timeout=120000) as download_info:
        xls_link.click(timeout=15000)

    download = download_info.value
    print(f"  [i] Download iniciado: {download.suggested_filename}")

    download_path = download.path()
    if download_path is None:
        raise RuntimeError("Download nao produziu arquivo no disco.")

    content = download_path.read_bytes()
    print(f"  [i] XLS baixado: {len(content)} bytes")
    return content


def save_xls(output_dir: Path, content: bytes, safe_date: str) -> Path:
    """Salva o XLS no diretorio de saida."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    xls_path = output_dir / f"altas-{safe_date}-{ts}.xlsx"
    xls_path.write_bytes(content)
    print(f"[i] XLS salvo em: {xls_path}")
    return xls_path


def save_debug(page: Page) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(
            path=str(DEBUG_DIR / f"discharges-xls-error-{ts}.png"),
            full_page=True,
        )
        (DEBUG_DIR / f"discharges-xls-error-{ts}.html").write_text(
            page.content(), encoding="utf-8"
        )
        print(f"[i] Debug salvo em debug/discharges-xls-error-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DOWNLOADS_DIR

    date_value = args.date or _today_dd_mm_yyyy()
    safe_date = date_value.replace("/", "-")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            # Login
            page.goto(args.source_url)
            page.locator(
                "input[placeholder=\"Nome de usu\u00e1rio\"]"
            ).fill(args.username)
            page.locator("input[placeholder=\"Senha\"]").fill(args.password)
            page.locator("input[placeholder=\"Senha\"]").press("Enter")
            aguardar_pagina_estavel(page)
            fechar_dialogos_iniciais(page)

            # Navegar para Pesquisar Pacientes Com Alta
            click_procurar_icon(page)
            frame_locator = wait_frame_ready(page)
            page.wait_for_timeout(1500)

            # Preencher campos de data
            fill_date_field(
                frame_locator, page,
                "dataInicial:dataInicial:inputId_input",
                date_value, "data inicial",
            )
            page.wait_for_timeout(500)

            fill_date_field(
                frame_locator, page,
                "dataFinal:dataFinal:inputId_input",
                date_value, "data final",
            )
            page.wait_for_timeout(500)

            # Clicar Pesquisar para carregar resultados
            pesquisar_btn = frame_locator.get_by_role("button", name="Pesquisar")
            if not safe_click(pesquisar_btn, "botao Pesquisar", timeout=20000):
                raise RuntimeError("Nao foi possivel clicar em Pesquisar.")
            print("[i] Botao Pesquisar clicado, aguardando resultados...")
            page.wait_for_timeout(3000)

            # Exportar XLS
            click_exportar_arquivo(frame_locator)
            page.wait_for_timeout(1000)

            xls_content = click_xls_option(page, frame_locator)

            # Salvar XLS
            save_xls(output_dir, xls_content, safe_date)

        except Exception as exc:
            print(f"[ERRO] {exc}", file=sys.stderr)
            try:
                save_debug(page)
            except Exception:
                pass
            sys.exit(1)
        finally:
            context.close()
            browser.close()
            pw.stop()


if __name__ == "__main__":
    main()
