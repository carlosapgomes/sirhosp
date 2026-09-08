"""First-login password-change enforcement (design D3, SLICE-AUP-S2).

``RequirePasswordChangeMiddleware`` is the single chokepoint that forces an
authenticated user whose profile carries ``must_change_password=True`` to
change the provisional password on ``/perfil/`` before using any other
portal page. Anonymous users and unflagged/missing profiles are never
redirected; monitoring probes on ``/health/`` and the operator's ``/admin/``
stay reachable (allowlist).
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

# Allowlisted path prefixes. /health/ keeps monitoring probes — even when
# authenticated — free of redirects; /admin/ is the operator's break-glass;
# /accounts/ is reserved for future auth-related routes.
ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "/perfil/",
    "/login/",
    "/logout/",
    "/admin/",
    "/static/",
    "/health/",
    "/accounts/",
)

FORCED_CHANGE_URL = "/perfil/"


class RequirePasswordChangeMiddleware:
    """Redirect flagged users away from every non-allowlisted path."""

    def __init__(
        self, get_response: Callable[[HttpRequest], HttpResponse]
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self._must_force_password_change(request):
            return redirect(FORCED_CHANGE_URL)
        return self.get_response(request)

    @staticmethod
    def _must_force_password_change(request: HttpRequest) -> bool:
        if request.path.startswith(ALLOWED_PATH_PREFIXES):
            return False
        try:
            user = request.user
        except AttributeError:
            return False  # auth middleware not available for this request
        if not user.is_authenticated:
            return False
        profile = getattr(user, "profile", None)
        if profile is None:
            return False  # no profile: nothing to force
        return profile.must_change_password
