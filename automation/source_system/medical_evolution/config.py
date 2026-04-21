import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    source_system_url: str | None
    source_system_username: str | None
    source_system_password: str | None
    llm_base_url: str
    llm_api_key: str
    llm_model: str = "default"
    llm_timeout_seconds: float = 120.0
    flask_host: str = "0.0.0.0"
    flask_port: int = 8000
    evolution_fixture_path: Path | None = None
    pdf_output_path: Path = Path("downloads/evolucoes-intervalo.pdf")
    txt_output_path: Path = Path("downloads/evolucoes-intervalo.txt")
    processed_txt_output_path: Path = Path("downloads/evolucoes-intervalo-processado.txt")
    sorted_txt_output_path: Path = Path("downloads/evolucoes-intervalo-ordenado.txt")
    pdf_debug_html_path: Path = Path("downloads/evolucoes-intervalo.debug.html")


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    flask_port = int(os.getenv("FLASK_PORT", "8000"))
    llm_timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    evolution_fixture_path_value = os.getenv("EVOLUTION_FIXTURE_PATH")

    source_system_url = os.getenv("SOURCE_SYSTEM_URL")
    source_system_username = os.getenv("SOURCE_SYSTEM_USERNAME")
    source_system_password = os.getenv("SOURCE_SYSTEM_PASSWORD")

    if not evolution_fixture_path_value:
        source_system_url = required_env("SOURCE_SYSTEM_URL")
        source_system_username = required_env("SOURCE_SYSTEM_USERNAME")
        source_system_password = required_env("SOURCE_SYSTEM_PASSWORD")

    return Settings(
        source_system_url=source_system_url,
        source_system_username=source_system_username,
        source_system_password=source_system_password,
        llm_base_url=required_env("LLM_BASE_URL"),
        llm_api_key=required_env("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "default"),
        llm_timeout_seconds=llm_timeout_seconds,
        flask_host=os.getenv("FLASK_HOST", "0.0.0.0"),
        flask_port=flask_port,
        evolution_fixture_path=Path(evolution_fixture_path_value) if evolution_fixture_path_value else None,
        pdf_output_path=Path(os.getenv("PDF_OUTPUT_PATH", "downloads/evolucoes-intervalo.pdf")),
        txt_output_path=Path(os.getenv("TXT_OUTPUT_PATH", "downloads/evolucoes-intervalo.txt")),
        processed_txt_output_path=Path(
            os.getenv("PROCESSED_TXT_OUTPUT_PATH", "downloads/evolucoes-intervalo-processado.txt")
        ),
        sorted_txt_output_path=Path(
            os.getenv("SORTED_TXT_OUTPUT_PATH", "downloads/evolucoes-intervalo-ordenado.txt")
        ),
        pdf_debug_html_path=Path(
            os.getenv("PDF_DEBUG_HTML_PATH", "downloads/evolucoes-intervalo.debug.html")
        ),
    )
