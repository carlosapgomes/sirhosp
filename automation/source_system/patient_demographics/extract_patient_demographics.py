"""Extract patient demographic data from source system (AGHU/TASY).

Follows the same login + navigation flow as path2.py, but instead of
clicking "Internações" in the POL menu, clicks "Dados do Paciente"
and scrapes the "Cadastro" tab fields.

Usage:
    python extract_patient_demographics.py --patient-record 1234567 [--headless]

Environment variables (required):
    SOURCE_SYSTEM_URL
    SOURCE_SYSTEM_USERNAME
    SOURCE_SYSTEM_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import Frame, Page, sync_playwright

# ---------------------------------------------------------------------------
# Reuse shared helpers from the medical_evolution connector
# ---------------------------------------------------------------------------

# Add parent directory so we can import from the sibling package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "medical_evolution"))

from source_system import (  # noqa: E402
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    fechar_dialogos_iniciais,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = DEFAULT_TIMEOUT_MS
PAUSA_MS = 1500
FRAME_NAME = "frame_pol"


# ---------------------------------------------------------------------------
# Helper: env validation
# ---------------------------------------------------------------------------


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


# ---------------------------------------------------------------------------
# Helper: patient record normalization (same as path2.py)
# ---------------------------------------------------------------------------


def normalize_patient_record(value: str) -> str:
    digits_only = re.sub(r"\D", "", value)
    return digits_only or value.strip()


# ---------------------------------------------------------------------------
# Helper: wait_visible / click_with_fallback (same as path2.py)
# ---------------------------------------------------------------------------


def wait_visible(locator, timeout: int = 5000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_with_fallback(locator, description: str, timeout: int = 5000) -> bool:
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


# ---------------------------------------------------------------------------
# Navigation helpers (adapted from path2.py)
# ---------------------------------------------------------------------------


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
                current_page.get_by_role(
                    "button",
                    name=re.compile(r"Clique aqui para acessar o", re.IGNORECASE),
                ),
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
                print(f"Tela de pesquisa aberta após {description}.")
                return

    raise RuntimeError("A tela de pesquisa não ficou disponível após as tentativas de navegação.")


# ---------------------------------------------------------------------------
# Core: click "Dados do Paciente" in the POL tree menu
# ---------------------------------------------------------------------------


def click_dados_do_paciente(page: Page) -> None:
    """Click 'Dados do Paciente' leaf node in the POL tree menu.

    The element is a tree leaf with label text 'Dados do Paciente'
    inside the POL accordion tree. We locate it by its span label text.
    """
    print("Procurando 'Dados do Paciente' no menu POL...")

    # Strategy 1: locate by the tree node label text
    dados_locator = page.locator(
        "#accordionPOL .ui-treenode-label span",
        has_text=re.compile(r"Dados do Paciente", re.IGNORECASE),
    )

    if not wait_visible(dados_locator, timeout=10000):
        # Strategy 2: broader search in the tree
        dados_locator = page.locator(
            "#accordionPOL span",
            has_text=re.compile(r"^Dados do Paciente$", re.IGNORECASE),
        )

    if not wait_visible(dados_locator, timeout=5000):
        raise RuntimeError(
            "Não foi possível localizar 'Dados do Paciente' no menu lateral POL."
        )

    # Click the label — the parent .ui-treenode-content handles the click event
    click_with_fallback(dados_locator.first, "'Dados do Paciente' no menu POL")

    page.wait_for_timeout(PAUSA_MS)


# ---------------------------------------------------------------------------
# Core: extract demographic fields from the Cadastro tab
# ---------------------------------------------------------------------------

# Mapping of {output_key: (css_selector, label_for_logging)}
# Each selector targets the <input> element whose `value` attribute holds the data.
DEMOGRAPHIC_FIELDS = {
    "prontuario": ("#prontuario\\:prontuario\\:inputId", "Prontuário"),
    "nome": ("#nome\\:nome\\:inputId", "Nome"),
    "nome_social": ("#nomeSocial\\:nomeSocial\\:inputId", "Nome Social"),
    "sexo": ("#sexo\\:sexo\\:inputId", "Sexo"),
    "genero": ("#genero\\:genero\\:inputId", "Gênero"),
    "nome_mae": ("#nome_mae\\:nome_mae\\:inputId", "Nome da Mãe"),
    "data_nascimento": (
        "#idFieldDataNascimento\\:dataDataNascimento_input",
        "Data de Nascimento",
    ),
    "nome_pai": ("#nome_pai\\:nome_pai\\:inputId", "Nome do Pai"),
    "raca_cor": ("#cor\\:cor\\:inputId", "Raça/Cor"),
    "naturalidade": ("#naturalidade\\:naturalidade\\:inputId", "Naturalidade"),
    "nacionalidade": (
        "#nacionalidade\\:nacionalidade\\:inputId",
        "Nacionalidade",
    ),
    "estado_civil": (
        "#estadoCivil\\:estadoCivil\\:inputId",
        "Estado Civil",
    ),
    "profissao": ("#profissao\\:profissao\\:inputId", "Profissão"),
    "grau_instrucao": (
        "#grauInstrucao\\:grauInstrucao\\:inputId",
        "Grau de Instrução",
    ),
    "ddd_fone_residencial": (
        "#ddd_fone_residencial\\:ddd_fone_residencial\\:inputId",
        "DDD Residencial",
    ),
    "fone_residencial": (
        "#foneResidencial\\:foneResidencial\\:inputId",
        "Telefone Residencial",
    ),
    "ddd_fone_celular": (
        "#ddd_fone_celular\\:ddd_fone_celular\\:inputId",
        "DDD Celular",
    ),
    "fone_celular": (
        "#foneCelular\\:foneCelular\\:inputId",
        "Telefone Celular",
    ),
    "ddd_fone_recado": (
        "#ddd_fone_recado\\:ddd_fone_recado\\:inputId",
        "DDD Recado",
    ),
    "fone_recado": (
        "#foneRecado\\:foneRecado\\:inputId",
        "Telefone Recado",
    ),
    "cns": ("#nroCartaoSaude\\:nroCartaoSaude\\:inputId", "Número CNS"),
    "equipe": ("#nomeEquipe\\:nomeEquipe\\:inputId", "Equipe"),
    "medico_responsavel": (
        "#nomeResponsavel\\:nomeResponsavel\\:inputId",
        "Médico Responsável",
    ),
    # Address fields
    "logradouro": ("#logradouro\\:logradouro\\:inputId", "Logradouro"),
    "numero": ("#numero\\:numero\\:inputId", "Número"),
    "complemento": ("#complemento\\:complemento\\:inputId", "Complemento"),
    "bairro": ("#bairro\\:bairro\\:inputId", "Bairro"),
    "cep": ("#cep\\:cep\\:inputId", "CEP"),
    "cidade": ("#cidade\\:cidade\\:inputId", "Município"),
    "uf": ("#uf\\:uf\\:inputId", "UF"),
    # Documents
    "cpf": ("#cpf\\:cpf\\:inputId", "CPF"),
}


def _wait_for_frame(page: Page, timeout: int = 15000) -> Frame:
    """Wait for the POL iframe to appear and return it."""
    print(f"Aguardando iframe '{FRAME_NAME}'...")
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        frame = page.frame(name=FRAME_NAME)
        if frame is not None:
            try:
                # Wait for some content inside the frame
                frame.wait_for_load_state("domcontentloaded", timeout=5000)
                print(f"OK: iframe '{FRAME_NAME}' disponível.")
                return frame
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise RuntimeError(
        f"Iframe '{FRAME_NAME}' não ficou disponível em {timeout}ms."
    )


def _read_input_value(frame: Frame, selector: str, label: str) -> str:
    """Read the value of an input field inside the frame, returning empty string if not found."""
    locator = frame.locator(selector)
    try:
        if wait_visible(locator, timeout=3000):
            value = locator.first.input_value(timeout=3000)
            return (value or "").strip()
    except Exception as exc:
        print(f"  Aviso: não foi possível ler '{label}' ({selector}): {exc}")
    return ""


def extract_demographics(page: Page) -> dict[str, Any]:
    """Extract all demographic fields from the Cadastro tab.

    The content loads inside iframe frame_pol. We locate the frame,
    wait for the Cadastro tab to appear, then read each field.

    Returns a dict with field keys and their string values.
    Dates are left in source format (DD/MM/YYYY) for the caller to parse.
    """
    # Wait for the iframe to load after clicking "Dados do Paciente"
    frame = _wait_for_frame(page)

    print("Aguardando aba Cadastro carregar no iframe...")

    # Wait for the cadastro tab panel to be visible inside the frame
    cadastro_tab = frame.locator("#aba_cadastro")
    if not wait_visible(cadastro_tab, timeout=15000):
        # Debug: dump frame content for diagnosis
        try:
            frame_url = frame.url
            print(f"  Debug: frame URL = {frame_url}")
            frame_content = frame.content()
            debug_path = Path("downloads/frame_cadastro.debug.html")
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(frame_content, encoding="utf-8")
            print(f"  Debug: conteúdo do iframe salvo em {debug_path}")
        except Exception as dbg_err:
            print(f"  Debug: falha ao capturar conteúdo do iframe: {dbg_err}")
        raise RuntimeError(
            "A aba 'Cadastro' não ficou visível no iframe após clicar em 'Dados do Paciente'."
        )

    # Small pause to ensure all fields are rendered
    page.wait_for_timeout(PAUSA_MS)

    result: dict[str, Any] = {}

    for field_key, (selector, label) in DEMOGRAPHIC_FIELDS.items():
        value = _read_input_value(frame, selector, label)
        result[field_key] = value
        if value:
            print(f"  ✅ {label}: {value}")
        else:
            print(f"  ⬜ {label}: (vazio)")

    return result


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------


def parse_br_date_to_iso(value: str) -> str | None:
    """Convert DD/MM/YYYY to YYYY-MM-DD, or return None if unparseable."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), "%d/%m/%Y")
        return dt.date().isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    patient_record: str,
    headless: bool = False,
) -> dict[str, Any]:
    """Full extraction flow: login → search patient → click Dados do Paciente → scrape.

    Returns the demographics dict.
    """
    patient_record = normalize_patient_record(patient_record)

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
            context = browser.new_context(
                ignore_https_errors=True,
                accept_downloads=True,
            )
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT)

            # --- Login ---
            print("Acessando sistema fonte...")
            page.goto(source_system_url, timeout=DEFAULT_TIMEOUT)

            print("Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            # --- Navigate to search screen ---
            ensure_search_screen(page)

            # --- Search patient ---
            print(f"Pesquisando prontuário {patient_record}...")
            promptuario_input = page.locator("#prontuarioInput")
            promptuario_input.wait_for(state="visible", timeout=15000)
            promptuario_input.click()
            promptuario_input.fill(patient_record)

            pesquisa_avancada = page.get_by_role("link", name="Pesquisa Avançada")
            pesquisa_avancada.wait_for(state="visible", timeout=15000)
            pesquisa_avancada.click()
            page.wait_for_timeout(1200)

            # --- Click "Dados do Paciente" ---
            click_dados_do_paciente(page)

            # --- Extract demographics ---
            demographics = extract_demographics(page)

            # Add metadata
            demographics["_meta"] = {
                "patient_record": patient_record,
                "extracted_at": datetime.now().isoformat(),
                "source_system": "aghu",
            }

            return demographics

        except Exception:
            if page is not None:
                try:
                    debug_path = Path("downloads/patient_demographics.debug.html")
                    debug_path.parent.mkdir(parents=True, exist_ok=True)
                    debug_path.write_text(page.content(), encoding="utf-8")
                    print(f"Debug HTML salvo em: {debug_path}")
                except Exception as save_err:
                    print(f"Aviso: falha ao salvar debug HTML: {save_err}")
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            playwright.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai dados demográficos de um paciente do sistema fonte (AGHU).",
    )
    parser.add_argument(
        "--patient-record",
        type=str,
        required=True,
        help="Registro/prontuário do paciente (ex: 1234567).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Executar Playwright em modo headless (sem interface gráfica).",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default="",
        help="Caminho para salvar o resultado em JSON (opcional).",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()

    args = parse_args()

    source_system_url = required_env("SOURCE_SYSTEM_URL")
    username = required_env("SOURCE_SYSTEM_USERNAME")
    password = required_env("SOURCE_SYSTEM_PASSWORD")

    demographics = run(
        source_system_url=source_system_url,
        username=username,
        password=password,
        patient_record=args.patient_record,
        headless=args.headless,
    )

    # --- Print results ---
    print("\n" + "=" * 60)
    print("DADOS DEMOGRÁFICOS EXTRAÍDOS")
    print("=" * 60)

    meta = demographics.pop("_meta", {})
    print(f"Prontuário: {meta.get('patient_record', '—')}")
    print(f"Extraído em: {meta.get('extracted_at', '—')}")
    print("-" * 60)

    # Group for display
    core_fields = [
        "prontuario", "nome", "nome_social", "sexo", "genero",
        "data_nascimento", "nome_mae", "nome_pai",
        "raca_cor", "naturalidade", "nacionalidade",
        "estado_civil", "profissao", "grau_instrucao",
    ]
    contact_fields = [
        "ddd_fone_residencial", "fone_residencial",
        "ddd_fone_celular", "fone_celular",
        "ddd_fone_recado", "fone_recado",
    ]
    health_fields = ["cns", "equipe", "medico_responsavel"]
    address_fields = [
        "logradouro", "numero", "complemento",
        "bairro", "cep", "cidade", "uf",
    ]
    doc_fields = ["cpf"]

    def _print_group(title: str, keys: list[str]) -> None:
        print(f"\n📋 {title}")
        for key in keys:
            val = demographics.get(key, "")
            label_map = {v[0]: v[1] for v in DEMOGRAPHIC_FIELDS.values()}
            # Find label by selector
            label = ""
            for fk, (sel, lbl) in DEMOGRAPHIC_FIELDS.items():
                if fk == key:
                    label = lbl
                    break
            display = val if val else "(vazio)"
            print(f"  {label}: {display}")

    _print_group("Dados Pessoais", core_fields)
    _print_group("Contato", contact_fields)
    _print_group("Saúde", health_fields)
    _print_group("Endereço", address_fields)
    _print_group("Documentos", doc_fields)

    print("\n" + "=" * 60)

    # --- Save JSON if requested ---
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Re-add meta for the JSON file
        demographics["_meta"] = meta
        output_path.write_text(
            json.dumps(demographics, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"JSON salvo em: {output_path}")


if __name__ == "__main__":
    main()
