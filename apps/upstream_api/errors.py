"""Standard JSON error envelope for the upstream read API (design D7).

Every API error answers ``{"error": {"code", "message"}}`` with exactly those
nested keys, the status owned by the code and ``Cache-Control: no-store``.
Messages are intentionally generic: server errors never leak stack traces,
internals or clinical values.
"""

from __future__ import annotations

from typing import Any, Final

from django.http import JsonResponse

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"
CACHE_CONTROL_NO_STORE: Final = "no-store"

ERROR_STATUS: Final[dict[str, int]] = {
    "unauthorized": 401,
    "patient_not_found": 404,
    "no_snapshot": 404,
    "bad_request": 400,
    "internal_error": 500,
}

ERROR_MESSAGES: Final[dict[str, str]] = {
    "unauthorized": "Missing or invalid credentials.",
    "patient_not_found": "Patient not found.",
    "no_snapshot": "No completed census snapshot is available.",
    "bad_request": "Invalid request.",
    "internal_error": "Internal error.",
}


def api_response(payload: dict[str, Any], *, status: int = 200) -> JsonResponse:
    """JSON response carrying the fixed contract headers."""
    response = JsonResponse(
        payload,
        status=status,
        content_type=JSON_CONTENT_TYPE,
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = CACHE_CONTROL_NO_STORE
    return response


def error_response(code: str) -> JsonResponse:
    """Error response in the standard envelope for one known error code."""
    return api_response(
        {"error": {"code": code, "message": ERROR_MESSAGES[code]}},
        status=ERROR_STATUS[code],
    )
