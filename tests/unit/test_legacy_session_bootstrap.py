"""Tests for the legacy session bootstrap helper (PSW-S10).

These tests prove that the persistent worker's ``--real-handle`` path can
bootstrap an authenticated legacy session through a Playwright-like page and
resolve the real URL templates required for admissions/evolutions/safe
renewal.

All tests use mocks/fakes — no real legacy access and no real Playwright.
Sanitization is verified explicitly: no password or cookie value may appear in
exception strings or captured log output.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from apps.ingestion.extractors.legacy_session_bootstrap import (
    LegacyBootstrapError,
    LegacyUrlTemplates,
    bootstrap_legacy_session,
    resolve_legacy_url_templates,
)
from apps.ingestion.historical_extraction import SourceCredentials

_PASSWORD_VALUE = "super-secret-password-123"
_COOKIE_VALUE = "JSESSIONID=abc-def-456"

# Exact selectors used by the production discharge extractor.
_USERNAME_SELECTOR = 'input[placeholder="Nome de usuário"]'
_PASSWORD_SELECTOR = 'input[placeholder="Senha"]'


def _make_credentials(**overrides) -> SourceCredentials:
    base = {
        "url": "https://legacy.example.test/sistema/login.xhtml",
        "username": "operador",
        "password": _PASSWORD_VALUE,
    }
    base.update(overrides)
    return SourceCredentials(**base)


def _make_page() -> MagicMock:
    """Build a mock Playwright-like page with the canonical login chain."""
    page = MagicMock()
    page.url = "https://legacy.example.test/sistema/login.xhtml"
    return page


# ===========================================================================
# URL template resolution
# ===========================================================================


class TestResolveLegacyUrlTemplates:
    """resolve_legacy_url_templates reads settings then env."""

    def test_resolves_all_three_templates_from_settings(self) -> None:
        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="https://x/admissions/{patient_record}",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="https://x/evolutions/{patient_record}",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="https://x/safe",
        ):
            templates = resolve_legacy_url_templates()

        assert isinstance(templates, LegacyUrlTemplates)
        assert templates.admissions_url_template == "https://x/admissions/{patient_record}"
        assert templates.evolutions_url_template == "https://x/evolutions/{patient_record}"
        assert templates.safe_renewal_url == "https://x/safe"

    def test_returns_empty_strings_when_unset(self, monkeypatch) -> None:
        for var in (
            "SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE",
            "SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE",
            "SOURCE_SYSTEM_SAFE_RENEWAL_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="",
        ):
            templates = resolve_legacy_url_templates()

        assert templates.admissions_url_template == ""
        assert templates.evolutions_url_template == ""
        assert templates.safe_renewal_url == ""

    def test_env_used_when_settings_empty(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE", "https://env/adm/{patient_record}"
        )
        monkeypatch.setenv(
            "SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE", "https://env/evo/{patient_record}"
        )
        monkeypatch.setenv("SOURCE_SYSTEM_SAFE_RENEWAL_URL", "https://env/safe")
        with override_settings(
            SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE="",
            SOURCE_SYSTEM_SAFE_RENEWAL_URL="",
        ):
            templates = resolve_legacy_url_templates()

        assert templates.admissions_url_template == "https://env/adm/{patient_record}"
        assert templates.safe_renewal_url == "https://env/safe"


# ===========================================================================
# Successful bootstrap
# ===========================================================================


class TestBootstrapSuccess:
    """bootstrap_legacy_session navigates, fills, submits, and waits."""

    def test_navigates_to_source_url_once(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds, login_timeout=30)

        page.goto.assert_called_once()
        args, _ = page.goto.call_args
        assert args[0] == creds.url

    def test_applies_explicit_timeout_to_all_page_actions(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds, login_timeout=42)

        page.set_default_timeout.assert_called_once_with(42_000)
        _, kwargs = page.goto.call_args
        assert kwargs.get("timeout") == 42_000

    def test_fills_username_with_proven_legacy_selector(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds)

        page.locator.assert_any_call(_USERNAME_SELECTOR)
        page.locator.return_value.fill.assert_any_call(creds.username)

    def test_fills_password_with_proven_legacy_selector(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds)

        page.locator.assert_any_call(_PASSWORD_SELECTOR)
        page.locator.return_value.fill.assert_any_call(_PASSWORD_VALUE)

    def test_submits_login_with_password_enter(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds)

        page.locator.assert_any_call(_PASSWORD_SELECTOR)
        page.locator.return_value.press.assert_called_once_with("Enter")
        page.get_by_role.assert_not_called()

    def test_waits_for_tempo_sessao_readiness(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds, login_timeout=15)

        page.wait_for_selector.assert_called_once()
        args, kwargs = page.wait_for_selector.call_args
        assert "#tempoSessao" in args or kwargs.get("selector") == "#tempoSessao"
        _, kwargs = page.wait_for_selector.call_args
        assert kwargs.get("timeout") == 15_000

    def test_waits_for_populated_countdown_after_marker(self) -> None:
        """Attached marker alone is not authenticated readiness."""
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds, login_timeout=15)

        page.wait_for_function.assert_called_once()
        args, kwargs = page.wait_for_function.call_args
        assert "tempoSessao" in args[0]
        assert "querySelectorAll" in args[0]
        assert kwargs.get("timeout") == 15_000

    def test_default_legacy_timeout_is_used_when_omitted(self) -> None:
        page = _make_page()
        creds = _make_credentials()

        bootstrap_legacy_session(page, credentials=creds)

        page.set_default_timeout.assert_called_once_with(180_000)
        _, kwargs = page.wait_for_selector.call_args
        assert kwargs.get("timeout") == 180_000


# ===========================================================================
# Sanitized failures
# ===========================================================================


class TestBootstrapSanitizedFailures:
    """Bootstrap failures never leak password/cookie values."""

    def test_navigation_failure_raises_sanitized_error(self) -> None:
        page = _make_page()
        page.goto.side_effect = RuntimeError(_PASSWORD_VALUE)
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert _PASSWORD_VALUE not in str(exc_info.value)
        assert _COOKIE_VALUE not in str(exc_info.value)

    def test_username_fill_failure_is_sanitized(self) -> None:
        page = _make_page()
        page.locator.return_value.fill.side_effect = RuntimeError(
            f"cannot fill {_PASSWORD_VALUE}"
        )
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert _PASSWORD_VALUE not in str(exc_info.value)

    def test_submit_failure_is_sanitized(self) -> None:
        page = _make_page()
        page.locator.return_value.press.side_effect = RuntimeError(
            f"cannot press Enter with {_PASSWORD_VALUE}"
        )
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert _PASSWORD_VALUE not in str(exc_info.value)
        assert "cannot press Enter" not in str(exc_info.value)

    def test_missing_tempo_sessao_is_sanitized(self) -> None:
        page = _make_page()
        page.wait_for_selector.side_effect = RuntimeError("timeout waiting #tempoSessao")
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert _PASSWORD_VALUE not in str(exc_info.value)
        assert "timeout" not in str(exc_info.value).lower()

    def test_unpopulated_tempo_sessao_is_sanitized(self) -> None:
        page = _make_page()
        page.wait_for_function.side_effect = RuntimeError(
            f"counter delayed {_PASSWORD_VALUE}"
        )
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert _PASSWORD_VALUE not in str(exc_info.value)
        assert "counter delayed" not in str(exc_info.value)

    def test_missing_url_raises_sanitized_error(self) -> None:
        page = _make_page()
        creds = _make_credentials(url="")

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert "SOURCE_SYSTEM_URL" in str(exc_info.value)
        assert _PASSWORD_VALUE not in str(exc_info.value)

    def test_missing_username_raises_sanitized_error(self) -> None:
        page = _make_page()
        creds = _make_credentials(username="")

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert "SOURCE_SYSTEM_USERNAME" in str(exc_info.value)

    def test_missing_password_raises_sanitized_error(self) -> None:
        page = _make_page()
        creds = _make_credentials(password="")

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=creds)

        assert "SOURCE_SYSTEM_PASSWORD" in str(exc_info.value)

    def test_none_credentials_raises_sanitized_error(self) -> None:
        page = _make_page()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(page, credentials=None)  # type: ignore[arg-type]

        assert _PASSWORD_VALUE not in str(exc_info.value)

    def test_none_page_raises_sanitized_error(self) -> None:
        creds = _make_credentials()

        with pytest.raises(LegacyBootstrapError) as exc_info:
            bootstrap_legacy_session(None, credentials=creds)  # type: ignore[arg-type]

        assert _PASSWORD_VALUE not in str(exc_info.value)

    def test_no_password_in_log_output(self, caplog) -> None:
        """No password value appears in captured log records on failure."""
        page = _make_page()
        page.goto.side_effect = RuntimeError(f"network down {_PASSWORD_VALUE}")
        creds = _make_credentials()

        with caplog.at_level(
            logging.DEBUG,
            logger="apps.ingestion.extractors.legacy_session_bootstrap",
        ):
            with pytest.raises(LegacyBootstrapError):
                bootstrap_legacy_session(page, credentials=creds)

        for record in caplog.records:
            assert _PASSWORD_VALUE not in record.getMessage()
