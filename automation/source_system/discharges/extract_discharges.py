#!/usr/bin/env python3
"""Extract discharged patients from the source system for a specific date."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

import pymupdf
from playwright.sync_api import (
    BrowserContext,
    FrameLocator,
    Locator,
    Page,
    expect,
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
ALTAS_IFRAME_NAME = "i_frame_altas_do_dia"
ALTAS_ICON_SELECTOR = ".silk-new-internacao-altas-do-dia"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"


def _today_dd_mm_yyyy() -> str:
    return time.strftime("%d/%m/%Y")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai lista de pacientes com alta em data especifica do sistema fonte."
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
        help="Diretorio de saida para o JSON",
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


def esperar_locator_com_retry(
    page: Page,
    descricao: str,
    locator_factory: Callable[[], Locator],
    *,
    timeout: int = UI_TIMEOUT_MS,
    tentativas: int = RETRY_ATTEMPTS,
) -> Locator:
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        locator = locator_factory()

        try:
            expect(locator).to_be_visible(timeout=timeout)
            return locator
        except Exception as erro:
            ultimo_erro = erro
            if tentativa == tentativas:
                break

            print(
                f"Tentativa {tentativa}/{tentativas} falhou ao localizar "
                f"{descricao}. Tentando novamente..."
            )
            page.wait_for_timeout(RETRY_INTERVAL_MS)
            aguardar_pagina_estavel(page)

    raise ultimo_erro


def wait_visible(locator: Locator, timeout: int = 10000) -> bool:
    """Aguarda elemento ficar visivel."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator: Locator, label: str, timeout: int = 15000) -> bool:
    """Clica em um locator com fallback (force click e DOM click)."""
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


def get_altas_frame_locator(page: Page) -> FrameLocator:
    """Retorna o FrameLocator para o iframe de altas do dia."""
    return page.frame_locator(f'iframe[name="{ALTAS_IFRAME_NAME}"]')


def wait_altas_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    """Aguarda o iframe de altas do dia carregar."""
    print("[i] Aguardando iframe de altas do dia carregar...")
    frame_locator = get_altas_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000

    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(state="attached", timeout=2000)
            print("[i] Iframe de altas do dia carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)

    raise RuntimeError("Timeout aguardando iframe de altas do dia.")


def click_altas_icon(page: Page) -> None:
    """Clica no icone de Altas do Dia usando classe CSS estavel."""
    icon = page.locator(ALTAS_ICON_SELECTOR)
    if not safe_click(icon, "icone Altas do Dia", timeout=20000):
        raise RuntimeError("Nao foi possivel clicar no icone de Altas do Dia.")
    print("[i] icone Altas do Dia clicado.")


def fill_date_field(frame_locator: FrameLocator, page: Page, date_value: str) -> None:
    """Preenche o campo de data de alta no iframe."""
    print(f"[i] Preenchendo data de alta: {date_value}")

    # O campo de data tem id: dataAlta:dataAlta:inputId_input (PrimeFaces)
    date_input_selector = 'input[id="dataAlta:dataAlta:inputId_input"]'
    date_input = frame_locator.locator(date_input_selector)

    if not wait_visible(date_input, timeout=10000):
        raise RuntimeError(
            f"Campo de data nao encontrado: {date_input_selector}"
        )

    date_input.click()
    date_input.fill("")
    page.wait_for_timeout(200)

    # Digita caractere por caractere para o PrimeFaces registrar
    date_input.type(date_value, delay=50)
    page.wait_for_timeout(300)

    # Tab out para triggerar validacao/blur do PrimeFaces
    date_input.press("Tab")
    page.wait_for_timeout(500)

    print(f"  [i] Data de alta preenchida: {date_value}")


def click_visualizar_impressao(frame_locator: FrameLocator) -> None:
    """Clica no botão Visualizar Impressão dentro do iframe de altas."""
    btn = frame_locator.get_by_role("button", name="Visualizar Impressão")
    if not safe_click(btn, "botão Visualizar Impressão", timeout=20000):
        raise RuntimeError("Não foi possível clicar em Visualizar Impressão.")
    print("[i] Botão Visualizar Impressão clicado.")


def get_pdf_url_from_frame(frame_locator: FrameLocator, page: Page) -> str:
    """Extrai a URL do PDF do <object> dentro do iframe de altas."""
    print("[i] Aguardando objeto PDF aparecer...")

    pdf_object = esperar_locator_com_retry(
        page,
        "visualizador PDF no iframe de altas",
        lambda: frame_locator.locator('object[type="application/pdf"]'),
        timeout=120000,
    )

    ultimo_data = None
    for tentativa in range(1, 4):
        pdf_url = pdf_object.get_attribute("data")
        if pdf_url:
            absolute_url = urljoin(page.url, pdf_url)
            print(f"[i] URL do PDF: {absolute_url}")
            return absolute_url

        ultimo_data = pdf_url
        if tentativa < 3:
            print(
                f"  [!] Tentativa {tentativa}/3: atributo 'data' nao disponivel. "
                "Aguardando..."
            )
            page.wait_for_timeout(2000)

    raise RuntimeError(
        "O elemento <object> do PDF apareceu, mas o atributo 'data' nao ficou disponivel. "
        f"Ultimo valor: {ultimo_data!r}"
    )


def download_pdf(context: BrowserContext, pdf_url: str, output_path: Path) -> None:
    """Faz download autenticado do PDF."""
    print(f"[i] Baixando PDF de {pdf_url}...")
    response = context.request.get(pdf_url, timeout=120000)

    if not response.ok:
        raise RuntimeError(f"Falha ao baixar PDF. HTTP {response.status}")

    content_type = (response.headers.get("content-type") or "").lower()
    body = response.body()

    print(f"  Content-Type: {content_type}")
    print(f"  Tamanho: {len(body)} bytes")

    if not body.startswith(b"%PDF-"):
        # Salva para debug
        debug_path = output_path.with_suffix(".debug.html")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_bytes(body)
        raise RuntimeError(
            f"Conteudo retornado nao e um PDF valido. Salvo em: {debug_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)
    print(f"[i] PDF salvo em: {output_path}")


# ---------------------------------------------------------------------------
# Extracao da tabela do PDF (reutiliza logica do extract_discharges.py)
# ---------------------------------------------------------------------------

_RE_PRONTUARIO = re.compile(r"^\d{2,7}/\d$")
_RE_DATA_CURTA = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_RE_DATA_LONGA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_CRM = re.compile(r"^\d{4,6}$")
_RE_CRM_PLACEHOLDER = re.compile(r"^CRM([A-Z]{2})?$", re.IGNORECASE)
_RE_SO_NUMEROS = re.compile(r"\D")
_RE_PREFIXO = re.compile(r"^[A-Z]{1,2}$")


def _clean_prontuario(raw: str) -> str:
    """Remove '/' e mantem so digitos."""
    return _RE_SO_NUMEROS.sub("", raw)


def _normalize_data(raw: str) -> str:
    """Normaliza data para DD/MM/YYYY."""
    if not raw:
        return raw
    parts = raw.split("/")
    if len(parts) != 3:
        return raw
    day, month, year = parts
    if len(year) == 2:
        year = "20" + year
    return f"{day}/{month}/{year}"


def extract_patients_from_pdf(pdf_path: Path) -> list[dict[str, str]]:
    """
    Extrai a lista de pacientes do PDF de altas.

    Usa analise de coordenadas x/y pois o PDF e landscape rotacionado
    e o texto extraido nao segue a ordem visual das colunas.
    """
    if not pdf_path.exists():
        raise RuntimeError(f"PDF nao encontrado: {pdf_path}")

    print(f"[i] Extraindo tabela de {pdf_path}...")
    all_patients: list[dict[str, str]] = []

    with pymupdf.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            words = page.get_text("words")
            if not words:
                continue

            print(
                f"  Pagina {page_num}: {len(words)} palavras, analisando bandas X..."
            )
            patients = _extract_patients_by_x_bands(words)
            print(f"  Pacientes encontrados: {len(patients)}")
            all_patients.extend(patients)

    # Pos-processamento: limpa prontuarios e normaliza datas
    for patient in all_patients:
        if patient.get("prontuario"):
            patient["prontuario"] = _clean_prontuario(patient["prontuario"])
        if patient.get("data_internacao"):
            patient["data_internacao"] = _normalize_data(patient["data_internacao"])

    return all_patients


def _extract_patients_by_x_bands(words: list) -> list[dict[str, str]]:
    """
    Agrupa palavras por bandas de coordenada X e extrai pacientes.
    """
    pront_words = []
    for word in words:
        if _RE_PRONTUARIO.match(word[4]):
            pront_words.append(word)

    if not pront_words:
        return []

    bands = _group_by_x_band(pront_words, tolerance=1.5)

    patients = []
    for band_x in sorted(bands.keys()):
        main_words = []
        secondary_words = []

        for word in words:
            wx = round(word[0], 1)
            if abs(wx - band_x) < 1.0:
                main_words.append(word)
            elif abs(wx - (band_x + 1.0)) < 1.0:
                secondary_words.append(word)

        if not main_words:
            continue

        main_words.sort(key=lambda word: -word[1])
        secondary_words.sort(key=lambda word: -word[1])

        patient = _parse_patient_band(main_words, secondary_words)
        if patient:
            patients.append(patient)

    return patients


def _group_by_x_band(pront_words: list, tolerance: float = 1.5) -> dict[float, list]:
    """Agrupa palavras por bandas de coordenada X."""
    sorted_words = sorted(pront_words, key=lambda word: word[0])
    bands: dict[float, list] = {}
    current_band_x = None

    for word in sorted_words:
        wx = round(word[0], 1)
        if current_band_x is None or (wx - current_band_x) > tolerance:
            current_band_x = wx
            bands[current_band_x] = []
        bands[current_band_x].append(word)

    return bands


def _parse_patient_band(
    main_words: list, secondary_words: list
) -> dict[str, str] | None:
    """
    Faz parsing dos campos de um paciente a partir das palavras da banda.
    """
    pront = ""
    nome_parts: list[str] = []
    data_int = ""
    leito = ""
    esp = ""

    i = 0
    mw = main_words

    # 1. Prontuario (sempre o primeiro)
    if i < len(mw) and _RE_PRONTUARIO.match(mw[i][4]):
        pront = mw[i][4]
        i += 1

    # 2. Pula prefixos
    while i < len(mw) and _RE_PREFIXO.match(mw[i][4]):
        i += 1

    # 3. Nome do paciente: ate o CRM
    while i < len(mw):
        word = mw[i][4]
        if _RE_CRM.match(word) or _RE_CRM_PLACEHOLDER.match(word):
            i += 1
            break
        nome_parts.append(word)
        i += 1

    # 4. Pula nome do medico e captura Data Int
    while i < len(mw):
        word = mw[i][4]
        if _RE_DATA_CURTA.match(word) or _RE_DATA_LONGA.match(word):
            data_int = word
            i += 1
            break
        i += 1

    if not data_int:
        while i < len(mw):
            word = mw[i][4]
            if _RE_DATA_CURTA.match(word) or _RE_DATA_LONGA.match(word):
                data_int = word
                break
            i += 1

    # --- Coluna secundaria ---
    sw = secondary_words
    seen_texts: set[str] = set()
    sw_dedup = []
    for word in sw:
        if word[4] not in seen_texts:
            seen_texts.add(word[4])
            sw_dedup.append(word)

    valid = [
        word
        for word in sw_dedup
        if not _RE_DATA_CURTA.match(word[4]) and not _RE_DATA_LONGA.match(word[4])
    ]

    if len(valid) >= 2:
        leito = valid[0][4]
        esp = valid[-1][4]
    elif len(valid) == 1:
        word = valid[0][4]
        if 2 <= len(word) <= 4 and word.isupper() and word.isalpha():
            esp = word
        else:
            leito = word

    nome = " ".join(nome_parts).strip()
    if not pront and not nome:
        return None

    return {
        "prontuario": pront,
        "nome": nome,
        "leito": leito,
        "especialidade": esp,
        "data_internacao": data_int,
    }


def save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug."""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(
            path=str(DEBUG_DIR / f"discharges-by-date-error-{ts}.png"),
            full_page=True,
        )
        (DEBUG_DIR / f"discharges-by-date-error-{ts}.html").write_text(
            page.content(), encoding="utf-8"
        )
        print(f"[i] Debug salvo em debug/discharges-by-date-error-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DOWNLOADS_DIR

    # Resolve date
    date_value = args.date or _today_dd_mm_yyyy()
    ref_date = args.reference_date or time.strftime("%Y-%m-%d")
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
            # Login — usa seletores CSS em vez de role/name para robustez em headless
            page.goto(args.source_url)
            page.locator("input[placeholder=\"Nome de usu\u00e1rio\"]").fill(args.username)
            page.locator("input[placeholder=\"Senha\"]").fill(args.password)
            page.locator("input[placeholder=\"Senha\"]").press("Enter")
            aguardar_pagina_estavel(page)
            fechar_dialogos_iniciais(page)

            # Navegar para Altas do Dia
            click_altas_icon(page)
            frame_locator = wait_altas_frame_ready(page)
            page.wait_for_timeout(1500)

            # Preencher campo de data
            fill_date_field(frame_locator, page, date_value)
            page.wait_for_timeout(500)

            # Visualizar Impressao
            click_visualizar_impressao(frame_locator)
            page.wait_for_timeout(3000)

            # Download PDF
            pdf_url = get_pdf_url_from_frame(frame_locator, page)
            pdf_filename = f"altas-{safe_date}.pdf"
            pdf_path = output_dir / pdf_filename
            download_pdf(context, pdf_url, pdf_path)

            # Extrair pacientes
            patients = extract_patients_from_pdf(pdf_path)

            # Salvar JSON
            output_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            json_path = output_dir / f"discharges-{safe_date}-{ts}.json"
            data = {
                "data": ref_date,
                "date_display": date_value,
                "total": len(patients),
                "pacientes": patients,
            }
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[i] JSON salvo em: {json_path}")

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
