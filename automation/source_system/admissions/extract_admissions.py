#!/usr/bin/env python3
"""Extract admissions report from the source system for a given date."""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import openpyxl
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

# Iframe name for the admissions report
ADMISSIONS_IFRAME_NAME = "i_frame_pesquisar_pacientes_admitidos"
# Icon ID for the admissions report (from source system)
ADMISSIONS_ICON_SELECTOR = '[id="_icon_img_20340"]'

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai relatório de admissões do sistema fonte para uma data específica."
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
        help="Diretório de saída para o XLS/JSON",
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


def click_admissions_icon(page: Page) -> None:
    """Clica no ícone do relatório de admissões."""
    icon = page.locator(ADMISSIONS_ICON_SELECTOR)
    if not safe_click(icon, "ícone Relatório de Admissões", timeout=20000):
        raise RuntimeError("Não foi possível clicar no ícone de Relatório de Admissões.")
    print("[i] Ícone Relatório de Admissões clicado.")


def get_admissions_frame_locator(page: Page) -> FrameLocator:
    """Retorna o FrameLocator para o iframe do relatório de admissões."""
    return page.frame_locator(f'iframe[name="{ADMISSIONS_IFRAME_NAME}"]')


def wait_admissions_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    """Aguarda o iframe do relatório de admissões carregar."""
    print("[i] Aguardando iframe do relatório de admissões carregar...")
    frame_locator = get_admissions_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000

    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(state="attached", timeout=2000)
            print("[i] Iframe do relatório de admissões carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)

    raise RuntimeError("Timeout aguardando iframe do relatório de admissões.")


def fill_date_field(
    frame_locator: FrameLocator,
    field_id: str,
    date_value: str,
    label: str,
) -> None:
    """Preenche um campo de data no PrimeFaces datepicker."""
    print(f"[i] Preenchendo {label}: {date_value}")

    input_selector = f'input[id="{field_id}"]'
    date_input = frame_locator.locator(input_selector)

    if not wait_visible(date_input, timeout=10000):
        raise RuntimeError(f"Campo de data {label} não encontrado: {field_id}")

    date_input.click()
    date_input.fill("")
    page = frame_locator.page
    page.wait_for_timeout(200)

    # Type the date to ensure PrimeFaces registers it
    date_input.type(date_value, delay=50)
    page.wait_for_timeout(300)

    # Tab out to trigger PrimeFaces validation/blur event
    date_input.press("Tab")
    page.wait_for_timeout(500)

    print(f"  [i] {label} preenchido com: {date_value}")


def click_pesquisar(frame_locator: FrameLocator) -> None:
    """Clica no botão Pesquisar dentro do iframe."""
    btn = frame_locator.get_by_role("button", name="Pesquisar")
    if not wait_visible(btn, timeout=15000):
        raise RuntimeError("Botão Pesquisar não encontrado.")
    print("[i] Clicando em Pesquisar...")
    btn.click(timeout=15000)
    # Aguarda resultados carregarem
    if frame_locator.page:
        frame_locator.page.wait_for_timeout(3000)
    print("[i] Pesquisa concluída.")


def click_exportar_xls(frame_locator: FrameLocator, page: Page) -> bytes:
    """Clica em Exportar para Arquivo > XLS (Tudo) e retorna o conteúdo do download."""
    export_btn = frame_locator.get_by_role("button", name="Exportar para Arquivo")
    if not wait_visible(export_btn, timeout=15000):
        raise RuntimeError("Botão Exportar para Arquivo não encontrado.")

    print("[i] Clicando em Exportar para Arquivo...")
    export_btn.click(timeout=15000)
    page.wait_for_timeout(1000)

    # Localiza o link "XLS (Tudo)" no dropdown que apareceu
    xls_link = frame_locator.locator("a").filter(has_text="XLS (Tudo)")
    if not wait_visible(xls_link, timeout=10000):
        raise RuntimeError("Link XLS (Tudo) não encontrado no dropdown.")

    print("[i] Disparando download do XLS...")
    with page.expect_download(timeout=120000) as download_info:
        xls_link.click(timeout=15000)

    download = download_info.value
    print(f"  [i] Download iniciado: {download.suggested_filename}")

    download_path = download.path()
    if download_path is None:
        raise RuntimeError("Download não produziu um arquivo no disco.")

    content = download_path.read_bytes()
    print(f"  [i] XLS baixado: {len(content)} bytes")

    return content


def parse_xls_content(content: bytes) -> list[dict[str, str | None]]:
    """Converte o conteúdo XLS em lista de dicionários usando openpyxl."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise RuntimeError(f"Falha ao ler arquivo XLS: {exc}") from exc

    ws = wb.active
    if ws is None:
        raise RuntimeError("Planilha XLS não possui aba ativa.")

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Primeira linha como cabeçalho
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]

    records: list[dict[str, str | None]] = []
    for row in rows[1:]:
        record: dict[str, str | None] = {}
        for i, value in enumerate(row):
            col_name = headers[i] if i < len(headers) else f"col_{i}"
            if value is None:
                record[col_name] = None
            elif isinstance(value, str):
                record[col_name] = value.strip()
            else:
                record[col_name] = str(value)
        records.append(record)

    wb.close()
    return records


def save_outputs(
    output_dir: Path,
    xls_content: bytes,
    records: list[dict[str, str | None]],
    date_value: str,
    start_date: str,
    end_date: str,
) -> tuple[Path, Path]:
    """Salva o XLS bruto e o JSON processado."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    safe_date = date_value.replace("/", "-")
    xls_path = output_dir / f"admissoes-{safe_date}-{ts}.xlsx"
    xls_path.write_bytes(xls_content)

    json_path = output_dir / f"admissoes-{safe_date}-{ts}.json"
    data = {
        "data": date_value,
        "start_date": start_date,
        "end_date": end_date,
        "total": len(records),
        "columns": list(records[0].keys()) if records else [],
        "records": records,
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return xls_path, json_path


def save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug."""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"admissoes-error-{ts}.png"), full_page=True)
        (DEBUG_DIR / f"admissoes-error-{ts}.html").write_text(page.content(), encoding="utf-8")
        print(f"[i] Debug salvo em debug/admissoes-error-{ts}.*")
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
    """Executa o fluxo completo de extração do relatório de admissões."""
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

            print("[i] Abrindo relatório de admissões...")
            click_admissions_icon(page)
            page.wait_for_timeout(2000)

            frame_locator = wait_admissions_frame_ready(page)
            page.wait_for_timeout(1500)

            # Preencher campos de data
            fill_date_field(
                frame_locator,
                "dataInicial:dataInicial:inputId_input",
                start_date,
                "data inicial",
            )
            page.wait_for_timeout(500)

            fill_date_field(
                frame_locator,
                "dataFinal:dataFinal:inputId_input",
                end_date,
                "data final",
            )
            page.wait_for_timeout(500)

            # Pesquisar
            click_pesquisar(frame_locator)
            page.wait_for_timeout(2000)

            # Exportar XLS
            xls_content = click_exportar_xls(frame_locator, page)

            # Processar e salvar
            records = parse_xls_content(xls_content)
            print(f"  [i] Registros extraídos: {len(records)}")

            if records:
                print(f"  [i] Colunas: {list(records[0].keys())}")

            xls_path, json_path = save_outputs(
                output_dir=output_dir,
                xls_content=xls_content,
                records=records,
                date_value=date_value,
                start_date=start_date,
                end_date=end_date,
            )
            print(f"[i] XLS salvo em: {xls_path}")
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
    """Resolve as datas a partir dos argumentos."""
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
