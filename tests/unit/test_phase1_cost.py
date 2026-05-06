"""Unit tests for phase-1 cost extraction and accumulation (STC-S3).

Tests:
- `call_llm_gateway` returns tokens, cost_usd_reported, cost_usd_estimated.
- `_compute_phase1_cost_from_tokens` correctly sums multi-chunk costs.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.summaries.llm_gateway import call_llm_gateway
from apps.summaries.services import _compute_phase1_cost_from_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_gateway_completion(
    *,
    content: dict | None = None,
    input_tokens: int = 500,
    output_tokens: int = 300,
    cost: float | None = 0.008,
) -> MagicMock:
    """Mock an OpenAI completion for phase-1 gateway calls."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = (
        '{"estado_estruturado":{},"resumo_markdown":"ok"}'
        if content is None
        else str(content)
    )

    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    if cost is not None:
        usage.cost = cost
    else:
        del usage.cost
    mock.usage = usage
    return mock


# ---------------------------------------------------------------------------
# Phase-1 gateway returns tokens and cost
# ---------------------------------------------------------------------------


class TestCallLlmGatewayCost:
    """call_llm_gateway returns token and cost data."""

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_returns_tokens(self, mock_openai_cls: MagicMock):
        """call_llm_gateway returns input_tokens and output_tokens."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_gateway_completion(input_tokens=400, output_tokens=200)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert result["input_tokens"] == 400
        assert result["output_tokens"] == 200

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_returns_reported_cost(self, mock_openai_cls: MagicMock):
        """call_llm_gateway returns cost_usd_reported from usage.cost."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_gateway_completion(cost=0.004)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert result["cost_usd_reported"] == Decimal("0.004")
        assert result["cost_is_reported"] is True

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_fallback_when_cost_missing(self, mock_openai_cls: MagicMock):
        """When usage.cost is absent, falls back to estimated."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_gateway_completion(cost=None, input_tokens=1000, output_tokens=500)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert result["cost_usd_reported"] == Decimal("0.00")
        assert result["cost_is_reported"] is False
        # Estimated should be > 0 since we had tokens
        assert result["cost_usd_estimated"] > Decimal("0")

    @patch("apps.summaries.llm_gateway.OpenAI")
    def test_meta_still_present(self, mock_openai_cls: MagicMock):
        """_meta with provider/model is still returned alongside cost."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = (
            _stub_gateway_completion(cost=0.002)
        )
        mock_openai_cls.return_value = mock_client

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert "_meta" in result
        assert "provider" in result["_meta"]
        assert "model" in result["_meta"]


# ---------------------------------------------------------------------------
# Phase-1 cost accumulation helper
# ---------------------------------------------------------------------------


class TestComputePhase1Cost:
    """_compute_phase1_cost_from_tokens correctly aggregates costs."""

    def test_single_chunk(self):
        """Single chunk cost computed from tokens."""
        cost = _compute_phase1_cost_from_tokens(input_tokens=500, output_tokens=300)
        assert cost["cost_total"] == cost["cost_input"] + cost["cost_output"]
        assert cost["cost_input"] > Decimal("0")
        assert cost["cost_output"] > Decimal("0")

    def test_three_chunks_accumulated(self):
        """Three chunks summed correctly."""
        chunks = [(500, 300), (800, 400), (200, 100)]
        total_cost = Decimal("0")
        total_input = 0
        total_output = 0

        for inp, out in chunks:
            c = _compute_phase1_cost_from_tokens(input_tokens=inp, output_tokens=out)
            total_cost += c["cost_total"]
            total_input += inp
            total_output += out

        # Verify against direct computation from totals
        direct = _compute_phase1_cost_from_tokens(
            input_tokens=total_input, output_tokens=total_output,
        )

        assert total_cost == direct["cost_total"]
        assert total_input == 1500
        assert total_output == 800

    def test_zero_tokens_zero_cost(self):
        """Zero tokens yields zero cost."""
        cost = _compute_phase1_cost_from_tokens(input_tokens=0, output_tokens=0)
        assert cost["cost_input"] == Decimal("0.00")
        assert cost["cost_output"] == Decimal("0.00")
        assert cost["cost_total"] == Decimal("0.00")

    def test_large_tokens(self):
        """Large token counts scale correctly."""
        cost = _compute_phase1_cost_from_tokens(
            input_tokens=50000, output_tokens=25000,
        )
        # input: 50k * 0.005 = 0.25, output: 25k * 0.015 = 0.375
        assert cost["cost_input"] == Decimal("0.250")
        assert cost["cost_output"] == Decimal("0.375")
        assert cost["cost_total"] == Decimal("0.625")
