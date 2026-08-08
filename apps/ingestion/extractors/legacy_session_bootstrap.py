"""Legacy session bootstrap for the persistent real handle (PSW-S10).

Provides a focused helper that turns an already-started Playwright-like page
into an authenticated legacy session, plus resolution of the real URL
templates (admissions, evolutions, safe renewal) required by the
``--real-handle`` path of the persistent worker.

Design (per PSW-S10 scope):

- Reuse the production-proven login selectors and password-Enter submission
  from the legacy discharge extractor.
- Wait for ``#tempoSessao`` as the authenticated-readiness signal.
- Fail with **sanitized** messages: no password, cookie, username value, or
  raw page payload is ever included in exception strings or log records.
- No real legacy access is required in tests — bootstrap operates on an
  injected Playwright-like page object.

This module deliberately keeps Playwright-specific login logic separate from
the :class:`~playwright_session_handle.PlaywrightSessionHandle` session
lifecycle and the command queue orchestration, so it is unit-testable with a
plain mock page.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from django.conf import settings as django_settings

from apps.ingestion.extractors.session_policy import SEL_SESSION_COUNTER
from apps.ingestion.historical_extraction import SourceCredentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical selectors — consistent with automation/source_system/medical_evolution
# ---------------------------------------------------------------------------

_USERNAME_FIELD_SELECTOR = 'input[placeholder="Nome de usuário"]'
"""CSS selector used by the production discharge extractor."""

_PASSWORD_FIELD_SELECTOR = 'input[placeholder="Senha"]'
"""Password selector used for both fill and Enter submission."""

_AUTH_READINESS_SELECTOR = SEL_SESSION_COUNTER
"""CSS selector used as authenticated-readiness evidence (``#tempoSessao``)."""

_AUTH_READINESS_EXPRESSION = """
() => {
  const counter = document.querySelector("#tempoSessao");
  const values = counter
    ? Array.from(counter.querySelectorAll("span"), (span) => span.textContent)
    : [];
  return values.length >= 3
    && values.slice(0, 3).every((value) => /^\\s*\\d+\\s*$/.test(value || ""));
}
"""
"""Browser predicate for a populated, parseable session countdown."""

_DEFAULT_LOGIN_TIMEOUT_SECONDS = 180
"""Production-proven timeout for every legacy login page action."""


class LegacyBootstrapError(Exception):
    """Sanitized error raised when legacy session bootstrap fails.

    Messages never include credentials, cookies, or raw page payloads. The
    command layer converts this into a user-facing failure before any run is
    claimed.
    """


@dataclass(frozen=True)
class LegacyUrlTemplates:
    """Real legacy URL templates required by the persistent real handle.

    Attributes:
        admissions_url_template: Admissions page URL template (supports
            ``{patient_record}``, ``{start_date}``, ``{end_date}``).
        evolutions_url_template: Evolutions page URL template (used by the
            persistent full-sync path; wired here even if PSW-S11 will
            consume it later).
        safe_renewal_url: Safe renewal tab URL used to reset the session
            counter by opening/rendering a legacy tab.
    """

    admissions_url_template: str
    evolutions_url_template: str
    safe_renewal_url: str


def resolve_legacy_url_templates() -> LegacyUrlTemplates:
    """Resolve real legacy URL templates from Django settings then env vars.

    Reads ``SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE``,
    ``SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE``, and
    ``SOURCE_SYSTEM_SAFE_RENEWAL_URL`` from settings first, then env vars.

    Returns:
        A :class:`LegacyUrlTemplates` with the resolved values (empty string
        for any value that is unset). The caller decides whether missing
        values are fatal (e.g. the ``--real-handle`` path fails before claim).
    """
    admissions = (
        getattr(django_settings, "SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE", "")
        or os.getenv("SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE", "")
    )
    evolutions = (
        getattr(django_settings, "SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE", "")
        or os.getenv("SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE", "")
    )
    safe_renewal = (
        getattr(django_settings, "SOURCE_SYSTEM_SAFE_RENEWAL_URL", "")
        or os.getenv("SOURCE_SYSTEM_SAFE_RENEWAL_URL", "")
    )
    return LegacyUrlTemplates(
        admissions_url_template=admissions,
        evolutions_url_template=evolutions,
        safe_renewal_url=safe_renewal,
    )


def bootstrap_legacy_session(
    page: Any,
    *,
    credentials: SourceCredentials,
    login_timeout: int = _DEFAULT_LOGIN_TIMEOUT_SECONDS,
) -> None:
    """Navigate to the source URL, log in, and wait for authenticated readiness.

    Performs the production-proven discharge login flow:

    1. Apply the legacy 180-second default action timeout.
    2. Navigate to ``credentials.url`` once at startup.
    3. Fill the username by its exact placeholder selector.
    4. Fill the password by its exact placeholder selector.
    5. Press Enter in the password field.
    6. Wait for ``#tempoSessao`` as authenticated-readiness evidence.

    All failures raise :class:`LegacyBootstrapError` with **sanitized**
    messages — no password, cookie, username value, or raw page payload is
    ever included in the exception string or in log records.

    Args:
        page: A Playwright-like ``Page`` object (mocked in tests). Must expose
            ``set_default_timeout``, ``goto``, ``locator``, and
            ``wait_for_selector``.
        credentials: Resolved source-system credentials.
        login_timeout: Maximum time in seconds for every page action, converted
            to milliseconds for the Playwright API.

    Raises:
        LegacyBootstrapError: If the page is missing, credentials are missing,
            navigation fails, login fields cannot be filled/submitted, or
            authenticated readiness is not observed.
    """
    if page is None:
        raise LegacyBootstrapError(
            "No active page available for legacy session bootstrap"
        )
    if credentials is None:
        raise LegacyBootstrapError(
            "Missing source-system credentials for legacy bootstrap"
        )
    if not credentials.url:
        raise LegacyBootstrapError(
            "Missing SOURCE_SYSTEM_URL for legacy bootstrap"
        )
    if not credentials.username:
        raise LegacyBootstrapError(
            "Missing SOURCE_SYSTEM_USERNAME for legacy bootstrap"
        )
    if not credentials.password:
        raise LegacyBootstrapError(
            "Missing SOURCE_SYSTEM_PASSWORD for legacy bootstrap"
        )

    timeout_ms = max(1, int(login_timeout)) * 1000
    _configure_timeout(page, timeout_ms)

    _navigate(page, credentials.url, timeout_ms)
    _fill_username(page, credentials.username)
    _fill_password(page, credentials.password)
    _submit_login(page)
    _await_authenticated(page, timeout_ms)


# ---------------------------------------------------------------------------
# Private steps — each failure path is sanitized
# ---------------------------------------------------------------------------


def _navigate(page: Any, url: str, timeout_ms: int) -> None:
    """Navigate the page to the source URL once."""
    try:
        page.goto(url, timeout=timeout_ms)
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning("Legacy bootstrap: navigation to login page failed (sanitized)")
        raise LegacyBootstrapError(
            "Failed to navigate to the source-system login page"
        ) from None


def _configure_timeout(page: Any, timeout_ms: int) -> None:
    """Apply the production legacy timeout to every page action."""
    try:
        page.set_default_timeout(timeout_ms)
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning(
            "Legacy bootstrap: page timeout could not be configured (sanitized)"
        )
        raise LegacyBootstrapError(
            "Failed to configure the page timeout during legacy bootstrap"
        ) from None

def _fill_username(page: Any, username: str) -> None:
    """Fill the username with the production-proven placeholder selector."""
    try:
        page.locator(_USERNAME_FIELD_SELECTOR).fill(username)
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning(
            "Legacy bootstrap: username field could not be filled (sanitized)"
        )
        raise LegacyBootstrapError(
            "Failed to fill the username field during legacy bootstrap"
        ) from None


def _fill_password(page: Any, password: str) -> None:
    """Fill the password with the production-proven placeholder selector."""
    try:
        page.locator(_PASSWORD_FIELD_SELECTOR).fill(password)
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning(
            "Legacy bootstrap: password field could not be filled (sanitized)"
        )
        raise LegacyBootstrapError(
            "Failed to fill the password field during legacy bootstrap"
        ) from None


def _submit_login(page: Any) -> None:
    """Submit through password Enter, matching the proven production path."""
    try:
        page.locator(_PASSWORD_FIELD_SELECTOR).press("Enter")
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning(
            "Legacy bootstrap: login form could not be submitted (sanitized)"
        )
        raise LegacyBootstrapError(
            "Failed to submit the login form during legacy bootstrap"
        ) from None


def _await_authenticated(page: Any, timeout_ms: int) -> None:
    """Wait for a populated ``#tempoSessao`` countdown."""
    try:
        page.wait_for_selector(_AUTH_READINESS_SELECTOR, timeout=timeout_ms)
        page.wait_for_function(
            _AUTH_READINESS_EXPRESSION,
            timeout=timeout_ms,
        )
    except Exception:  # noqa: BLE001 - sanitized below
        logger.warning(
            "Legacy bootstrap: authenticated readiness marker missing (sanitized)"
        )
        raise LegacyBootstrapError(
            "Valid authenticated readiness marker (#tempoSessao) not observed "
            "after login — credentials may be invalid or the session did not "
            "start"
        ) from None
