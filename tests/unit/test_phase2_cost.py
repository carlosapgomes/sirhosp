"""Unit tests for phase-2 cost extraction from provider response (STC-S2).

Tests:
- `call_llm_phase2_render` extracts `cost_usd_reported` from usage.cost.
- `call_llm_phase2_render` falls back to estimated cost when usage.cost absent.
- `cost_is_reported` flag indicates whether cost came from provider or tokens.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.summaries.llm_gateway import GatewayConfig, call_llm_phase2_render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GatewayConfig:
    defaults: dict[str, object] = {
        "api_key": "sk-test",
        "base_url": "https://test.openai.com/v1",
        "model": "test-model",
        "timeout": 30,
        "provider": "openai",
    }
    defaults.update(overrides)
    return GatewayConfig(**defaults)  # type: ignore[arg-type]


def _stub_completion(
    *,
    content: str = "Test summary",
    input_tokens: int = 500,
    output_tokens: int = 300,
    cost: float | None = 0.008,
) -> MagicMock:
    """Build a Mock that mimics an OpenAI completion object."""
    mock = MagicMock()
    mock.id = "chatcmpl-test"
    mock.model = "test-model"

    # choices
    choice = MagicMock()
    choice.index = 0
    choice.finish_reason = "stop"
    choice.message.role = "assistant"
    choice.message.content = content
    mock.choices = [choice]

    # usage
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    usage.total_tokens = input_tokens + output_tokens

    # OpenRouter puts cost in model_extra (Pydantic v2)
    if cost is not None:
        usage.cost = cost
    else:
        # Simulate no cost attribute at all
        del usage.cost

    # prompt_tokens_details for cached tokens extraction
    details = MagicMock()
    details.cached_tokens = 0
    usage.prompt_tokens_details = details

    mock.usage = usage
    return mock


# ---------------------------------------------------------------------------
# cost extraction from usage.cost
# ---------------------------------------------------------------------------


class TestPhase2CostReported:
    """Tests where the provider returns usage.cost (real cost)."""

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_extracts_reported_cost_from_usage(
        self, mock_openai_cls: MagicMock,
    ):
        """call_llm_phase2_render returns cost_usd_reported=Decimal
        when usage.cost is present."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_completion(
                content="# Hello",
                input_tokens=500,
                output_tokens=300,
                cost=0.008,
            )
        )
        mock_openai_cls.return_value = mock_client

        cfg = _make_config()
        result = call_llm_phase2_render(
            canonical_narrative="# Prior",
            canonical_state={},
            prompt_text="Render as Markdown.",
            config=cfg,
        )

        # Real cost from provider
        assert result["cost_usd_reported"] == Decimal("0.008")
        assert result["cost_is_reported"] is True

        # Estimated cost still calculated
        assert "cost_usd_estimated" in result
        assert result["cost_usd_estimated"] > Decimal("0")

        # Legacy cost fields still present for backward compat
        assert result["cost_total"] == result["cost_usd_reported"]

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_reported_cost_handles_small_float(
        self, mock_openai_cls: MagicMock,
    ):
        """Small costs like 8e-06 are correctly converted to Decimal."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_completion(cost=8e-06)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_phase2_render(
            canonical_narrative="",
            canonical_state={},
            prompt_text="x",
            config=_make_config(),
        )

        assert result["cost_usd_reported"] == Decimal("0.000008")
        assert result["cost_is_reported"] is True


class TestPhase2CostEstimated:
    """Tests where the provider does NOT return usage.cost."""

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_fallback_to_estimated_when_cost_missing(
        self, mock_openai_cls: MagicMock,
    ):
        """When usage.cost is absent, cost_usd_reported=0 and
        cost_is_reported=False."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_completion(cost=None)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_phase2_render(
            canonical_narrative="",
            canonical_state={},
            prompt_text="x",
            config=_make_config(),
        )

        assert result["cost_usd_reported"] == Decimal("0.00")
        assert result["cost_is_reported"] is False
        # Estimated from tokens
        assert result["cost_usd_estimated"] > Decimal("0")
        # Legacy total uses estimated when reported is zero
        assert result["cost_total"] == result["cost_usd_estimated"]

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_fallback_zero_tokens_yields_zero_estimated(
        self, mock_openai_cls: MagicMock,
    ):
        """Edge case: zero tokens → zero estimated cost."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_completion(
                cost=None, input_tokens=0, output_tokens=0,
            )
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_phase2_render(
            canonical_narrative="",
            canonical_state={},
            prompt_text="x",
            config=_make_config(),
        )

        assert result["cost_usd_reported"] == Decimal("0.00")
        assert result["cost_usd_estimated"] == Decimal("0.00")
        assert result["cost_total"] == Decimal("0.00")
