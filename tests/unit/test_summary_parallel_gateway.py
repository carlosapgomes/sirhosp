"""Tests for parallel LLM gateway (APS-P-S2 RED phase).

Tests for asyncio-based parallel chunk calls and final consolidation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.summaries.llm_gateway import GatewayConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gateway_config() -> GatewayConfig:
    """Minimal valid gateway config for tests."""
    return GatewayConfig(
        api_key="sk-test",
        base_url="https://api.test/v1",
        model="test-model",
        timeout=30.0,
        provider="test-provider",
    )


@pytest.fixture
def sample_chunks_data() -> list[dict]:
    """Three chunks with minimal event data."""
    return [
        {
            "chunk_index": 0,
            "novas_evolucoes": [
                {
                    "event_id": "evt-1",
                    "happened_at": "2025-01-01T10:00:00-03:00",
                    "signed_at": "2025-01-01T10:30:00-03:00",
                    "author_name": "Dr. A",
                    "profession_type": "medical",
                    "content_text": "Paciente admitido com dor abdominal.",
                },
            ],
        },
        {
            "chunk_index": 1,
            "novas_evolucoes": [
                {
                    "event_id": "evt-2",
                    "happened_at": "2025-01-03T10:00:00-03:00",
                    "signed_at": "2025-01-03T10:30:00-03:00",
                    "author_name": "Dr. B",
                    "profession_type": "medical",
                    "content_text": "Exames laboratoriais sem alterações.",
                },
            ],
        },
        {
            "chunk_index": 2,
            "novas_evolucoes": [
                {
                    "event_id": "evt-3",
                    "happened_at": "2025-01-06T10:00:00-03:00",
                    "signed_at": "2025-01-06T10:30:00-03:00",
                    "author_name": "Dr. C",
                    "profession_type": "medical",
                    "content_text": "Alta hospitalar programada.",
                },
            ],
        },
    ]


def _make_llm_response() -> dict:
    """Return a valid LLM response dict matching the summary contract."""
    return {
        "estado_estruturado": {
            "motivo_internacao": "dor abdominal",
            "linha_do_tempo": ["Paciente admitido."],
            "problemas_ativos": ["dor abdominal"],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": [],
            "intercorrencias": [],
            "pendencias": [],
            "riscos_eventos_adversos": [],
            "situacao_atual": "estável",
        },
        "resumo_markdown": "# Resumo\n\nPaciente estável.",
        "mudancas_da_rodada": ["Admissão."],
        "incertezas": [],
        "evidencias": [
            {
                "event_id": "evt-1",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. A",
                "snippet": "Paciente admitido.",
            }
        ],
        "alertas_consistencia": [],
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd_reported": 0,
        "cost_usd_estimated": 0,
        "cost_is_reported": False,
    }


def _make_async_completion_mock(response_dict: dict):
    """Build an AsyncMock that simulates an OpenAI chat completion response."""

    class UsageMock:
        prompt_tokens = 100
        completion_tokens = 50

    class ChoiceMessageMock:
        role = "assistant"
        content = '{"ok": true}'
        def __init__(self, content):
            self.content = content

    class ChoiceMock:
        index = 0
        finish_reason = "stop"
        def __init__(self, content):
            self.message = ChoiceMessageMock(content)

    import json

    content_json = json.dumps(response_dict, ensure_ascii=False)

    completion_mock = AsyncMock()
    completion_mock.id = "cmpl-test"
    completion_mock.model = "test-model"
    completion_mock.choices = [ChoiceMock(content_json)]
    completion_mock.usage = UsageMock()
    return completion_mock


# ---------------------------------------------------------------------------
# Tests for _call_chunk_local_async
# ---------------------------------------------------------------------------


class TestCallChunkLocalAsync:
    """Tests for the async single-chunk LLM call function."""

    @pytest.mark.asyncio
    async def test_returns_validated_output(self, gateway_config):
        """A successful call returns a dict passing schema validation."""
        from apps.summaries.llm_gateway import _call_chunk_local_async

        response = _make_llm_response()
        completion_mock = _make_async_completion_mock(response)

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=completion_mock
            )
            mock_client_cls.return_value = mock_client

            result = await _call_chunk_local_async(
                config=gateway_config,
                novas_evolucoes=[
                    {
                        "event_id": "evt-1",
                        "happened_at": "2025-01-01T10:00:00-03:00",
                        "signed_at": "2025-01-01T10:30:00-03:00",
                        "author_name": "Dr. A",
                        "profession_type": "medical",
                        "content_text": "Paciente admitido.",
                    }
                ],
                chunk_index=0,
            )

            assert isinstance(result, dict)
            assert "estado_estruturado" in result
            assert "resumo_markdown" in result
            assert "evidencias" in result

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self, gateway_config):
        """Fails twice, succeeds on third attempt."""
        from apps.summaries.llm_gateway import _call_chunk_local_async

        response = _make_llm_response()
        completion_mock = _make_async_completion_mock(response)

        # Fail twice with JSON decode error, then succeed
        fail_completion = AsyncMock()
        fail_completion.choices = [MagicMock()]
        fail_completion.choices[0].message.content = "not json {{{"

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return fail_completion
            return completion_mock

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=side_effect
            )
            mock_client_cls.return_value = mock_client

            result = await _call_chunk_local_async(
                config=gateway_config,
                novas_evolucoes=[],
                chunk_index=0,
            )

            assert call_count == 3
            assert "estado_estruturado" in result

    @pytest.mark.asyncio
    async def test_exhausts_retries_returns_error_dict(self, gateway_config):
        """After 3 failures, returns error dict instead of raising."""
        from apps.summaries.llm_gateway import _call_chunk_local_async

        fail_completion = AsyncMock()
        fail_completion.choices = [MagicMock()]
        fail_completion.choices[0].message.content = "not json {{{"

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=fail_completion
            )
            mock_client_cls.return_value = mock_client

            result = await _call_chunk_local_async(
                config=gateway_config,
                novas_evolucoes=[],
                chunk_index=2,
            )

            assert result.get("_error") is True
            assert result.get("_chunk_index") == 2
            assert "exhausted 3 retries" in result.get("error_message", "")

    @pytest.mark.asyncio
    async def test_uses_parallel_local_prompt(self, gateway_config):
        """The function loads and uses phase1_parallel_local_v1.md."""
        from apps.summaries.llm_gateway import _call_chunk_local_async

        response = _make_llm_response()
        completion_mock = _make_async_completion_mock(response)

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            create_mock = AsyncMock(return_value=completion_mock)
            mock_client.chat.completions.create = create_mock
            mock_client_cls.return_value = mock_client

            await _call_chunk_local_async(
                config=gateway_config,
                novas_evolucoes=[],
                chunk_index=0,
            )

            # Verify the system prompt contains "resumo local"
            call_kwargs = create_mock.call_args.kwargs
            messages = call_kwargs.get("messages", [])
            system_msg = messages[0]["content"] if messages else ""
            assert "resumo local" in system_msg.lower()


# ---------------------------------------------------------------------------
# Tests for _call_chunks_async
# ---------------------------------------------------------------------------


class TestCallChunksAsync:
    """Tests for the async parallel dispatch orchestration."""

    @pytest.mark.asyncio
    async def test_dispatches_all_chunks_concurrently(
        self, gateway_config, sample_chunks_data
    ):
        """N chunks are all dispatched with asyncio.gather."""
        from apps.summaries.llm_gateway import _call_chunks_async

        response = _make_llm_response()
        completion_mock = _make_async_completion_mock(response)

        call_counts = {"count": 0}

        async def track_calls(*args, **kwargs):
            call_counts["count"] += 1
            # Small delay to verify concurrency
            await asyncio.sleep(0.01)
            return completion_mock

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=track_calls)
            mock_client_cls.return_value = mock_client

            results = await _call_chunks_async(
                chunks_data=sample_chunks_data,
                config=gateway_config,
            )

            assert len(results) == 3
            assert call_counts["count"] == 3

    @pytest.mark.asyncio
    async def test_results_ordered_by_chunk_index(
        self, gateway_config, sample_chunks_data
    ):
        """Results maintain the original chunk order."""
        # Create responses with chunk-specific markers
        import json

        from apps.summaries.llm_gateway import _call_chunks_async

        async def per_chunk_response(*args, **kwargs):
            # Extract chunk info from the user message
            user_msg = kwargs.get("messages", [{}])[-1].get("content", "{}")
            try:
                parsed = json.loads(user_msg)
                chunk_idx = parsed.get("_chunk_index", -1)
            except (json.JSONDecodeError, KeyError):
                chunk_idx = -1

            resp = _make_llm_response()
            resp["resumo_markdown"] = f"# Chunk {chunk_idx}\n\nTest."
            completion = _make_async_completion_mock(resp)
            return completion

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=per_chunk_response
            )
            mock_client_cls.return_value = mock_client

            results = await _call_chunks_async(
                chunks_data=sample_chunks_data,
                config=gateway_config,
            )

            assert len(results) == 3
            # Results should be in order of chunk_index
            for i, result in enumerate(results):
                assert result.get("_chunk_index") == i


# ---------------------------------------------------------------------------
# Tests for call_llm_parallel_chunks (sync entry point)
# ---------------------------------------------------------------------------


class TestCallLLMParallelChunks:
    """Tests for the synchronous entry point that wraps asyncio.run."""

    def test_sync_entry_point_returns_ordered_results(
        self, gateway_config, sample_chunks_data
    ):
        """call_llm_parallel_chunks returns results via asyncio.run."""
        from apps.summaries.llm_gateway import call_llm_parallel_chunks

        response = _make_llm_response()
        completion_mock = _make_async_completion_mock(response)

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=completion_mock
            )
            mock_client_cls.return_value = mock_client

            results = call_llm_parallel_chunks(
                chunks_data=sample_chunks_data,
                config=gateway_config,
            )

            assert len(results) == 3
            for result in results:
                assert "estado_estruturado" in result


# ---------------------------------------------------------------------------
# Tests for call_llm_parallel_final
# ---------------------------------------------------------------------------


class TestCallLLMParallelFinal:
    """Tests for the final consolidation call."""

    def test_final_call_uses_parallel_final_prompt(
        self, gateway_config
    ):
        """The final consolidation uses phase2_parallel_final_v1.md."""
        from apps.summaries.llm_gateway import call_llm_parallel_final

        response = _make_llm_response()
        # For the final call, the response is plain Markdown text, not JSON
        completion_mock = _make_async_completion_mock(response)

        local_summaries = [
            {
                "periodo": "2025-01-01 a 2025-01-04",
                "resumo_markdown": "# Período 1\n\nPaciente admitido.",
                "estado_estruturado": {
                    "situacao_atual": "estável",
                },
            },
            {
                "periodo": "2025-01-04 a 2025-01-07",
                "resumo_markdown": "# Período 2\n\nExames normais.",
                "estado_estruturado": {
                    "situacao_atual": "em observação",
                },
            },
        ]

        with patch(
            "apps.summaries.llm_gateway.AsyncOpenAI"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = MagicMock()
            mock_client.chat.completions = MagicMock()
            create_mock = AsyncMock(return_value=completion_mock)
            mock_client.chat.completions.create = create_mock
            mock_client_cls.return_value = mock_client

            result = call_llm_parallel_final(
                local_summaries=local_summaries,
                config=gateway_config,
            )

            assert "content" in result
            # Verify the system prompt mentions overlapping/duplicates
            call_kwargs = create_mock.call_args.kwargs
            messages = call_kwargs.get("messages", [])
            system_msg = messages[0]["content"] if messages else ""
            assert (
                "sobrepostos" in system_msg.lower()
                or "sobreposição" in system_msg.lower()
            )
