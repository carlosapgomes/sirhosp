"""LLM gateway abstraction layer (APS-S4).

Provides a pluggable gateway interface for calling an LLM to generate
summary updates.  The built-in ``call_llm_gateway`` stub returns
deterministic, valid JSON suitable for integration tests.

Swap the implementation to a real provider (e.g. OpenAI, Anthropic)
by replacing this module or injecting a different callable.
"""

from __future__ import annotations

from typing import Any


def call_llm_gateway(
    *,
    estado_estruturado_anterior: dict[str, Any],
    resumo_markdown_anterior: str,
    novas_evolucoes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stub LLM gateway — deterministic, always-valid response.

    Returns a well-formed summary output dict that passes
    ``validate_summary_output``.

    Args:
        estado_estruturado_anterior: Prior structured state (may be empty).
        resumo_markdown_anterior: Prior narrative Markdown (may be empty).
        novas_evolucoes: List of new clinical event dicts for this chunk.

    Returns:
        A dict conforming to the summary output contract.
    """
    return {
        "estado_estruturado": {
            "motivo_internacao": "internação eletiva para procedimento",
            "linha_do_tempo": [
                "Paciente admitido para avaliação inicial",
            ],
            "problemas_ativos": ["Observação clínica em curso"],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": [],
            "intercorrencias": [],
            "pendencias": ["Aguardando resultado de exames"],
            "riscos_eventos_adversos": [],
            "situacao_atual": "Paciente estável, em observação",
        },
        "resumo_markdown": (
            "# Resumo de Internação\n\n"
            "## Motivo da internação\n\n"
            "Internação eletiva para procedimento.\n\n"
            "## Linha do tempo\n\n"
            "- Paciente admitido para avaliação inicial\n\n"
            "## Problemas ativos\n\n"
            "- Observação clínica em curso\n\n"
            "## Pendências\n\n"
            "- Aguardando resultado de exames\n\n"
            "## Situação atual\n\n"
            "Paciente estável, em observação.\n"
        ),
        "mudancas_da_rodada": ["Registro inicial da internação"],
        "incertezas": [],
        "evidencias": [
            {
                "event_id": "evt-stub-001",
                "snippet": "Paciente admitido para avaliação inicial",
            },
        ],
    }
