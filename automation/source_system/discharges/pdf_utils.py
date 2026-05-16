"""Shared PDF parsing utilities for discharge reports."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

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
    """Agrupa palavras por bandas de coordenada X e extrai pacientes."""
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
