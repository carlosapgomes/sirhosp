"""Tests for centralized LLM environment configuration (STP-S3).

Covers:
- Phase 1 required env vars (success and error cases).
- Phase 2 up to 4 options with enabled/disabled filtering.
- Integration with gateway config loading.
"""

from __future__ import annotations

import os

import pytest

from apps.summaries.llm_config import (
    LLMConfigError,
    load_phase1_config,
    load_phase2_options,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_summary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all SUMMARY_PHASE* variables from the environment."""
    for key in list(os.environ):
        if key.startswith("SUMMARY_PHASE"):
            monkeypatch.delenv(key, raising=False)


def _set_phase1_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str = "openai",
    model: str = "gpt-4o",
    base_url: str = "https://api.openai.com/v1",
    api_key: str = "sk-test-phase1",
) -> None:
    monkeypatch.setenv("SUMMARY_PHASE1_PROVIDER", provider)
    monkeypatch.setenv("SUMMARY_PHASE1_MODEL", model)
    monkeypatch.setenv("SUMMARY_PHASE1_BASE_URL", base_url)
    monkeypatch.setenv("SUMMARY_PHASE1_API_KEY", api_key)


def _set_phase2_option(
    monkeypatch: pytest.MonkeyPatch,
    n: int,
    *,
    label: str = "",
    provider: str = "",
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    enabled: bool = False,
) -> None:
    """Set a single phase-2 option env block."""
    prefix = f"SUMMARY_PHASE2_OPTION_{n}"
    monkeypatch.setenv(f"{prefix}_LABEL", label)
    monkeypatch.setenv(f"{prefix}_PROVIDER", provider)
    monkeypatch.setenv(f"{prefix}_MODEL", model)
    monkeypatch.setenv(f"{prefix}_BASE_URL", base_url)
    monkeypatch.setenv(f"{prefix}_API_KEY", api_key)
    monkeypatch.setenv(f"{prefix}_ENABLED", "true" if enabled else "false")


# ---------------------------------------------------------------------------
# Phase 1 tests
# ---------------------------------------------------------------------------


class TestLoadPhase1Config:
    def test_all_vars_present_returns_config(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase1_env(monkeypatch)

        config = load_phase1_config()

        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key == "sk-test-phase1"

    def test_custom_provider_values(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase1_env(
            monkeypatch,
            provider="anthropic",
            model="claude-3-5-sonnet",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )

        config = load_phase1_config()

        assert config.provider == "anthropic"
        assert config.model == "claude-3-5-sonnet"
        assert config.base_url == "https://api.anthropic.com"
        assert config.api_key == "sk-ant-test"

    def test_missing_provider_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_PHASE1_MODEL", "gpt-4o")
        monkeypatch.setenv("SUMMARY_PHASE1_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("SUMMARY_PHASE1_API_KEY", "sk-test")

        with pytest.raises(LLMConfigError, match="PROVIDER"):
            load_phase1_config()

    def test_missing_model_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_PHASE1_PROVIDER", "openai")
        monkeypatch.setenv("SUMMARY_PHASE1_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("SUMMARY_PHASE1_API_KEY", "sk-test")

        with pytest.raises(LLMConfigError, match="MODEL"):
            load_phase1_config()

    def test_missing_base_url_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_PHASE1_PROVIDER", "openai")
        monkeypatch.setenv("SUMMARY_PHASE1_MODEL", "gpt-4o")
        monkeypatch.setenv("SUMMARY_PHASE1_API_KEY", "sk-test")

        with pytest.raises(LLMConfigError, match="BASE_URL"):
            load_phase1_config()

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_PHASE1_PROVIDER", "openai")
        monkeypatch.setenv("SUMMARY_PHASE1_MODEL", "gpt-4o")
        monkeypatch.setenv("SUMMARY_PHASE1_BASE_URL", "https://api.openai.com/v1")

        with pytest.raises(LLMConfigError, match="API_KEY"):
            load_phase1_config()

    def test_empty_api_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase1_env(monkeypatch, api_key="   ")

        with pytest.raises(LLMConfigError, match="API_KEY"):
            load_phase1_config()

    def test_empty_provider_raises(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase1_env(monkeypatch, provider="  ")

        with pytest.raises(LLMConfigError, match="PROVIDER"):
            load_phase1_config()

    def test_config_is_frozen(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase1_env(monkeypatch)
        config = load_phase1_config()

        with pytest.raises(AttributeError):  # dataclass FrozenInstanceError or similar
            config.api_key = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2 tests
# ---------------------------------------------------------------------------


class TestLoadPhase2Options:
    def test_no_options_configured_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)

        options = load_phase2_options()

        assert options == []

    def test_single_enabled_option_returned(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase2_option(
            monkeypatch,
            1,
            label="GPT-4o",
            provider="openai",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            enabled=True,
        )

        options = load_phase2_options()

        assert len(options) == 1
        opt = options[0]
        assert opt.label == "GPT-4o"
        assert opt.provider == "openai"
        assert opt.model == "gpt-4o"
        assert opt.base_url == "https://api.openai.com/v1"
        assert opt.api_key == "sk-test"
        assert opt.enabled is True

    def test_disabled_option_not_returned(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase2_option(
            monkeypatch,
            1,
            label="GPT-4o",
            provider="openai",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            enabled=False,
        )

        options = load_phase2_options()

        assert options == []

    def test_two_enabled_one_disabled(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        # Option 1: disabled
        _set_phase2_option(monkeypatch, 1, label="GPT-3.5", provider="openai",
                           model="gpt-3.5-turbo", base_url="https://api.openai.com/v1",
                           api_key="sk-1", enabled=False)
        # Option 2: enabled
        _set_phase2_option(monkeypatch, 2, label="GPT-4o", provider="openai",
                           model="gpt-4o", base_url="https://api.openai.com/v1",
                           api_key="sk-2", enabled=True)
        # Option 3: enabled
        _set_phase2_option(monkeypatch, 3, label="Claude", provider="anthropic",
                           model="claude-3-5-sonnet", base_url="https://api.anthropic.com",
                           api_key="sk-3", enabled=True)

        options = load_phase2_options()

        assert len(options) == 2
        labels = [o.label for o in options]
        assert "GPT-4o" in labels
        assert "Claude" in labels
        assert "GPT-3.5" not in labels

    def test_all_four_options_enabled(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        for n in range(1, 5):
            _set_phase2_option(
                monkeypatch,
                n,
                label=f"Model-{n}",
                provider=f"provider-{n}",
                model=f"model-{n}",
                base_url=f"https://api{n}.example.com",
                api_key=f"sk-{n}",
                enabled=True,
            )

        options = load_phase2_options()

        assert len(options) == 4
        assert [o.label for o in options] == ["Model-1", "Model-2", "Model-3", "Model-4"]

    def test_option_missing_label_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_PROVIDER", "openai")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_MODEL", "gpt-4o")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_API_KEY", "sk-test")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "true")
        # LABEL not set — defaults to empty string

        options = load_phase2_options()

        assert len(options) == 1
        assert options[0].label == ""

    def test_option_missing_required_field_excluded(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        # Set all fields except MODEL
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_LABEL", "GPT-4o")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_PROVIDER", "openai")
        # MODEL intentionally missing
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_API_KEY", "sk-test")
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "true")

        options = load_phase2_options()

        # Incomplete option should be silently excluded
        assert options == []

    def test_enabled_flag_case_insensitive(self, monkeypatch: pytest.MonkeyPatch):
        """ENABLED accepts 'true', 'True', 'TRUE', '1'."""
        _clear_summary_env(monkeypatch)
        _set_phase2_option(monkeypatch, 1, label="A", provider="p", model="m",
                           base_url="https://x.com", api_key="sk", enabled=True)
        # Override with uppercase
        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "TRUE")
        assert len(load_phase2_options()) == 1

        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "1")
        assert len(load_phase2_options()) == 1

        monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "false")
        assert load_phase2_options() == []

    def test_option_number_above_4_ignored(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase2_option(monkeypatch, 5, label="Extra", provider="p", model="m",
                           base_url="https://x.com", api_key="sk", enabled=True)

        options = load_phase2_options()

        assert options == []

    def test_option_is_frozen(self, monkeypatch: pytest.MonkeyPatch):
        _clear_summary_env(monkeypatch)
        _set_phase2_option(monkeypatch, 1, label="X", provider="p", model="m",
                           base_url="https://x.com", api_key="sk", enabled=True)
        options = load_phase2_options()
        opt = options[0]

        with pytest.raises(AttributeError):
            opt.label = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Gateway backward-compat tests
# ---------------------------------------------------------------------------


class TestGatewayBackwardCompat:
    """Ensure the gateway still works when only old env vars are set."""

    def test_gateway_uses_phase1_config_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When SUMMARY_PHASE1_* vars are set, gateway uses them."""
        from apps.summaries.llm_gateway import _load_gateway_phase1_config

        _clear_summary_env(monkeypatch)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        _set_phase1_env(
            monkeypatch,
            provider="test-prov",
            model="test-model",
            base_url="https://test.example.com",
            api_key="sk-new",
        )

        config = _load_gateway_phase1_config()

        assert config.provider == "test-prov"
        assert config.model == "test-model"
        assert config.base_url == "https://test.example.com"
        assert config.api_key == "sk-new"

    def test_gateway_falls_back_to_legacy_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When SUMMARY_PHASE1_* vars are absent, fall back to LLM_* vars."""
        from apps.summaries.llm_gateway import _load_gateway_phase1_config

        _clear_summary_env(monkeypatch)
        monkeypatch.setenv("LLM_API_KEY", "sk-legacy")
        monkeypatch.setenv("LLM_BASE_URL", "https://legacy.example.com")
        monkeypatch.setenv("LLM_MODEL", "legacy-model")

        config = _load_gateway_phase1_config()

        assert config.model == "legacy-model"
        assert config.base_url == "https://legacy.example.com"
        assert config.api_key == "sk-legacy"

    def test_gateway_falls_back_to_openai_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When LLM_API_KEY missing, fall back to OPENAI_API_KEY."""
        from apps.summaries.llm_gateway import _load_gateway_phase1_config

        _clear_summary_env(monkeypatch)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fallback")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        config = _load_gateway_phase1_config()

        assert config.api_key == "sk-openai-fallback"

    def test_gateway_raises_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch):
        """When no API key is available anywhere, raise RuntimeError."""
        from apps.summaries.llm_gateway import _load_gateway_phase1_config

        _clear_summary_env(monkeypatch)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        with pytest.raises(RuntimeError, match="API key"):
            _load_gateway_phase1_config()
