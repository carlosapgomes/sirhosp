#!/usr/bin/env python3
"""Extract official daily census ZIP files from the source system.

Downloads a ZIP containing two TXT files. The relevant one starts with
'arquivoCensoPacientesInternacao' and is a semicolon-delimited CSV.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import zipfile
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

from proxy_config import get_playwright_proxy  # noqa: E402
from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais  # noqa: E402

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000
RETRY_INTERVAL_MS = 2000
RETRY_ATTEMPTS = 3

# Iframe name for the official census file generator
CENSUS_IFRAME_NAME = "i_frame_gera_arquivo_censo_pacientes"
# Icon ID for the official census (from source system)
CENSUS_ICON_SELECTOR = '[id="_icon_img_405577"]'

# Prefix of the internal TXT file we care about
CENSUS_TXT_PREFIX = "arquivoCensoPacientesInternacao"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai arquivos do censo oficial do sistema fonte para uma data específica."
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
        help="Diretório de saída para o ZIP/JSON",
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
        help="Data do censo no formato DD/MM/AAAA (padrão: hoje)",
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


def click_census_icon(page: Page) -> None:
    """Clica no ícone do gerador de arquivos de censo."""
    icon = page.locator(CENSUS_ICON_SELECTOR)
    if not safe_click(icon, "ícone Censo Oficial", timeout=20000):
        raise RuntimeError("Não foi possível clicar no ícone do Censo Oficial.")
    print("[i] Ícone Censo Oficial clicado.")


def get_census_frame_locator(page: Page) -> FrameLocator:
    """Retorna o FrameLocator para o iframe do censo oficial."""
    return page.frame_locator(f'iframe[name="{CENSUS_IFRAME_NAME}"]')


def wait_census_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    """Aguarda o iframe do censo oficial carregar."""
    print("[i] Aguardando iframe do censo oficial carregar...")
    frame_locator = get_census_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000

    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(state="attached", timeout=2000)
            print("[i] Iframe do censo oficial carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)

    raise RuntimeError("Timeout aguardando iframe do censo oficial.")


def fill_date_field(
    frame_locator: FrameLocator,
    page: Page,
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
    page.wait_for_timeout(200)

    date_input.type(date_value, delay=50)
    page.wait_for_timeout(300)

    date_input.press("Tab")
    page.wait_for_timeout(500)

    print(f"  [i] {label} preenchido com: {date_value}")


def click_gerar_arquivos(frame_locator: FrameLocator, page: Page) -> bytes:
    """Clica no botão Gerar Arquivos e retorna o conteúdo do ZIP baixado."""
    btn = frame_locator.get_by_role("button", name="Gerar Arquivos")
    if not wait_visible(btn, timeout=15000):
        raise RuntimeError("Botão Gerar Arquivos não encontrado.")

    print("[i] Disparando download do ZIP...")

    with page.expect_download(timeout=180000) as download_info:
        btn.click(timeout=15000)

    download = download_info.value
    print(f"  [i] Download iniciado: {download.suggested_filename}")

    download_path = download.path()
    if download_path is None:
        raise RuntimeError("Download não produziu um arquivo no disco.")

    content = download_path.read_bytes()
    print(f"  [i] ZIP baixado: {len(content)} bytes")

    return content


def extract_census_txt_from_zip(zip_content: bytes) -> tuple[str, str]:
    """Extrai o conteúdo do TXT de censo de dentro do ZIP.

    Procura pelo arquivo com prefixo 'arquivoCensoPacientesInternacao'.

    Returns:
        (filename, text_content) do arquivo encontrado.

    Raises:
        RuntimeError: Se o arquivo não for encontrado no ZIP.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_content))
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Arquivo baixado não é um ZIP válido: {exc}") from exc

    txt_files = [
        name
        for name in zf.namelist()
        if name.startswith(CENSUS_TXT_PREFIX) and name.endswith(".txt")
    ]

    if not txt_files:
        all_files = zf.namelist()
        raise RuntimeError(
            f"Nenhum arquivo '{CENSUS_TXT_PREFIX}*.txt' encontrado no ZIP. "
            f"Arquivos no ZIP: {all_files}"
        )

    target = txt_files[0]
    content = zf.read(target).decode("utf-8", errors="replace")
    print(f"  [i] Arquivo extraído do ZIP: {target} ({len(content)} bytes)")
    zf.close()
    return target, content


def parse_census_txt(text_content: str) -> list[dict[str, str]]:
    """Converte o conteúdo TXT (semicolon CSV) em lista de dicionários."""
    reader = csv.DictReader(io.StringIO(text_content), delimiter=";")
    records: list[dict[str, str]] = []
    for row in reader:
        record = {
            k.strip(): v.strip() if v else ""
            for k, v in row.items()
        }
        records.append(record)
    return records


def save_outputs(
    output_dir: Path,
    zip_content: bytes,
    txt_filename: str,
    txt_content: str,
    records: list[dict[str, str]],
    date_value: str,
) -> tuple[Path, Path, Path]:
    """Salva o ZIP bruto, o TXT extraído e o JSON processado."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    safe_date = date_value.replace("/", "-")

    zip_path = output_dir / f"censo-oficial-{safe_date}-{ts}.zip"
    zip_path.write_bytes(zip_content)

    txt_path = output_dir / f"censo-oficial-{safe_date}-{ts}.txt"
    txt_path.write_text(txt_content, encoding="utf-8")

    json_path = output_dir / f"censo-oficial-{safe_date}-{ts}.json"
    data = {
        "data": date_value,
        "arquivo_original": txt_filename,
        "total": len(records),
        "columns": list(records[0].keys()) if records else [],
        "records": records,
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return zip_path, txt_path, json_path


def save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug."""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"censo-oficial-error-{ts}.png"), full_page=True)
        (DEBUG_DIR / f"censo-oficial-error-{ts}.html").write_text(page.content(), encoding="utf-8")
        print(f"[i] Debug salvo em debug/censo-oficial-error-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


def run(
    source_url: str,
    username: str,
    password: str,
    headless: bool,
    date_value: str,
    output_dir: Path,
) -> None:
    """Executa o fluxo completo de extração do censo oficial."""
    with sync_playwright() as pw:
        browser = context = page = None
        try:
            print("[i] Abrindo navegador...")
            _proxy = get_playwright_proxy()
            browser = pw.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
                **({"proxy": _proxy} if _proxy else {}),
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

            print("[i] Abrindo gerador de arquivos de censo...")
            click_census_icon(page)
            page.wait_for_timeout(2000)

            frame_locator = wait_census_frame_ready(page)
            page.wait_for_timeout(1500)

            # Preencher campos de data (inicial e final com a mesma data)
            fill_date_field(
                frame_locator,
                page,
                "data_inicial:data_inicial:inputId_input",
                date_value,
                "data inicial",
            )
            page.wait_for_timeout(500)

            fill_date_field(
                frame_locator,
                page,
                "data_fim:data_fim:inputId_input",
                date_value,
                "data final",
            )
            page.wait_for_timeout(500)

            # Gerar arquivos (ZIP)
            zip_content = click_gerar_arquivos(frame_locator, page)

            # Extrair TXT do ZIP
            txt_filename, txt_content = extract_census_txt_from_zip(zip_content)

            # Parsear CSV (separador ";")
            records = parse_census_txt(txt_content)
            print(f"  [i] Registros extraídos: {len(records)}")

            if records:
                print(f"  [i] Colunas: {list(records[0].keys())}")

            zip_path, txt_path, json_path = save_outputs(
                output_dir=output_dir,
                zip_content=zip_content,
                txt_filename=txt_filename,
                txt_content=txt_content,
                records=records,
                date_value=date_value,
            )
            print(f"[i] ZIP salvo em: {zip_path}")
            print(f"[i] TXT salvo em: {txt_path}")
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


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DOWNLOADS_DIR
    date_value = args.date or time.strftime("%d/%m/%Y")

    print(f"[i] Data do censo: {date_value}")

    run(
        source_url=args.source_url,
        username=args.username,
        password=args.password,
        headless=args.headless,
        date_value=date_value,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
