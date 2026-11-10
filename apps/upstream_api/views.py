"""Read-only upstream API views (design D2, D3, D4, D7, D9, D10).

``GET /api/v1/inpatients/current`` mirrors the current census photo 1:1 and
``GET /api/v1/patients/{prontuario}`` mirrors one patient demographic record.
Views are CSRF-exempt (token authentication is the only gate) and every
response carries ``Cache-Control: no-store``. Application logging records
method, sanitized route and status only — never parameters or clinical data.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.census.models import CensusSnapshot

from .access_log import PATIENT_DEMOGRAPHICS_ROUTE
from .auth import requires_upstream_token
from .demographics import build_patient_demographics
from .errors import CACHE_CONTROL_NO_STORE, api_response, error_response
from .photo import InvalidPhotoRow, build_current_photo

logger = logging.getLogger("apps.upstream_api")

CURRENT_INPATIENTS_ROUTE = "/api/v1/inpatients/current"


def _timestamp(value: datetime | None) -> str | None:
    """ISO 8601 with explicit offset; ``null`` stays ``null`` (no fabrication)."""
    return value.isoformat() if value is not None else None


def _serialize_row(row: CensusSnapshot) -> dict[str, Any]:
    """The census identity contract, mirrored without business transformation."""
    return {
        "setor_codigo": row.setor_codigo,
        "setor": row.setor,
        "leito": row.leito,
        "prontuario": row.prontuario,
        "nome": row.nome,
        "bed_status": row.bed_status,
        "especialidade": row.especialidade,
        "source_admission_at": _timestamp(row.source_admission_at),
        "source_movement_at": _timestamp(row.source_movement_at),
    }


def no_store(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Keep ``Cache-Control: no-store`` on every response, including 405."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = CACHE_CONTROL_NO_STORE
        return response

    return wrapper


def _log_failure(request: HttpRequest, route: str) -> None:
    """Sanitized failure record: method, route and status only."""
    logger.error(
        "upstream_api method=%s route=%s status=500",
        request.method,
        route,
    )


@csrf_exempt
@no_store
@requires_upstream_token
@require_GET
def current_inpatients(request: HttpRequest) -> JsonResponse:
    try:
        photo = build_current_photo()
        if photo is None:
            return error_response("no_snapshot")
        payload = {
            "captured_at": photo.captured_at.isoformat(),
            "cycle_seq": photo.cycle_seq,
            "row_count": len(photo.rows),
            "patients": [_serialize_row(row) for row in photo.rows],
        }
    except InvalidPhotoRow:
        _log_failure(request, CURRENT_INPATIENTS_ROUTE)
        return error_response("internal_error")
    except Exception:
        _log_failure(request, CURRENT_INPATIENTS_ROUTE)
        return error_response("internal_error")
    return api_response(payload)


@csrf_exempt
@no_store
@requires_upstream_token
@require_GET
def patient_demographics(request: HttpRequest, prontuario: str) -> JsonResponse:
    try:
        payload = build_patient_demographics(prontuario)
    except Exception:
        _log_failure(request, PATIENT_DEMOGRAPHICS_ROUTE)
        return error_response("internal_error")
    if payload is None:
        return error_response("patient_not_found")
    return api_response(payload)
