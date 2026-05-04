"""LLM gateway abstraction layer (APS-S4 / STP-S3 / STP-S6).

Pluggable gateway for calling an LLM to generate progressive admission
summary updates.  The built-in implementation uses the OpenAI chat
completions API (or any OpenAI-compatible endpoint).

Configuration is read from ``apps.summaries.llm_config`` (phase-1 env
vars prefixed with ``SUMMARY_PHASE1_*``) with automatic fallback to
legacy ``LLM_*`` / ``OPENAI_API_KEY`` environment variables for
backward compatibility.

Phase 2 render calls are made via ``call_llm_phase2_render``, which
accepts an explicit ``GatewayConfig`` for provider/model selection.
Costs are computed from token counts using configurable pricing
(default approximate OpenAI rates).
"""

from __future__ import annotations

import json
import os
import time
import warnings
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openai import OpenAI

from apps.summaries.llm_config import (
    LLMConfigError,
    Phase1Config,
    load_phase1_config,
)
from apps.summaries.prompt_loader import load_phase1_prompt

# ---------------------------------------------------------------------------
# Approximate cost per 1k tokens (USD).  Used when the provider does not
# return pricing metadata in the API response.
# ---------------------------------------------------------------------------

_DEFAULT_INPUT_PRICE_PER_1K = Decimal("0.005")   # $5 / 1M tokens
_DEFAULT_OUTPUT_PRICE_PER_1K = Decimal("0.015")  # $15 / 1M tokens


@dataclass(frozen=True)
class GatewayConfig:
    """LLM gateway configuration used at call time."""

    api_key: str
    base_url: str
    model: str
    timeout: float
    provider: str = "openai"


def _load_gateway_phase1_config() -> GatewayConfig:
    """Load gateway configuration, preferring ``SUMMARY_PHASE1_*`` vars.

    Resolution order:

    1. ``SUMMARY_PHASE1_*`` environment variables (new, preferred).
    2. ``LLM_API_KEY`` (or ``OPENAI_API_KEY``) + ``LLM_BASE_URL`` +
       ``LLM_MODEL`` (legacy, with deprecation warning).

    Returns:
        ``GatewayConfig`` with all required fields populated.

    Raises:
        RuntimeError: If no API key can be found through any path.
    """
    try:
        phase1 = load_phase1_config()
    except LLMConfigError:
        phase1 = None

    if phase1 is not None:
        return _phase1_to_gateway(phase1)

    # Legacy fallback
    warnings.warn(
        "LLM configuration via LLM_API_KEY/LLM_BASE_URL/LLM_MODEL is "
        "deprecated. Please migrate to SUMMARY_PHASE1_* environment "
        "variables. See .env.example for the new format.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _load_legacy_config()


def _phase1_to_gateway(config: Phase1Config) -> GatewayConfig:
    """Convert a ``Phase1Config`` to a ``GatewayConfig``."""
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
    return GatewayConfig(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=timeout,
        provider=config.provider,
    )


def _load_legacy_config() -> GatewayConfig:
    """Load configuration from legacy LLM_* environment variables."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "No LLM API key found. Set SUMMARY_PHASE1_API_KEY or "
            "LLM_API_KEY (or OPENAI_API_KEY) in your environment."
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


def _load_config() -> GatewayConfig:
    """Load LLM gateway configuration (delegates to phase-1 loader).

    Kept for backward compatibility with internal callers.
    """
    return _load_gateway_phase1_config()


def _get_system_prompt() -> str:
    """Load the phase-1 canonical prompt from its versioned file."""
    return load_phase1_prompt()


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
            {"role": "system", "content": _get_system_prompt()},
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


# ---------------------------------------------------------------------------
# Phase 2 render gateway (STP-S6)
# ---------------------------------------------------------------------------


def _compute_phase2_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    input_price_per_1k: Decimal = _DEFAULT_INPUT_PRICE_PER_1K,
    output_price_per_1k: Decimal = _DEFAULT_OUTPUT_PRICE_PER_1K,
) -> dict[str, Decimal]:
    """Compute cost breakdown from token counts.

    Returns a dict with ``cost_input``, ``cost_output``, and ``cost_total``
    as ``Decimal`` values (USD).
    """
    cost_input = (Decimal(input_tokens) / Decimal(1000)) * input_price_per_1k
    cost_output = (
        Decimal(output_tokens) / Decimal(1000)
    ) * output_price_per_1k
    return {
        "cost_input": cost_input,
        "cost_output": cost_output,
        "cost_total": cost_input + cost_output,
    }


def call_llm_phase2_render(
    *,
    canonical_narrative: str,
    canonical_state: dict[str, Any],
    prompt_text: str,
    config: GatewayConfig,
) -> dict[str, Any]:
    """Call an LLM to render the canonical summary into a final Markdown.

    Args:
        canonical_narrative: Markdown narrative from phase 1.
        canonical_state: Structured clinical state from phase 1.
        prompt_text: System prompt to guide rendering style (loaded from
            file or provided as custom text).
        config: LLM provider/model/credentials for this call.

    Returns:
        A dict with keys:

        * ``content`` (str): The rendered Markdown output.
        * ``input_tokens`` (int)
        * ``output_tokens`` (int)
        * ``cached_tokens`` (int, default 0)
        * ``cost_input`` (Decimal)
        * ``cost_output`` (Decimal)
        * ``cost_total`` (Decimal)
        * ``request_payload`` (dict): Full request sent to the LLM.
        * ``response_payload`` (dict): Full API response.

    Raises:
        RuntimeError: If the LLM call fails or returns invalid content.
    """
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
    )

    user_message = json.dumps(
        {
            "estado_estruturado": canonical_state,
            "resumo_markdown_base": canonical_narrative,
        },
        ensure_ascii=False,
    )

    request_payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
    }

    start_time = time.monotonic()

    try:
        completion = client.chat.completions.create(**request_payload)
    except Exception as exc:
        raise RuntimeError(
            f"Phase 2 LLM call failed ({config.provider}/{config.model}): "
            f"{exc}"
        ) from exc

    latency_ms = int((time.monotonic() - start_time) * 1000)

    content = completion.choices[0].message.content or ""

    usage = getattr(completion, "usage", None)
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    cached_tokens = getattr(
        usage, "prompt_tokens_details", {}
    )
    if isinstance(cached_tokens, dict):
        cached_tokens = cached_tokens.get("cached_tokens", 0)
    else:
        cached_tokens = 0

    costs = _compute_phase2_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    response_payload = {
        "id": getattr(completion, "id", ""),
        "model": getattr(completion, "model", config.model),
        "choices": [
            {
                "index": choice.index,
                "message": {
                    "role": choice.message.role,
                    "content": choice.message.content,
                },
                "finish_reason": choice.finish_reason,
            }
            for choice in completion.choices
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        } if usage else None,
    }

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_input": costs["cost_input"],
        "cost_output": costs["cost_output"],
        "cost_total": costs["cost_total"],
        "request_payload": request_payload,
        "response_payload": response_payload,
        "latency_ms": latency_ms,
    }
