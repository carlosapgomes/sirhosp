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

import asyncio
import json
import os
import time
import warnings
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openai import AsyncOpenAI, OpenAI

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

    # ---- Token usage and cost (STC-S3) ----
    usage = getattr(completion, "usage", None)
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    raw_cost = getattr(usage, "cost", None) if usage else None
    cost_is_reported = raw_cost is not None
    cost_usd_reported = (
        Decimal(str(raw_cost)) if cost_is_reported else Decimal("0.00")
    )
    # Estimated cost (always computed for audit)
    cost_usd_estimated = (
        (Decimal(input_tokens) / Decimal(1000)) * _DEFAULT_INPUT_PRICE_PER_1K
        + (Decimal(output_tokens) / Decimal(1000)) * _DEFAULT_OUTPUT_PRICE_PER_1K
    )

    # Embed provider/model metadata so the service layer can record it
    # in AdmissionSummaryVersion without a separate side-channel.
    result["_meta"] = {
        "provider": config.provider,
        "model": config.model,
    }

    result["input_tokens"] = input_tokens
    result["output_tokens"] = output_tokens
    result["cost_usd_reported"] = cost_usd_reported
    result["cost_usd_estimated"] = cost_usd_estimated
    result["cost_is_reported"] = cost_is_reported

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

    # Estimated cost from tokens (always computed as audit trail)
    costs_estimated = _compute_phase2_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    # Real cost from provider (OpenRouter puts cost in usage.cost,
    # a Pydantic model_extra field).
    raw_cost = getattr(usage, "cost", None) if usage else None
    cost_is_reported = raw_cost is not None
    cost_usd_reported = (
        Decimal(str(raw_cost)) if cost_is_reported else Decimal("0.00")
    )

    # Effective total: prefer reported, fall back to estimated.
    cost_total = (
        cost_usd_reported
        if cost_is_reported and cost_usd_reported > Decimal("0")
        else costs_estimated["cost_total"]
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
        "cost_input": costs_estimated["cost_input"],
        "cost_output": costs_estimated["cost_output"],
        "cost_total": cost_total,
        "cost_usd_reported": cost_usd_reported,
        "cost_usd_estimated": costs_estimated["cost_total"],
        "cost_is_reported": cost_is_reported,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "latency_ms": latency_ms,
    }


# ---------------------------------------------------------------------------
# Parallel pipeline gateway (APS-P-S2)
# ---------------------------------------------------------------------------

_PARALLEL_MAX_RETRIES_PER_CHUNK = 3


def call_llm_parallel_chunks(
    *,
    chunks_data: list[dict[str, Any]],
    config: GatewayConfig,
) -> list[dict[str, Any]]:
    """Dispatch all parallel chunks concurrently via asyncio.

    Synchronous entry point that wraps ``asyncio.run()``.

    Args:
        chunks_data: List of chunk dicts, each with ``chunk_index`` and
            ``novas_evolucoes`` keys.
        config: LLM gateway configuration (provider, model, etc.).

    Returns:
        List of result dicts, one per chunk, in the same order.  Results
        may include ``_error: True`` for chunks that exhausted retries.
    """
    return asyncio.run(_call_chunks_async(
        chunks_data=chunks_data,
        config=config,
    ))


async def _call_chunks_async(
    *,
    chunks_data: list[dict[str, Any]],
    config: GatewayConfig,
) -> list[dict[str, Any]]:
    """Async: dispatch all chunks with ``asyncio.gather``.

    Each chunk is processed independently and concurrently.
    Results are always returned in the original chunk order.
    """
    tasks = [
        _call_chunk_local_async(
            config=config,
            novas_evolucoes=chunk.get("novas_evolucoes", []),
            chunk_index=chunk.get("chunk_index", i),
        )
        for i, chunk in enumerate(chunks_data)
    ]
    return list(await asyncio.gather(*tasks))


async def _call_chunk_local_async(
    *,
    config: GatewayConfig,
    novas_evolucoes: list[dict[str, Any]],
    chunk_index: int,
) -> dict[str, Any]:
    """Async: call LLM for a single parallel chunk with retries.

    Uses the phase-1 parallel local prompt.  Validates the response
    against the summary output schema.  Retries up to
    ``_PARALLEL_MAX_RETRIES_PER_CHUNK`` times.

    Args:
        config: LLM gateway configuration.
        novas_evolucoes: Clinical events for this chunk.
        chunk_index: Position of this chunk in the admission timeline.

    Returns:
        Validated LLM output dict.  On exhaustion, returns a dict with
        ``_error: True`` and an ``error_message``.
    """
    from apps.summaries.prompt_loader import load_phase1_parallel_local_prompt
    from apps.summaries.schema import validate_summary_output

    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
    )

    prompt_text = load_phase1_parallel_local_prompt()

    user_message = json.dumps(
        {
            "novas_evolucoes": novas_evolucoes,
            "_chunk_index": chunk_index,
        },
        ensure_ascii=False,
    )

    last_error_msg: str = ""

    for _attempt in range(1, _PARALLEL_MAX_RETRIES_PER_CHUNK + 1):
        try:
            completion = await client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )

            content = completion.choices[0].message.content or "{}"
            result = json.loads(content)

            # Validate schema
            validation_errors = validate_summary_output(result)
            if not validation_errors:
                # ---- Token usage and cost ----
                usage = getattr(completion, "usage", None)
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                raw_cost = getattr(usage, "cost", None) if usage else None
                cost_is_reported = raw_cost is not None
                cost_usd_reported = (
                    Decimal(str(raw_cost))
                    if cost_is_reported
                    else Decimal("0.00")
                )
                cost_usd_estimated = (
                    (Decimal(input_tokens) / Decimal(1000))
                    * _DEFAULT_INPUT_PRICE_PER_1K
                    + (Decimal(output_tokens) / Decimal(1000))
                    * _DEFAULT_OUTPUT_PRICE_PER_1K
                )

                result["_meta"] = {
                    "provider": config.provider,
                    "model": config.model,
                }
                result["_chunk_index"] = chunk_index
                result["input_tokens"] = input_tokens
                result["output_tokens"] = output_tokens
                result["cost_usd_reported"] = cost_usd_reported
                result["cost_usd_estimated"] = cost_usd_estimated
                result["cost_is_reported"] = cost_is_reported

                return result

            # Validation failed
            last_error_msg = "; ".join(validation_errors)

        except Exception as exc:
            last_error_msg = str(exc)

    # Exhausted retries
    return {
        "_error": True,
        "_chunk_index": chunk_index,
        "error_message": (
            f"Chunk {chunk_index} exhausted "
            f"{_PARALLEL_MAX_RETRIES_PER_CHUNK} retries: "
            f"{last_error_msg}"
        ),
    }


def call_llm_parallel_final(
    *,
    local_summaries: list[dict[str, Any]],
    config: GatewayConfig,
) -> dict[str, Any]:
    """Consolidate multiple local summaries into a final narrative.

    Synchronous entry point.  Uses the phase-2 parallel final prompt
    to instruct the LLM to remove overlapping duplicities, preserve
    chronological order, and produce a single longitudinal summary.

    Args:
        local_summaries: List of dicts, each with ``periodo``,
            ``resumo_markdown``, and ``estado_estruturado`` keys.
        config: LLM gateway configuration.

    Returns:
        Dict with ``content`` (final Markdown), token counts, costs,
        ``request_payload``, and ``response_payload``.
    """
    from apps.summaries.prompt_loader import load_phase2_parallel_final_prompt

    return asyncio.run(_call_parallel_final_async(
        local_summaries=local_summaries,
        config=config,
        prompt_text=load_phase2_parallel_final_prompt(),
    ))


async def _call_parallel_final_async(
    *,
    local_summaries: list[dict[str, Any]],
    config: GatewayConfig,
    prompt_text: str,
) -> dict[str, Any]:
    """Async: single consolidation call for the parallel pipeline."""
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
    )

    user_message = json.dumps(
        {"resumos_locais": local_summaries},
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

    import time as time_module

    start_time = time_module.monotonic()

    try:
        completion = await client.chat.completions.create(**request_payload)
    except Exception as exc:
        raise RuntimeError(
            f"Parallel final consolidation failed "
            f"({config.provider}/{config.model}): {exc}"
        ) from exc

    latency_ms = int((time_module.monotonic() - start_time) * 1000)

    content = completion.choices[0].message.content or ""

    usage = getattr(completion, "usage", None)
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    costs_estimated = _compute_phase2_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    raw_cost = getattr(usage, "cost", None) if usage else None
    cost_is_reported = raw_cost is not None
    cost_usd_reported = (
        Decimal(str(raw_cost)) if cost_is_reported else Decimal("0.00")
    )
    cost_total = (
        cost_usd_reported
        if cost_is_reported and cost_usd_reported > Decimal("0")
        else costs_estimated["cost_total"]
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
        "cached_tokens": 0,
        "cost_input": costs_estimated["cost_input"],
        "cost_output": costs_estimated["cost_output"],
        "cost_total": cost_total,
        "cost_usd_reported": cost_usd_reported,
        "cost_usd_estimated": costs_estimated["cost_total"],
        "cost_is_reported": cost_is_reported,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "latency_ms": latency_ms,
    }
