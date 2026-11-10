"""Unit evidence for slice UPA-001 R2: Bearer auth matrix and fail-closed precedence.

Every case crosses the configured upstream token (absent, blank or present)
with one credential shape a consumer can send, always through the real
middleware stack declared by ``config.settings``.

Synthetic values only: the token and every identifier below are fabricated.
"""

from __future__ import annotations

import secrets

import pytest
from django.test import Client

PHOTO_URL = "/api/v1/inpatients/current"
SYNTHETIC_TOKEN = "synthetic-upstream-token-0123456789abcdef"


def _get(authorization: str | None):
    client = Client()
    if authorization is None:
        return client.get(PHOTO_URL)
    return client.get(PHOTO_URL, headers={"Authorization": authorization})


def _error_code(response) -> str:
    return response.json()["error"]["code"]


@pytest.mark.django_db
@pytest.mark.parametrize("configured", ["", "   "], ids=["missing", "blank"])
@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer " + SYNTHETIC_TOKEN,
        "Bearer wrong-synthetic-token",
        "Token " + SYNTHETIC_TOKEN,
        "Bearer",
    ],
    ids=[
        "no-header",
        "empty-header",
        "correct-token",
        "wrong-token",
        "wrong-scheme",
        "scheme-only",
    ],
)
def test_unconfigured_token_answers_500_for_every_credential(
    settings, configured: str, authorization: str | None
):
    """Fail-closed precedence: an unset token wins over every 401 case."""
    settings.SIRHOSP_UPSTREAM_API_TOKEN = configured

    response = _get(authorization)

    assert response.status_code == 500
    assert _error_code(response) == "internal_error"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Basic {token}",
        "Token {token}",
        "Bearer wrong-synthetic-token",
    ],
    ids=[
        "no-header",
        "empty-header",
        "scheme-only",
        "empty-credentials",
        "wrong-scheme",
        "other-scheme",
        "wrong-token",
    ],
)
def test_configured_token_rejects_missing_or_malformed_credentials(
    settings, authorization: str | None
):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN
    presented = (
        authorization if authorization is None else authorization.format(token=SYNTHETIC_TOKEN)
    )

    response = _get(presented)

    assert response.status_code == 401
    assert _error_code(response) == "unauthorized"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "authorization",
    ["Bearer {token}", "bearer {token}", "Bearer   {token}"],
    ids=["canonical", "lowercase-scheme", "extra-spaces"],
)
def test_valid_bearer_token_passes_the_auth_gate(settings, authorization: str):
    """A valid credential reaches the photo; an empty database answers no_snapshot."""
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN

    response = _get(authorization.format(token=SYNTHETIC_TOKEN))

    assert response.status_code == 404
    assert _error_code(response) == "no_snapshot"


@pytest.mark.django_db
def test_presented_token_is_compared_in_constant_time(settings, monkeypatch):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN
    comparisons: list[tuple[bytes, bytes]] = []
    real_compare_digest = secrets.compare_digest

    def spy(presented: bytes, configured: bytes) -> bool:
        comparisons.append((presented, configured))
        return real_compare_digest(presented, configured)

    monkeypatch.setattr("apps.upstream_api.auth.secrets.compare_digest", spy)

    response = _get(f"Bearer {SYNTHETIC_TOKEN}")

    assert response.status_code == 404
    assert (SYNTHETIC_TOKEN.encode("utf-8"), SYNTHETIC_TOKEN.encode("utf-8")) in comparisons
