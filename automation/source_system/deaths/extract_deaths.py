#!/usr/bin/env python3
"""Extract deaths report from the source system for a given date."""

from __future__ import annotations

import argparse
import csv
import io
import json
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
RETRY_INTERVAL_MS = 2000
RETRY_ATTEMPTS = 3

# Iframe name for the deaths report
DEATHS_IFRAME_NAME = "i_frame_óbitos_com_cid"
# Icon ID for the deaths report (from source system)
DEATHS_ICON_SELECTOR = '[id="_icon_img_405272"]'

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai relatório de óbitos do sistema fonte para uma data específica."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem interface gráfica",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretório de saída para o CSV/JSON",
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
        help="Nome de usuário do sistema fonte",
    )
    parser.add_argument(
        "--password",
        type=str,
        required=True,
        help="Senha do sistema fonte",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Data do relatório no formato DD/MM/AAAA (padrão: hoje)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Data inicial do período no formato DD/MM/AAAA",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Data final do período no formato DD/MM/AAAA",
    )
    return parser.parse_args()


def wait_visible(locator: Locator, timeout: int = 10000) -> bool:
    """Aguarda elemento ficar visível."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator: Locator, label: str, timeout: int = 15000) -> bool:
    """Clica em um locator com fallback (force click e DOM click)."""
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


def click_deaths_icon(page: Page) -> None:
    """Clica no ícone do relatório de óbitos."""
    icon = page.locator(DEATHS_ICON_SELECTOR)
    if not safe_click(icon, "ícone Relatório de Óbitos", timeout=20000):
        raise RuntimeError("Não foi possível clicar no ícone de Relatório de Óbitos.")
    print("[i] Ícone Relatório de Óbitos clicado.")


def get_deaths_frame_locator(page: Page) -> FrameLocator:
    """Retorna o FrameLocator para o iframe do relatório de óbitos."""
    return page.frame_locator(f'iframe[name="{DEATHS_IFRAME_NAME}"]')


def wait_deaths_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    """Aguarda o iframe do relatório de óbitos carregar."""
    print("[i] Aguardando iframe do relatório de óbitos carregar...")
    frame_locator = get_deaths_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000

    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(state="attached", timeout=2000)
            print("[i] Iframe do relatório de óbitos carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)

    raise RuntimeError("Timeout aguardando iframe do relatório de óbitos.")


def fill_date_field(
    frame_locator: FrameLocator,
    field_id: str,
    date_value: str,
    label: str,
) -> None:
    """Preenche um campo de data no PrimeFaces datepicker."""
    print(f"[i] Preenchendo {label}: {date_value}")

    # The PrimeFaces date input uses a colon-based ID pattern
    # e.g. dtInicial:dtInicial:inputId_input
    input_selector = f'input[id="{field_id}"]'

    date_input = frame_locator.locator(input_selector)
    if not wait_visible(date_input, timeout=10000):
        raise RuntimeError(f"Campo de data {label} não encontrado: {field_id}")

    date_input.click()
    date_input.fill("")
    page = frame_locator.page
    page.wait_for_timeout(200)

    # Type the date character by character to ensure PrimeFaces registers it
    date_input.type(date_value, delay=50)
    page.wait_for_timeout(300)

    # Tab out to trigger PrimeFaces validation/blur event
    date_input.press("Tab")
    page.wait_for_timeout(500)

    print(f"  [i] {label} preenchido com: {date_value}")


def click_export_csv(frame_locator: FrameLocator, page: Page) -> bytes:
    """Clica no botão Exportar Arquivo CSV e retorna o conteúdo do download."""
    btn = frame_locator.get_by_role("button", name="Exportar Arquivo CSV")

    if not wait_visible(btn, timeout=15000):
        raise RuntimeError("Botão Exportar Arquivo CSV não encontrado.")

    print("[i] Disparando download do CSV...")

    with page.expect_download(timeout=120000) as download_info:
        btn.click(timeout=15000)

    download = download_info.value
    print(f"  [i] Download iniciado: {download.suggested_filename}")

    download_path = download.path()
    if download_path is None:
        raise RuntimeError("Download não produziu um arquivo no disco.")

    content = download_path.read_bytes()
    print(f"  [i] CSV baixado: {len(content)} bytes")

    return content


def parse_csv_content(content: bytes) -> list[dict[str, str]]:
    """Converte o conteúdo CSV em lista de dicionários."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def save_outputs(
    output_dir: Path,
    csv_content: bytes,
    records: list[dict[str, str]],
    date_value: str,
    start_date: str,
    end_date: str,
) -> tuple[Path, Path]:
    """Salva o CSV bruto e o JSON processado."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    safe_date = date_value.replace("/", "-")
    csv_path = output_dir / f"obitos-{safe_date}-{ts}.csv"
    csv_path.write_bytes(csv_content)

    json_path = output_dir / f"obitos-{safe_date}-{ts}.json"
    data = {
        "data": date_value,
        "start_date": start_date,
        "end_date": end_date,
        "total": len(records),
        "columns": list(records[0].keys()) if records else [],
        "records": records,
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return csv_path, json_path


def save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug."""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"obitos-error-{ts}.png"), full_page=True)
        (DEBUG_DIR / f"obitos-error-{ts}.html").write_text(page.content(), encoding="utf-8")
        print(f"[i] Debug salvo em debug/obitos-error-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


def run(
    source_url: str,
    username: str,
    password: str,
    headless: bool,
    date_value: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
) -> None:
    """Executa o fluxo completo de extração do relatório de óbitos."""
    with sync_playwright() as pw:
        browser = context = page = None
        try:
            print("[i] Abrindo navegador...")
            browser = pw.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)

            print(f"[i] Acessando {source_url}...")
            page.goto(source_url)

            print("[i] Login...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("[i] Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            print("[i] Abrindo relatório de óbitos...")
            click_deaths_icon(page)
            page.wait_for_timeout(2000)

            frame_locator = wait_deaths_frame_ready(page)
            page.wait_for_timeout(1500)

            # Preencher campos de data
            fill_date_field(
                frame_locator,
                "dtInicial:dtInicial:inputId_input",
                start_date,
                "data inicial",
            )
            page.wait_for_timeout(500)

            fill_date_field(
                frame_locator,
                "dtFinal:dtFinal:inputId_input",
                end_date,
                "data final",
            )
            page.wait_for_timeout(500)

            # Exportar CSV
            csv_content = click_export_csv(frame_locator, page)

            # Processar e salvar
            records = parse_csv_content(csv_content)
            print(f"  [i] Registros extraídos: {len(records)}")

            if records:
                print(f"  [i] Colunas: {list(records[0].keys())}")

            csv_path, json_path = save_outputs(
                output_dir=output_dir,
                csv_content=csv_content,
                records=records,
                date_value=date_value,
                start_date=start_date,
                end_date=end_date,
            )
            print(f"[i] CSV salvo em: {csv_path}")
            print(f"[i] JSON salvo em: {json_path}")

        except Exception as exc:
            print(f"[ERRO] {exc}", file=sys.stderr)
            if page is not None:
                save_debug(page)
            sys.exit(1)
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
            pw.stop()


def resolve_dates(args: argparse.Namespace) -> tuple[str, str, str]:
    """Resolve as datas a partir dos argumentos.

    Prioridade:
      1. Se --start-date e --end-date fornecidos, usa-os.
      2. Se --date fornecido, usa mesma data para início e fim.
      3. Padrão: data atual.
    """
    today = time.strftime("%d/%m/%Y")

    if args.start_date and args.end_date:
        return (args.date or args.start_date, args.start_date, args.end_date)

    if args.date:
        return (args.date, args.date, args.date)

    return (today, today, today)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DOWNLOADS_DIR
    date_value, start_date, end_date = resolve_dates(args)

    print(f"[i] Período do relatório: {start_date} a {end_date}")

    run(
        source_url=args.source_url,
        username=args.username,
        password=args.password,
        headless=args.headless,
        date_value=date_value,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
