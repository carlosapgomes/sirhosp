"""Unit evidence for slice UPA-001 R3: standard error envelope and headers.

The envelope is ``{"error": {"code", "message"}}`` with exactly those nested
keys, ``Cache-Control: no-store`` and no stack trace or internal detail on
``500``. Synthetic values only.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.upstream_api.errors import error_response

PHOTO_URL = "/api/v1/inpatients/current"
SYNTHETIC_TOKEN = "synthetic-upstream-token-0123456789abcdef"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"

ERROR_STATUS = {
    "unauthorized": 401,
    "patient_not_found": 404,
    "no_snapshot": 404,
    "bad_request": 400,
    "internal_error": 500,
}


def _assert_envelope(response, code: str) -> str:
    body = json.loads(response.content)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]
    assert response["Cache-Control"] == "no-store"
    return response.content.decode("utf-8")


@pytest.mark.parametrize(("code", "status"), sorted(ERROR_STATUS.items()))
def test_error_response_uses_the_standard_envelope(code: str, status: int):
    response = error_response(code)

    assert response.status_code == status
    assert response["Content-Type"] == JSON_CONTENT_TYPE
    _assert_envelope(response, code)


def test_unauthenticated_request_uses_the_envelope(settings):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN

    response = Client().get(PHOTO_URL)

    assert response.status_code == 401
    _assert_envelope(response, "unauthorized")


@pytest.mark.django_db
def test_missing_photo_uses_the_no_snapshot_envelope(settings):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN

    response = Client(headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"}).get(PHOTO_URL)

    assert response.status_code == 404
    _assert_envelope(response, "no_snapshot")


def test_fail_closed_500_is_generic_and_carries_no_stack_trace(settings):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = ""

    response = Client().get(PHOTO_URL)
    text = _assert_envelope(response, "internal_error")

    assert "Traceback" not in text
    assert 'File "' not in text
    assert ".py" not in text
    assert "Exception" not in text
    assert SYNTHETIC_TOKEN not in text
