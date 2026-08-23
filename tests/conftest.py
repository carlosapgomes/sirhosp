"""Global pytest safety guards."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _block_external_llm_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail locally when a test forgets to simulate an LLM boundary."""

    def fail_unmocked_llm(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError(
            "Unexpected external LLM client in tests; mock the application boundary"
        )

    monkeypatch.setattr(
        "apps.summaries.llm_gateway.OpenAI",
        fail_unmocked_llm,
    )
    monkeypatch.setattr(
        "apps.summaries.llm_gateway.AsyncOpenAI",
        fail_unmocked_llm,
    )
