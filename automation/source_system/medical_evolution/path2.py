from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, unquote, urljoin, urlparse
import html

from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, Locator, Page, Frame, sync_playwright

from datetime import date, datetime, timedelta

from processa_evolucoes_txt import remove_page_artifacts
from source_system import (
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    baixar_pdf_autenticado,
    extrair_texto_do_pdf,
    fechar_dialogos_iniciais,
    obter_pdf_url_do_object,
    salvar_debug,
    salvar_texto_extraido,
)

DEFAULT_PATIENT_RECORD: Final[str] = "8920415"
DEFAULT_START_DATE: Final[str] = "05/06/2024"
DEFAULT_END_DATE: Final[str] = "01/07/2024"
DEFAULT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.pdf")
DEFAULT_DEBUG_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.debug.html")
DEFAULT_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.txt")
DEFAULT_NORMALIZED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-normalizado.txt")
DEFAULT_PROCESSED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-processado.txt")
DEFAULT_SORTED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-ordenado.txt")
DEFAULT_JSON_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.json")
FRAME_NAME: Final[str] = "frame_pol"
REPORT_WAIT_TIMEOUT_MS: Final[int] = 180000
REPORT_POLL_INTERVAL_MS: Final[int] = 5000
REPORT_DOWNLOAD_TIMEOUT_MS: Final[int] = 600000
MAX_CHUNK_DAYS: Final[int] = 15
CHUNK_OVERLAP_DAYS: Final[int] = 1
PAGE_HEADER_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'(?ms)^(===== PÁGINA \d+ =====)\nEVOLUÇÃO\n(/\s*\d+)\n(\d+)\n'
)
DATETIME_WITHOUT_SECONDS_RE: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\d{2}/\d{2}/\d{4} \d{2}:\d{2})$'
)
DATETIME_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}(?::\d{2})?$'
)
EVOLUTION_END_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r'^Elaborado\b.*\bem:?\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?$',
    re.IGNORECASE,
)
SIGNATURE_AUTHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'\bpor[:\s]+(.+?)\s*(?:,|-)?\s*(?:Crm|Coren|Crefito|Crefono|Crn\d*|Cro(?:-?[A-Z]{2})?)\b',
    re.IGNORECASE,
)
SIGNATURE_DATETIME_RE: Final[re.Pattern[str]] = re.compile(
    r'\bem:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)\s*$',
    re.IGNORECASE,
)


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Navega pelo caminho de internações, abre a evolução por intervalo, baixa o PDF bruto, "
            "extrai o texto e organiza as evoluções em arquivos TXT."
        )
    )
    parser.add_argument("--patient-record", default=DEFAULT_PATIENT_RECORD)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument(
        "--internacao-index",
        type=int,
        default=-1,
        help=(
            "Índice manual da internação para depuração. "
            "Use -1 (padrão) para seleção automática por interseção de datas."
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--debug-output", type=Path, default=DEFAULT_DEBUG_PATH)
    parser.add_argument("--txt-output", type=Path, default=DEFAULT_TXT_OUTPUT_PATH)
    parser.add_argument("--normalized-txt-output", type=Path, default=DEFAULT_NORMALIZED_TXT_OUTPUT_PATH)
    parser.add_argument("--processed-output", type=Path, default=DEFAULT_PROCESSED_TXT_OUTPUT_PATH)
    parser.add_argument("--sorted-output", type=Path, default=DEFAULT_SORTED_TXT_OUTPUT_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT_PATH)
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def wait_visible(locator: Locator, timeout: int = 5000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_if_visible(locator: Locator, description: str, timeout: int = 5000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        return False

    locator.first.click()
    print(f"OK: {description}")
    return True


def click_with_fallback(locator: Locator, description: str, timeout: int = 5000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        return False

    target = locator.first

    try:
        target.click(timeout=timeout)
        print(f"OK: {description}")
        return True
    except Exception as click_error:
        print(f"Aviso: clique padrão falhou em {description}: {click_error}")

    try:
        target.click(timeout=timeout, force=True)
        print(f"OK: {description} (force=True)")
        return True
    except Exception as force_error:
        print(f"Aviso: clique forçado falhou em {description}: {force_error}")

    try:
        target.evaluate("(element) => element.click()")
        print(f"OK: {description} (DOM click)")
        return True
    except Exception as eval_error:
        print(f"Aviso: DOM click falhou em {description}: {eval_error}")

    return False


def normalize_patient_record(value: str) -> str:
    digits_only = re.sub(r"\D", "", value)
    return digits_only or value.strip()


def parse_cli_date(value: str) -> date:
    candidate = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue

    raise RuntimeError(
        f"Data inválida: {value!r}. Use DD/MM/YYYY ou YYYY-MM-DD."
    )


def parse_br_date(value: str | None) -> date | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        return datetime.strptime(stripped, "%d/%m/%Y").date()
    except ValueError:
        return None


def format_br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def format_iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def normalize_signature_key(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", (value or "").strip().casefold())
    return collapsed


def open_pol_menu(page: Page) -> bool:
    locator = page.locator("#polMenu")
    if not wait_visible(locator, timeout=5000):
        return False

    try:
        locator.first.evaluate("(element) => element.click()")
        print("OK: botão #polMenu (DOM click)")
        return True
    except Exception as error:
        print(f"Aviso: DOM click falhou em #polMenu: {error}")

    return click_with_fallback(locator, "botão #polMenu", timeout=5000)


def ensure_search_screen(page: Page) -> None:
    promptuario = page.locator("#prontuarioInput")
    if wait_visible(promptuario, timeout=5000):
        print("Tela de pesquisa já está visível.")
        return

    print("Tentando abrir a tela de pesquisa avançada...")

    strategies = [
        (open_pol_menu, "botão #polMenu"),
        (
            lambda current_page: click_with_fallback(
                current_page.get_by_role("button", name=re.compile(r"Clique aqui para acessar o", re.IGNORECASE)),
                "atalho principal do dashboard",
                timeout=5000,
            ),
            "atalho principal do dashboard",
        ),
        (
            lambda current_page: click_with_fallback(
                current_page.locator(".casca-menu-center"),
                "área central do dashboard",
                timeout=5000,
            ),
            "área central do dashboard",
        ),
        (open_pol_menu, "botão #polMenu (nova tentativa)"),
    ]

    for action, description in strategies:
        if action(page):
            page.wait_for_timeout(1800)
            if wait_visible(promptuario, timeout=6000):
                print(f"Tela de pesquisa avançada aberta com sucesso após {description}.")
                return

    raise RuntimeError("A tela de pesquisa não ficou disponível após as tentativas de navegação.")


def wait_internacoes_table(page: Page, timeout: int = 120000) -> Frame:
    frame = page.frame(name=FRAME_NAME)
    if frame is None:
        raise RuntimeError(f"Iframe {FRAME_NAME} não encontrado.")

    rows_locator = frame.locator('#tabelaInternacoes\\:resultList_data > tr')
    rows_locator.first.wait_for(state='visible', timeout=timeout)
    return frame


def read_internacoes_rows(page: Page) -> list[dict[str, object]]:
    frame = wait_internacoes_table(page)
    rows = frame.eval_on_selector_all(
        '#tabelaInternacoes\\:resultList_data > tr',
        """
        (rows) => rows.map((tr) => ({
            dataRi: tr.getAttribute('data-ri'),
            dataRk: tr.getAttribute('data-rk'),
            cells: Array.from(tr.querySelectorAll('td')).map((td) => (td.textContent || '').trim()),
            hasDetailsLink: !!tr.querySelector('a[title="Detalhes da Internação"]'),
        }))
        """,
    )

    parsed: list[dict[str, object]] = []
    for row in rows:
        if not row.get("hasDetailsLink"):
            continue

        cells = row.get("cells") or []
        if len(cells) < 2:
            continue

        admission_start = parse_br_date(cells[0])
        if admission_start is None:
            continue

        admission_end = parse_br_date(cells[1])

        row_index_raw = row.get("dataRi")
        try:
            row_index = int(row_index_raw)
        except (TypeError, ValueError):
            row_index = len(parsed)

        parsed.append(
            {
                "rowIndex": row_index,
                "admissionKey": row.get("dataRk") or f"row-{row_index}",
                "admissionStart": admission_start,
                "admissionEnd": admission_end,
                "cells": cells,
            }
        )

    if not parsed:
        raise RuntimeError(
            "Nenhuma internação válida foi encontrada na tabela #tabelaInternacoes:resultList."
        )

    parsed.sort(key=lambda item: (item["admissionStart"], item["rowIndex"]))
    return parsed


def admission_overlaps_interval(
    admission: dict[str, object],
    requested_start: date,
    requested_end: date,
) -> bool:
    admission_start = admission["admissionStart"]
    admission_end = admission["admissionEnd"] or date.today()
    return admission_start <= requested_end and admission_end >= requested_start


def choose_target_admissions(
    admissions: list[dict[str, object]],
    requested_start: date,
    requested_end: date,
    internacao_index: int,
) -> list[dict[str, object]]:
    if internacao_index >= 0:
        if internacao_index >= len(admissions):
            raise RuntimeError(
                f"Índice manual de internação inválido: {internacao_index}. "
                f"Faixa disponível: 0 a {len(admissions) - 1}."
            )
        selected = admissions[internacao_index]
        print(
            "Modo manual ativado: usando apenas a internação "
            f"index={internacao_index} key={selected['admissionKey']}"
        )
        return [selected]

    selected = [
        admission
        for admission in admissions
        if admission_overlaps_interval(admission, requested_start, requested_end)
    ]

    if not selected:
        raise RuntimeError(
            "Nenhuma internação com interseção foi encontrada para o intervalo solicitado."
        )

    print(f"Internações selecionadas automaticamente: {len(selected)}")
    for admission in selected:
        print(
            " - key={key} | início={start} | alta={end}".format(
                key=admission["admissionKey"],
                start=admission["admissionStart"],
                end=admission["admissionEnd"] or "(sem alta)",
            )
        )

    return selected


def build_chunks_for_interval(start: date, end: date) -> list[tuple[date, date]]:
    if end < start:
        return []

    chunks: list[tuple[date, date]] = []
    cursor = start

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=MAX_CHUNK_DAYS - 1), end)
        chunks.append((cursor, chunk_end))

        if chunk_end >= end:
            break

        next_cursor = chunk_end - timedelta(days=CHUNK_OVERLAP_DAYS - 1)
        if next_cursor <= cursor:
            next_cursor = cursor + timedelta(days=1)

        cursor = next_cursor

    return chunks


def click_menu_internacoes(page: Page) -> None:
    menu_label = page.locator('.ui-treenode-label', has_text='Internações').first
    if not wait_visible(menu_label, timeout=30000):
        raise RuntimeError("Menu lateral 'Internações' não encontrado na página principal.")

    if not click_with_fallback(menu_label, "menu lateral Internações", timeout=15000):
        raise RuntimeError("Falha ao acionar o menu lateral Internações.")

    elapsed = 0
    while elapsed < REPORT_WAIT_TIMEOUT_MS:
        frame = page.frame(name=FRAME_NAME)
        if frame and 'consultarInternacoes.xhtml' in (frame.url or ''):
            if frame.locator('#tabelaInternacoes\\:resultList_data > tr').count() > 0:
                print('OK: lista de internações reaberta com sucesso.')
                return

        page.wait_for_timeout(REPORT_POLL_INTERVAL_MS)
        elapsed += REPORT_POLL_INTERVAL_MS

    raise RuntimeError("Não foi possível retornar à listagem de internações pelo menu lateral.")


def open_internacao_detail(page: Page, admission: dict[str, object]) -> None:
    frame = wait_internacoes_table(page)
    admission_key = admission["admissionKey"]

    row_locator = frame.locator(
        f'#tabelaInternacoes\\:resultList_data > tr[data-rk="{admission_key}"]'
    )

    if row_locator.count() == 0:
        row_index = admission["rowIndex"]
        row_locator = frame.locator(
            f'#tabelaInternacoes\\:resultList_data > tr[data-ri="{row_index}"]'
        )

    if row_locator.count() == 0:
        raise RuntimeError(
            f"Não foi possível localizar a internação na tabela. key={admission_key}"
        )

    details_link = row_locator.first.locator('a[title="Detalhes da Internação"]').first
    details_link.wait_for(state='visible', timeout=30000)
    details_link.click()

    elapsed = 0
    while elapsed < REPORT_WAIT_TIMEOUT_MS:
        frame = page.frame(name=FRAME_NAME)
        if frame and 'consultaDetalheInternacao.xhtml' in (frame.url or ''):
            if frame.get_by_role('button', name='Evolução').count() > 0:
                print(f"OK: detalhes da internação abertos. key={admission_key}")
                return

        page.wait_for_timeout(REPORT_POLL_INTERVAL_MS)
        elapsed += REPORT_POLL_INTERVAL_MS

    raise RuntimeError(
        f"A tela de detalhes da internação não carregou no tempo esperado. key={admission_key}"
    )


def go_back_to_detail_from_report(page: Page) -> None:
    frame = page.frame(name=FRAME_NAME)
    if frame is None:
        raise RuntimeError(f"Iframe {FRAME_NAME} não encontrado ao tentar voltar do relatório.")

    voltar_button = frame.get_by_role('button', name='Voltar').first
    if not wait_visible(voltar_button, timeout=30000):
        raise RuntimeError("Botão 'Voltar' não encontrado na tela de relatório.")

    if not click_with_fallback(voltar_button, "botão Voltar do relatório", timeout=15000):
        raise RuntimeError("Falha ao acionar o botão Voltar na tela de relatório.")

    elapsed = 0
    while elapsed < REPORT_WAIT_TIMEOUT_MS:
        frame = page.frame(name=FRAME_NAME)
        if frame and 'consultaDetalheInternacao.xhtml' in (frame.url or ''):
            if frame.get_by_role('button', name='Evolução').count() > 0:
                print('OK: retorno à tela de detalhes da internação concluído.')
                return

        page.wait_for_timeout(REPORT_POLL_INTERVAL_MS)
        elapsed += REPORT_POLL_INTERVAL_MS

    raise RuntimeError("Não foi possível voltar para a tela de detalhes da internação.")


def click_nth(locator: Locator, index: int, description: str) -> None:
    count = locator.count()
    print(f"{description}: {count} opção(ões) encontrada(s).")

    if count == 0:
        raise RuntimeError(f"Nenhuma opção encontrada para: {description}")

    if index < 0 or index >= count:
        raise RuntimeError(
            f"Índice inválido para {description}: {index}. Faixa disponível: 0 a {count - 1}."
        )

    target = locator.nth(index)
    target.wait_for(state="visible", timeout=15000)
    target.click()


def wait_for_modal_evolucao(page: Page, timeout: int = 120000) -> None:
    overlay = page.locator("#modalEvolucao_modal")

    if overlay.count() == 0:
        return

    print("Aguardando liberação do modal de evolução...")
    try:
        overlay.wait_for(state="hidden", timeout=timeout)
        print("OK: modal de evolução liberado.")
    except Exception:
        try:
            visible = overlay.is_visible()
        except Exception:
            visible = None
        print(f"Aviso: modal de evolução ainda não ficou hidden dentro do timeout. visible={visible}")


def select_order_crescente(frame, page: Page) -> None:
    result = frame.locator('#ordenacaoCrescente\\:ordenacaoCrescente\\:inputId_input').evaluate(
        """
        (select) => {
            if (!(select instanceof HTMLSelectElement)) {
                return { ok: false, reason: 'select não encontrado' };
            }

            const option = Array.from(select.options).find((item) =>
                (item.textContent || '').trim() === 'Crescente'
            );

            if (!option) {
                return {
                    ok: false,
                    reason: 'opção Crescente não encontrada',
                    options: Array.from(select.options).map((item) => ({
                        value: item.value,
                        text: (item.textContent || '').trim(),
                    })),
                };
            }

            select.value = option.value;
            select.selectedIndex = Array.from(select.options).indexOf(option);
            select.dispatchEvent(new Event('change', { bubbles: true }));

            const label = document.getElementById('ordenacaoCrescente:ordenacaoCrescente:inputId_label');
            if (label) {
                label.textContent = (option.textContent || '').trim();
            }

            return {
                ok: true,
                value: option.value,
                text: (option.textContent || '').trim(),
                label: label ? (label.textContent || '').trim() : null,
            };
        }
        """
    )

    if not result.get("ok"):
        raise RuntimeError(f"Não foi possível selecionar ordenação Crescente: {result}")

    print(f"OK: ordenação ajustada para Crescente via select oculto: {result}")
    page.wait_for_timeout(800)


def obter_pdf_url_via_viewer(page: Page) -> str | None:
    frame = page.frame(name=FRAME_NAME)
    if frame is None:
        print("Aviso: iframe frame_pol não foi encontrado para inspecionar o viewer.")
        return None

    frame_url = frame.url
    print(f"URL atual do iframe {FRAME_NAME}: {frame_url!r}")
    if not frame_url:
        return None

    parsed = urlparse(frame_url)
    if parsed.path.lower().endswith(".pdf"):
        pdf_url = urljoin(frame_url, frame_url)
        print(f"PDF identificado diretamente na URL do iframe: {pdf_url}")
        return pdf_url

    query = parse_qs(parsed.query)
    file_candidates = query.get("file", [])
    for file_candidate in file_candidates:
        decoded = unquote(file_candidate)
        absolute_pdf_url = urljoin(frame_url, decoded)
        print(f"PDF identificado pelo parâmetro file do viewer: {absolute_pdf_url}")
        return absolute_pdf_url

    iframe_src = page.locator(f'iframe[name="{FRAME_NAME}"]').get_attribute("src")
    if iframe_src:
        print(f"Atributo src do iframe {FRAME_NAME}: {iframe_src!r}")
        iframe_src_abs = urljoin(page.url, iframe_src)
        iframe_src_parsed = urlparse(iframe_src_abs)
        if iframe_src_parsed.path.lower().endswith(".pdf"):
            return iframe_src_abs

        iframe_query = parse_qs(iframe_src_parsed.query)
        file_candidates = iframe_query.get("file", [])
        for file_candidate in file_candidates:
            decoded = unquote(file_candidate)
            absolute_pdf_url = urljoin(iframe_src_abs, decoded)
            print(f"PDF identificado pelo src do iframe: {absolute_pdf_url}")
            return absolute_pdf_url

    return None


def normalize_pol_report_text(raw_text: str) -> str:
    text = PAGE_HEADER_BLOCK_RE.sub(r"\1\n\2\n\3\nEVOLUÇÃO\n", raw_text)
    text = DATETIME_WITHOUT_SECONDS_RE.sub(r"\1:00", text)
    return text


def normalize_datetime_line(value: str) -> str:
    stripped = value.strip()
    if DATETIME_LINE_RE.match(stripped) and len(stripped) == 16:
        return f"{stripped}:00"
    return stripped


def trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    return lines[start:end]


def is_evolution_end_line(value: str) -> bool:
    return bool(EVOLUTION_END_LINE_RE.match(value.strip()))


def split_evolutions_by_signature(cleaned_lines: list[str]) -> list[list[str]]:
    evolutions: list[list[str]] = []
    current: list[str] = []
    seen_first_datetime = False
    current_closed = False

    for line in cleaned_lines:
        stripped = line.strip()

        if DATETIME_LINE_RE.match(stripped):
            normalized_dt = normalize_datetime_line(stripped)

            if not seen_first_datetime:
                current = [normalized_dt]
                seen_first_datetime = True
                current_closed = False
                continue

            if current_closed:
                candidate = trim_blank_edges(current)
                if candidate:
                    evolutions.append(candidate)
                current = [normalized_dt]
                current_closed = False
                continue

            if current and current[0].strip() == normalized_dt:
                # Quebra de página de evolução longa: ignora data/hora repetida.
                continue

            # Data/hora isolada sem marcador de fechamento imediatamente anterior: ignora como ruído.
            continue

        if not seen_first_datetime:
            continue

        if current_closed:
            # Após linha final "Elaborado ... em DD/MM/YYYY HH:MM", ignora cauda até a próxima data.
            continue

        current.append(stripped)

        if stripped and is_evolution_end_line(stripped):
            current_closed = True

    candidate = trim_blank_edges(current)
    if candidate:
        evolutions.append(candidate)

    return evolutions


def extract_initial_datetime(evolution_lines: list[str]) -> datetime:
    for line in evolution_lines:
        stripped = normalize_datetime_line(line)
        if DATETIME_LINE_RE.match(stripped):
            return datetime.strptime(stripped, "%d/%m/%Y %H:%M:%S")

    raise RuntimeError("Não foi possível localizar a data/hora inicial de uma evolução.")


def build_evolutions_output(evolutions: list[list[str]]) -> str:
    blocks: list[str] = []

    for index, evolution_lines in enumerate(evolutions, start=1):
        body = "\n".join(trim_blank_edges(evolution_lines)).strip()
        blocks.append(f"===== EVOLUÇÃO {index} =====\n{body}")

    return "\n\n".join(blocks).strip() + "\n"


def find_signature_line(evolution_lines: list[str]) -> str | None:
    for line in reversed(evolution_lines):
        if is_evolution_end_line(line):
            return line.strip()
    return None


def classify_evolution_type(signature_line: str | None, content: str) -> str:
    signature_lowered = (signature_line or "").casefold()
    content_lowered = content.casefold()

    if "crm" in signature_lowered:
        return "medical"
    if "coren" in signature_lowered:
        return "nursing"
    if "crefito" in signature_lowered:
        return "phisiotherapy"
    if "crn" in signature_lowered:
        return "nutrition"
    if "crefono" in signature_lowered:
        return "speech_therapy"
    if "cro" in signature_lowered:
        return "dentistry"

    if "odontologia" in content_lowered or "odontolog" in content_lowered:
        return "dentistry"

    return "other"


def extract_created_by(signature_line: str | None) -> str:
    if not signature_line:
        return ""

    match = SIGNATURE_AUTHOR_RE.search(signature_line)
    if match:
        return match.group(1).strip(" ,-:")

    fallback = re.search(r"\bpor[:\s]+(.+?)\s+em:?\s*\d{2}/\d{2}/\d{4}", signature_line, re.IGNORECASE)
    if fallback:
        return fallback.group(1).strip(" ,-:")

    return ""


def build_evolution_content(evolution_lines: list[str], signature_line: str | None) -> str:
    lines = trim_blank_edges(evolution_lines)

    if lines and DATETIME_LINE_RE.match(normalize_datetime_line(lines[0])):
        lines = lines[1:]

    if signature_line and lines and lines[-1].strip() == signature_line:
        lines = lines[:-1]

    return "\n".join(trim_blank_edges(lines)).strip()


def extract_signature_datetime(signature_line: str | None) -> str:
    if not signature_line:
        return ""

    match = SIGNATURE_DATETIME_RE.search(signature_line)
    if not match:
        return ""

    raw_value = normalize_datetime_line(match.group(1).strip())
    try:
        return datetime.strptime(raw_value, "%d/%m/%Y %H:%M:%S").isoformat()
    except ValueError:
        return ""


def extract_confidence(evolution_type: str) -> str:
    return (
        "high"
        if evolution_type
        in {"medical", "nursing", "phisiotherapy", "nutrition", "speech_therapy", "dentistry"}
        else "low"
    )


def build_evolutions_json_payload(evolutions: list[list[str]]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []

    for source_index, evolution in enumerate(evolutions, start=1):
        signature_line = find_signature_line(evolution)
        created_at = extract_initial_datetime(evolution).isoformat()
        signed_at = extract_signature_datetime(signature_line)
        created_by = extract_created_by(signature_line)
        content = build_evolution_content(evolution, signature_line)
        evolution_type = classify_evolution_type(signature_line, content)
        confidence = extract_confidence(evolution_type)

        payload.append(
            {
                "createdAt": created_at,
                "signedAt": signed_at,
                "content": content,
                "createdBy": created_by,
                "type": evolution_type,
                "sourceIndex": source_index,
                "confidence": confidence,
                "signatureLine": signature_line or "",
            }
        )

    payload.sort(key=lambda item: (str(item["createdAt"]), int(item["sourceIndex"])))
    return payload


def salvar_evolucoes_json(payload: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extrair_e_processar_pdf_pol(
    pdf_path: Path,
    txt_output_path: Path,
    normalized_txt_output_path: Path,
    processed_txt_output_path: Path,
    sorted_txt_output_path: Path,
    json_output_path: Path,
) -> None:
    print(f"Extraindo texto do PDF salvo em: {pdf_path}")
    raw_text = extrair_texto_do_pdf(pdf_path)
    normalized_text = normalize_pol_report_text(raw_text)

    salvar_texto_extraido(raw_text, txt_output_path)
    salvar_texto_extraido(normalized_text, normalized_txt_output_path)

    cleaned_lines = remove_page_artifacts(normalized_text)
    evolutions = split_evolutions_by_signature(cleaned_lines)

    if not evolutions:
        raise RuntimeError("Nenhuma evolução foi identificada após a limpeza do texto extraído.")

    sorted_evolutions = sorted(evolutions, key=extract_initial_datetime)

    processed_text = build_evolutions_output(evolutions)
    sorted_text = build_evolutions_output(sorted_evolutions)
    json_payload = build_evolutions_json_payload(evolutions)

    salvar_texto_extraido(processed_text, processed_txt_output_path)
    salvar_texto_extraido(sorted_text, sorted_txt_output_path)
    salvar_evolucoes_json(json_payload, json_output_path)

    end_marker_lines = sum(1 for line in cleaned_lines if is_evolution_end_line(line))

    print(f"TXT bruto salvo em: {txt_output_path}")
    print(f"TXT normalizado salvo em: {normalized_txt_output_path}")
    print(f"TXT processado salvo em: {processed_txt_output_path}")
    print(f"TXT ordenado salvo em: {sorted_txt_output_path}")
    print(f"JSON de evoluções salvo em: {json_output_path}")
    print(f"Linhas após limpeza: {len(cleaned_lines)}")
    print(f"Marcadores de fim ('Elaborado ... em DD/MM/YYYY HH:MM'): {end_marker_lines}")
    print(f"Evoluções identificadas: {len(evolutions)}")


def resolve_pdf_url(page: Page) -> str:
    frame_locator = page.frame_locator(f'iframe[name="{FRAME_NAME}"]')

    try:
        return obter_pdf_url_do_object(frame_locator, page, page.url)
    except Exception as object_error:
        print(
            "Aviso: não foi possível obter a URL do PDF via <object>. "
            "Tentando descobrir a URL pelo viewer do iframe..."
        )
        print(f"Motivo original: {object_error}")

    viewer_pdf_url = obter_pdf_url_via_viewer(page)
    if viewer_pdf_url:
        return viewer_pdf_url

    raise RuntimeError(
        "O PDF não foi localizado nem via <object> nem via URL do viewer do iframe. "
        "Revise os artefatos de debug para confirmar como essa rota renderiza o relatório."
    )


def click_visualizar_relatorio(frame, page: Page) -> None:
    button = frame.locator('#bt_UltimosQuinzedias\\:button')
    button.wait_for(state='visible', timeout=30000)

    try:
        button.click(timeout=10000)
        print('OK: botão Visualizar do modal acionado com clique padrão')
    except Exception as click_error:
        print(f"Aviso: clique padrão no botão Visualizar falhou: {click_error}")
        try:
            button.click(timeout=10000, force=True)
            print('OK: botão Visualizar do modal acionado com force=True')
        except Exception as force_error:
            print(f"Aviso: clique forçado no botão Visualizar falhou: {force_error}")
            button.evaluate('(element) => element.click()')
            print('OK: botão Visualizar do modal acionado com DOM click')

    page.wait_for_timeout(1500)


def open_report_for_interval(page: Page, chunk_start: date, chunk_end: date) -> Frame | None:
    frame_locator = page.frame_locator(f'iframe[name="{FRAME_NAME}"]')

    botao_evolucao = frame_locator.get_by_role('button', name='Evolução')
    botao_evolucao.first.wait_for(state='visible', timeout=30000)

    try:
        if botao_evolucao.first.is_disabled():
            print("Aviso: botão Evolução está desabilitado para esta internação/período.")
            return None
    except Exception:
        pass

    if not click_with_fallback(botao_evolucao, 'botão Evolução', timeout=15000):
        raise RuntimeError("Falha ao acionar o botão Evolução na tela de detalhes.")
    page.wait_for_timeout(1000)

    wait_for_modal_evolucao(page)

    inicio_text = format_br_date(chunk_start)
    fim_text = format_br_date(chunk_end)

    print(f"Aplicando intervalo do chunk: {inicio_text} até {fim_text}")

    data_inicio = frame_locator.locator('[id="dataInicio:dataInicio:inputId_input"]')
    data_inicio.first.wait_for(state='visible', timeout=30000)
    data_inicio.first.click()
    data_inicio.first.fill(inicio_text)

    data_fim = frame_locator.locator('[id="dataFim:dataFim:inputId_input"]')
    data_fim.first.wait_for(state='visible', timeout=30000)
    data_fim.first.click()
    data_fim.first.fill(fim_text)

    wait_for_modal_evolucao(page)
    select_order_crescente(frame_locator, page)

    wait_for_modal_evolucao(page)
    click_visualizar_relatorio(frame_locator, page)

    try:
        return wait_for_report_page(page)
    except RuntimeError as error:
        frame = page.frame(name=FRAME_NAME)
        current_url = frame.url if frame else ""
        if 'consultaDetalheInternacao.xhtml' in (current_url or ''):
            print(
                "Aviso: relatório não foi gerado para este chunk. "
                f"intervalo={inicio_text} até {fim_text}"
            )
            return None
        raise error


def wait_for_report_page(page: Page) -> Frame:
    elapsed = 0

    while elapsed < REPORT_WAIT_TIMEOUT_MS:
        frame = page.frame(name=FRAME_NAME)
        if frame is None:
            raise RuntimeError(f'Iframe {FRAME_NAME} não encontrado durante a espera pelo relatório.')

        frame_url = frame.url or ''
        print(f'Aguardando relatório... {elapsed // 1000}s · frame={frame_url}')

        if 'relatorioAnaEvoInternacaoPdf.xhtml' in frame_url:
            try:
                has_print_links = frame.locator('#printLinks').count() > 0
                has_back_button = frame.get_by_role('button', name='Voltar').count() > 0
            except Exception:
                has_print_links = False
                has_back_button = False

            if has_print_links and has_back_button:
                print('OK: tela de relatório detectada e estabilizada.')
                return frame

        page.wait_for_timeout(REPORT_POLL_INTERVAL_MS)
        elapsed += REPORT_POLL_INTERVAL_MS

    raise RuntimeError(
        'A tela de relatório não ficou disponível dentro do tempo limite. '
        'O sistema fonte pode ainda estar processando o relatório.'
    )


def baixar_pdf_via_formulario_relatorio(
    context: BrowserContext,
    report_frame: Frame,
    output_path: Path,
    debug_output_path: Path,
) -> bool:
    html_content = report_frame.content()

    action_match = re.search(r'<form id="printLinks"[^>]*action="([^"]+)"', html_content)
    viewstate_match = re.search(
        r'<form id="printLinks".*?name="javax.faces.ViewState"[^>]*value="([^"]+)"',
        html_content,
        re.S,
    )

    if not action_match or not viewstate_match:
        print('Aviso: form printLinks não encontrado na tela de relatório.')
        return False

    action_url = html.unescape(action_match.group(1))
    viewstate = html.unescape(viewstate_match.group(1))
    absolute_action_url = urljoin(report_frame.url, action_url)

    print(f'Tentando baixar PDF via form printLinks: {absolute_action_url}')

    response = context.request.post(
        absolute_action_url,
        form={
            'printLinks': 'printLinks',
            'downloadLinkAjax': 'downloadLinkAjax',
            'javax.faces.ViewState': viewstate,
        },
        timeout=REPORT_DOWNLOAD_TIMEOUT_MS,
    )

    if not response.ok:
        raise RuntimeError(
            f'Falha ao baixar PDF via form printLinks. HTTP {response.status}.'
        )

    body = response.body()
    content_type = (response.headers.get('content-type') or '').lower()
    content_disposition = response.headers.get('content-disposition') or ''

    print(f'Content-Type via printLinks: {content_type}')
    print(f'Content-Disposition via printLinks: {content_disposition}')
    print(f'Tamanho retornado via printLinks: {len(body)} bytes')

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if body.startswith(b'%PDF-'):
        output_path.write_bytes(body)
        print(f'PDF salvo com sucesso em: {output_path}')
        return True

    debug_output_path.parent.mkdir(parents=True, exist_ok=True)
    debug_output_path.write_bytes(body)
    print(
        'Aviso: o download via printLinks não retornou um PDF válido. '
        f'Conteúdo salvo para inspeção em: {debug_output_path}'
    )
    return False


def download_pdf_from_report(
    page: Page,
    context: BrowserContext,
    report_frame: Frame,
    pdf_output_path: Path,
    debug_output_path: Path,
) -> None:
    print(f"Tentando localizar a URL do PDF para salvar em {pdf_output_path}...")

    try:
        pdf_url = resolve_pdf_url(page)
        baixar_pdf_autenticado(context, pdf_url, pdf_output_path, debug_output_path)
        print(f"PDF salvo com sucesso em: {pdf_output_path}")
        return
    except Exception as pdf_error:
        print(
            'Aviso: extração direta da URL do PDF falhou nesta rota. '
            'Tentando download pelo formulário interno do relatório...'
        )
        print(f'Motivo original: {pdf_error}')

    if not baixar_pdf_via_formulario_relatorio(
        context,
        report_frame,
        pdf_output_path,
        debug_output_path,
    ):
        raise RuntimeError("Não foi possível baixar o PDF do relatório por nenhuma estratégia.")


def build_chunk_artifact_path(base_path: Path, admission_idx: int, chunk_idx: int) -> Path:
    return base_path.with_name(
        f"{base_path.stem}-adm{admission_idx + 1:02d}-chunk{chunk_idx + 1:02d}{base_path.suffix}"
    )


def enrich_payload_with_metadata(
    payload: list[dict[str, object]],
    admission: dict[str, object],
    chunk_start: date,
    chunk_end: date,
    requested_start: date,
    requested_end: date,
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []

    for item in payload:
        item_copy = dict(item)
        item_copy["admissionKey"] = admission["admissionKey"]
        item_copy["admissionRowIndex"] = int(admission["rowIndex"])
        item_copy["admissionStart"] = format_iso_date(admission["admissionStart"])
        item_copy["admissionEnd"] = format_iso_date(admission["admissionEnd"])
        item_copy["chunkStart"] = format_iso_date(chunk_start)
        item_copy["chunkEnd"] = format_iso_date(chunk_end)
        item_copy["requestedStart"] = format_iso_date(requested_start)
        item_copy["requestedEnd"] = format_iso_date(requested_end)
        enriched.append(item_copy)

    return enriched


def dedupe_evolutions(records: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    deduped: list[dict[str, object]] = []
    index_by_key: dict[tuple[str, str, str], int] = {}

    for record in records:
        admission_key = str(record.get("admissionKey") or "")
        created_at = str(record.get("createdAt") or "")
        signature_key = normalize_signature_key(str(record.get("signatureLine") or ""))

        if not signature_key:
            content = str(record.get("content") or "")
            signature_key = hashlib.sha1(content.encode("utf-8")).hexdigest()

        key = (admission_key, created_at, signature_key)

        if key not in index_by_key:
            index_by_key[key] = len(deduped)
            deduped.append(record)
            continue

        existing_index = index_by_key[key]
        existing = deduped[existing_index]

        if len(str(record.get("content") or "")) > len(str(existing.get("content") or "")):
            deduped[existing_index] = record

    removed_count = len(records) - len(deduped)
    return deduped, removed_count


def sort_records_chronologically(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        records,
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("admissionStart") or ""),
            int(item.get("admissionRowIndex") or 0),
            int(item.get("sourceIndex") or 0),
        ),
    )


def build_text_blocks_from_records(records: list[dict[str, object]]) -> str:
    blocks: list[str] = []

    for index, record in enumerate(records, start=1):
        created_at = str(record.get("createdAt") or "")
        content = str(record.get("content") or "").strip()
        signature_line = str(record.get("signatureLine") or "").strip()

        body_lines: list[str] = []
        if created_at:
            body_lines.append(created_at.replace("T", " "))
        if content:
            body_lines.append(content)
        if signature_line:
            body_lines.append(signature_line)

        blocks.append(f"===== EVOLUÇÃO {index} =====\n" + "\n".join(body_lines).strip())

    return "\n\n".join(blocks).strip() + "\n" if blocks else ""


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    patient_record: str,
    start_date: str,
    end_date: str,
    internacao_index: int,
    output_path: Path,
    debug_output_path: Path,
    txt_output_path: Path,
    normalized_txt_output_path: Path,
    processed_txt_output_path: Path,
    sorted_txt_output_path: Path,
    json_output_path: Path,
    headless: bool,
) -> None:
    patient_record = normalize_patient_record(patient_record)
    requested_start = parse_cli_date(start_date)
    requested_end = parse_cli_date(end_date)

    if requested_end < requested_start:
        raise RuntimeError(
            f"Intervalo inválido: início {requested_start} é maior que fim {requested_end}."
        )

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            print("Abrindo navegador...")
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            print("Acessando sistema fonte...")
            page.goto(source_system_url, timeout=DEFAULT_TIMEOUT_MS)

            print("Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            ensure_search_screen(page)

            print(f"Pesquisando prontuário {patient_record}...")
            promptuario_input = page.locator("#prontuarioInput")
            promptuario_input.wait_for(state="visible", timeout=15000)
            promptuario_input.click()
            promptuario_input.fill(patient_record)

            pesquisa_avancada = page.get_by_role("link", name="Pesquisa Avançada")
            pesquisa_avancada.wait_for(state="visible", timeout=15000)
            pesquisa_avancada.click()
            page.wait_for_timeout(1200)

            internacoes = page.get_by_text("Internações", exact=True)
            internacoes.wait_for(state="visible", timeout=15000)
            internacoes.click()
            page.wait_for_timeout(1500)

            all_admissions = read_internacoes_rows(page)
            target_admissions = choose_target_admissions(
                all_admissions,
                requested_start,
                requested_end,
                internacao_index,
            )

            collected_records: list[dict[str, object]] = []
            merged_raw_text_parts: list[str] = []
            merged_normalized_text_parts: list[str] = []

            for admission_idx, planned_admission in enumerate(target_admissions):
                if admission_idx > 0:
                    click_menu_internacoes(page)

                current_rows = read_internacoes_rows(page)
                current_admission = next(
                    (
                        item
                        for item in current_rows
                        if item["admissionKey"] == planned_admission["admissionKey"]
                    ),
                    None,
                )

                if current_admission is None:
                    current_admission = next(
                        (
                            item
                            for item in current_rows
                            if item["rowIndex"] == planned_admission["rowIndex"]
                            and item["admissionStart"] == planned_admission["admissionStart"]
                            and item["admissionEnd"] == planned_admission["admissionEnd"]
                        ),
                        None,
                    )

                if current_admission is None:
                    raise RuntimeError(
                        "Não foi possível reencontrar a internação na tabela ao retomar o fluxo. "
                        f"key={planned_admission['admissionKey']}"
                    )

                admission_start = current_admission["admissionStart"]
                admission_end = current_admission["admissionEnd"] or requested_end

                effective_start = max(requested_start, admission_start)
                effective_end = min(requested_end, admission_end)

                if effective_end < effective_start:
                    print(
                        "Aviso: internação sem interseção efetiva após recorte. "
                        f"key={current_admission['admissionKey']}"
                    )
                    continue

                chunks = build_chunks_for_interval(effective_start, effective_end)
                print(
                    f"Internação {admission_idx + 1}/{len(target_admissions)} | "
                    f"key={current_admission['admissionKey']} | chunks={len(chunks)}"
                )

                open_internacao_detail(page, current_admission)

                last_chunk_had_report = False

                for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
                    if chunk_idx > 0 and last_chunk_had_report:
                        go_back_to_detail_from_report(page)

                    report_frame = open_report_for_interval(page, chunk_start, chunk_end)
                    if report_frame is None:
                        last_chunk_had_report = False
                        continue

                    chunk_pdf_path = build_chunk_artifact_path(output_path, admission_idx, chunk_idx)
                    chunk_debug_path = build_chunk_artifact_path(debug_output_path, admission_idx, chunk_idx)
                    chunk_txt_path = build_chunk_artifact_path(txt_output_path, admission_idx, chunk_idx)
                    chunk_norm_path = build_chunk_artifact_path(
                        normalized_txt_output_path,
                        admission_idx,
                        chunk_idx,
                    )
                    chunk_processed_path = build_chunk_artifact_path(
                        processed_txt_output_path,
                        admission_idx,
                        chunk_idx,
                    )
                    chunk_sorted_path = build_chunk_artifact_path(
                        sorted_txt_output_path,
                        admission_idx,
                        chunk_idx,
                    )
                    chunk_json_path = build_chunk_artifact_path(json_output_path, admission_idx, chunk_idx)

                    download_pdf_from_report(
                        page,
                        context,
                        report_frame,
                        chunk_pdf_path,
                        chunk_debug_path,
                    )

                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if chunk_pdf_path.exists():
                        output_path.write_bytes(chunk_pdf_path.read_bytes())

                    extrair_e_processar_pdf_pol(
                        chunk_pdf_path,
                        chunk_txt_path,
                        chunk_norm_path,
                        chunk_processed_path,
                        chunk_sorted_path,
                        chunk_json_path,
                    )

                    if chunk_txt_path.exists():
                        merged_raw_text_parts.append(chunk_txt_path.read_text(encoding="utf-8"))
                    if chunk_norm_path.exists():
                        merged_normalized_text_parts.append(chunk_norm_path.read_text(encoding="utf-8"))

                    chunk_payload = json.loads(chunk_json_path.read_text(encoding="utf-8"))
                    if not isinstance(chunk_payload, list):
                        raise RuntimeError(
                            f"Payload inválido no JSON do chunk: {chunk_json_path}"
                        )

                    enriched_payload = enrich_payload_with_metadata(
                        chunk_payload,
                        current_admission,
                        chunk_start,
                        chunk_end,
                        requested_start,
                        requested_end,
                    )
                    collected_records.extend(enriched_payload)
                    last_chunk_had_report = True

            if not collected_records:
                raise RuntimeError("Nenhuma evolução foi coletada para o intervalo solicitado.")

            deduped_records, removed_count = dedupe_evolutions(collected_records)
            sorted_records = sort_records_chronologically(deduped_records)

            salvar_evolucoes_json(sorted_records, json_output_path)

            if merged_raw_text_parts:
                salvar_texto_extraido(
                    "\n\n".join(part.strip() for part in merged_raw_text_parts if part.strip()).strip()
                    + "\n",
                    txt_output_path,
                )
            if merged_normalized_text_parts:
                salvar_texto_extraido(
                    "\n\n".join(
                        part.strip() for part in merged_normalized_text_parts if part.strip()
                    ).strip()
                    + "\n",
                    normalized_txt_output_path,
                )

            salvar_texto_extraido(
                build_text_blocks_from_records(deduped_records),
                processed_txt_output_path,
            )
            salvar_texto_extraido(
                build_text_blocks_from_records(sorted_records),
                sorted_txt_output_path,
            )

            print(f"Registros coletados (antes da deduplicação): {len(collected_records)}")
            print(f"Registros após deduplicação: {len(sorted_records)}")
            print(f"Duplicados removidos: {removed_count}")
            print(f"JSON consolidado salvo em: {json_output_path}")
        except Exception:
            if page is not None:
                salvar_debug(page)
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def main() -> None:
    load_dotenv()
    args = parse_args()

    source_system_url = required_env("SOURCE_SYSTEM_URL")
    username = required_env("SOURCE_SYSTEM_USERNAME")
    password = required_env("SOURCE_SYSTEM_PASSWORD")

    run(
        source_system_url=source_system_url,
        username=username,
        password=password,
        patient_record=args.patient_record,
        start_date=args.start_date,
        end_date=args.end_date,
        internacao_index=args.internacao_index,
        output_path=args.output,
        debug_output_path=args.debug_output,
        txt_output_path=args.txt_output,
        normalized_txt_output_path=args.normalized_txt_output,
        processed_txt_output_path=args.processed_output,
        sorted_txt_output_path=args.sorted_output,
        json_output_path=args.json_output,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
