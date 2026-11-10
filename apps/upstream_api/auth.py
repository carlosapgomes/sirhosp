"""Static Bearer authentication with fail-closed semantics (design D5).

The configured token is compared in constant time with the presented
credential. A missing or blank setting never opens the gate: every request
answers ``500 internal_error`` instead, taking precedence over the ``401``
cases, so a misconfigured deploy cannot serve clinical data unauthenticated.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from functools import wraps

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from .errors import error_response

BEARER_SCHEME = "bearer"


def configured_token() -> str:
    """Upstream token from settings; empty means the API fails closed."""
    return getattr(settings, "SIRHOSP_UPSTREAM_API_TOKEN", "").strip()


def presented_token(authorization_header: str) -> str | None:
    """Bearer credential carried by an ``Authorization`` header, if any."""
    scheme, separator, credentials = authorization_header.partition(" ")
    if not separator or scheme.strip().lower() != BEARER_SCHEME:
        return None
    return credentials.strip() or None


def requires_upstream_token(
    view: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """Reject requests without a valid Bearer credential before the view runs."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        token = configured_token()
        if not token:
            return error_response("internal_error")
        presented = presented_token(request.headers.get("Authorization", ""))
        if presented is None or not secrets.compare_digest(
            presented.encode("utf-8"), token.encode("utf-8")
        ):
            return error_response("unauthorized")
        return view(request, *args, **kwargs)

    return wrapper
