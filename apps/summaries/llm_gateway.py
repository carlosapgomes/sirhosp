"""LLM gateway abstraction layer (APS-S4).

Pluggable gateway for calling an LLM to generate progressive admission
summary updates.  The built-in implementation uses the OpenAI chat
completions API (or any OpenAI-compatible endpoint via ``LLM_BASE_URL``).

Swap the implementation to a different provider (e.g. Anthropic) by
replacing this module or injecting a different callable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class GatewayConfig:
    """LLM gateway configuration read from environment variables."""

    api_key: str
    base_url: str
    model: str
    timeout: float
    provider: str = "openai"


def _load_config() -> GatewayConfig:
    """Load LLM gateway configuration from environment.

    Required:
        LLM_API_KEY — API key for the LLM provider.

    Optional:
        LLM_BASE_URL  — override the API base URL (default: OpenAI).
        LLM_MODEL     — model name (default: ``gpt-4o``).
        LLM_TIMEOUT_SECONDS — request timeout in seconds (default: ``120``).
    """
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        # Fall back to OPENAI_API_KEY for convenience.
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY environment variable is required. "
            "Set it in your .env file."
        )

    base_url = os.environ.get(
        "LLM_BASE_URL", "https://api.openai.com/v1"
    ).strip()
    model = os.environ.get("LLM_MODEL", "gpt-4o").strip()
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))

    return GatewayConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )


_SYSTEM_PROMPT = """Você é um assistente clínico responsável por manter um
resumo progressivo de internação hospitalar.

Você recebe:
- estado_estruturado_anterior: estado canônico atual do resumo (pode ser vazio).
- resumo_markdown_anterior: narrativa Markdown atual (pode ser vazia).
- novas_evolucoes: lista de novos eventos clínicos a incorporar.
  Cada evento inclui: event_id, happened_at, signed_at, author_name,
  profession_type e content_text.

Sua tarefa é produzir um objeto JSON com os campos listados abaixo.

## Regras

1. O campo `estado_estruturado` deve conter o estado canônico ATUALIZADO,
   incorporando as novas evoluções.
2. O campo `resumo_markdown` deve ser a narrativa completa e atualizada em
   Markdown, com as seções fixas listadas abaixo.
3. O campo `mudancas_da_rodada` deve listar em linguagem natural o que mudou
   nesta rodada (frases curtas).
4. O campo `incertezas` deve listar pontos de incerteza ou ambiguidade
   identificados (pode ser vazio).
5. O campo `evidencias` deve conter referências aos eventos usados. Cada
   evidência deve incluir obrigatoriamente:
   - `event_id` (string)
   - `happened_at` (datetime ISO-8601 do evento)
   - `author_name` (autor do evento)
   - `snippet` (trecho textual curto que fundamenta a informação)
6. O campo `alertas_consistencia` deve listar SUSPEITAS de inconsistência
   clínica/documental (não afirme erro como fato). Cada alerta deve trazer:
   - `tipo` (ex.: lateralidade_conflitante, possivel_paciente_errado,
     cronologia_improvavel, dado_critico_sem_confirmacao)
   - `descricao` (curta e objetiva)
   - `evidencias` (lista no mesmo formato do campo evidencias).

## Seções fixas do resumo_markdown

1. Motivo da internação
2. Linha do tempo
3. Problemas ativos
4. Problemas resolvidos
5. Procedimentos
6. Antimicrobianos
7. Exames relevantes
8. Pendências
9. Riscos / eventos adversos
10. Situação atual

## Campos do estado_estruturado

- motivo_internacao (string)
- linha_do_tempo (list de strings)
- problemas_ativos (list de strings)
- problemas_resolvidos (list de strings)
- procedimentos (list de strings)
- antimicrobianos (list de strings)
- exames_relevantes (list de strings)
- intercorrencias (list de strings)
- pendencias (list de strings)
- riscos_eventos_adversos (list de strings)
- situacao_atual (string)

## Exemplo de saída

{
  "estado_estruturado": {
    "motivo_internacao": "...",
    "linha_do_tempo": ["..."],
    "problemas_ativos": ["..."],
    "problemas_resolvidos": [],
    "procedimentos": [],
    "antimicrobianos": [],
    "exames_relevantes": [],
    "intercorrencias": [],
    "pendencias": [],
    "riscos_eventos_adversos": [],
    "situacao_atual": "..."
  },
  "resumo_markdown": "# Resumo de Internação\\n\\n...",
  "mudancas_da_rodada": ["..."],
  "incertezas": [],
  "evidencias": [
    {
      "event_id": "...",
      "happened_at": "2026-05-03T08:15:00-03:00",
      "author_name": "Dr(a). ...",
      "snippet": "..."
    }
  ],
  "alertas_consistencia": [
    {
      "tipo": "lateralidade_conflitante",
      "descricao": "Há menções divergentes de lateralidade no prontuário.",
      "evidencias": [
        {
          "event_id": "...",
          "happened_at": "2026-05-03T08:15:00-03:00",
          "author_name": "Dr(a). ...",
          "snippet": "..."
        }
      ]
    }
  ]
}

Retorne SOMENTE o JSON, sem texto antes ou depois.
"""


def call_llm_gateway(
    *,
    estado_estruturado_anterior: dict[str, Any],
    resumo_markdown_anterior: str,
    novas_evolucoes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call the LLM to produce a progressive summary update.

    Reads provider configuration from environment variables
    (``LLM_API_KEY``, ``LLM_BASE_URL``, ``LLM_MODEL``).

    Args:
        estado_estruturado_anterior: Prior structured state (may be empty).
        resumo_markdown_anterior: Prior narrative Markdown (may be empty).
        novas_evolucoes: List of new clinical event dicts for this chunk.

    Returns:
        A dict conforming to the summary output contract, with an
        additional ``_meta`` key containing ``provider`` and ``model``.
    """
    config = _load_config()

    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
    )

    user_message = json.dumps(
        {
            "estado_estruturado_anterior": estado_estruturado_anterior,
            "resumo_markdown_anterior": resumo_markdown_anterior,
            "novas_evolucoes": novas_evolucoes,
        },
        ensure_ascii=False,
    )

    completion = client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    content = completion.choices[0].message.content or "{}"
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned invalid JSON: {exc}. "
            f"Raw content (first 500 chars): {content[:500]}"
        ) from exc

    # Embed provider/model metadata so the service layer can record it
    # in AdmissionSummaryVersion without a separate side-channel.
    result["_meta"] = {
        "provider": config.provider,
        "model": config.model,
    }

    return result
