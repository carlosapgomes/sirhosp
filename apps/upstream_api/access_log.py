"""Sanitized access logging for the upstream read API (design D6, R8/R10).

Every ``/api/v1/*`` request target is reduced to a fixed route pattern before
any gunicorn access or error record can reach the log: query strings are
dropped and matched routes, unmatched or malformed paths all collapse to a
constant. Non-API targets pass through byte for byte, so portal logging stays
unchanged — including its access format: an ``/api/v1/*`` record renders
method, sanitized route and status only, while every other record keeps the
access format configured for the server (gunicorn's default: client IP,
timestamp, request line, size, referer and user-agent).

Sanitization happens by path prefix, never by guessing nominal values, so a
look-alike path cannot bypass it and an identifier embedded in a query string
cannot survive. Framework error records that would carry a raw API target are
suppressed: an error record may be absent under suppression, but no emitted
record ever holds a raw target, query or identifier.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Final

from gunicorn.glogging import Logger

UPSTREAM_API_PREFIX: Final = "/api/v1"
UPSTREAM_API_ROOT: Final = f"{UPSTREAM_API_PREFIX}/"
UNMATCHED_ROUTE: Final = f"{UPSTREAM_API_PREFIX}/<unmatched>"
API_ACCESS_LOG_FORMAT: Final = "%(m)s %(U)s %(s)s"

# Fixed route pattern per registered API path. A new endpoint adds its own
# entry so its access lines stay constant (no identifiers, no query strings).
ROUTE_PATTERNS: Final[dict[str, str]] = {
    "/api/v1/inpatients/current": "/api/v1/inpatients/current",
}


def is_upstream_api_path(path: str) -> bool:
    return path == UPSTREAM_API_PREFIX or path.startswith(UPSTREAM_API_ROOT)


def sanitize_request_target(target: str) -> str:
    """Reduce one request target (path plus optional query) to a fixed route."""
    path = target.partition("?")[0]
    if not is_upstream_api_path(path):
        return target
    return ROUTE_PATTERNS.get(path, UNMATCHED_ROUTE)


def sanitize_environ(environ: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``environ`` whose request-target entries are all sanitized."""
    target = environ.get("RAW_URI") or environ.get("PATH_INFO") or ""
    route = sanitize_request_target(target)
    if route == target:
        return dict(environ)
    sanitized = dict(environ)
    sanitized["RAW_URI"] = route
    sanitized["PATH_INFO"] = route
    sanitized["QUERY_STRING"] = ""
    return sanitized


def carries_upstream_target(message: Any, args: tuple[Any, ...]) -> bool:
    """Whether a framework record would carry a raw ``/api/v1`` target."""
    if UPSTREAM_API_PREFIX in str(message):
        return True
    return any(UPSTREAM_API_PREFIX in str(arg) for arg in args)


class SanitizedAccessLogger(Logger):
    """Gunicorn logger that never emits a raw ``/api/v1`` request target."""

    def atoms(self, resp, req, environ, request_time):
        return super().atoms(resp, req, sanitize_environ(environ), request_time)

    def access_log_format_for(self, environ: dict[str, Any]) -> str:
        """Access format for one request: three fields for API, server format else."""
        target = environ.get("RAW_URI") or environ.get("PATH_INFO") or ""
        if is_upstream_api_path(target.partition("?")[0]):
            return API_ACCESS_LOG_FORMAT
        return self.cfg.access_log_format

    def access(self, resp, req, environ, request_time):
        """Gunicorn's access record with the format selected per request target.

        Gunicorn reads ``access_log_format`` from server config only, which is
        why the API narrowing lives here instead of in ``gunicorn.conf.py``: a
        server-wide directive would also narrow portal records.
        """
        if not self.access_log_enabled:
            return
        safe_atoms = self.atoms_wrapper_class(self.atoms(resp, req, environ, request_time))
        try:
            self.access_log.info(self.access_log_format_for(environ), safe_atoms)
        except Exception:
            self.error(traceback.format_exc())

    def _emit(
        self,
        emit: Callable[..., None],
        message: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        if carries_upstream_target(message, args):
            return  # suppressed: absence is proven by the containerized tests
        emit(message, *args, **kwargs)

    def critical(self, msg, *args, **kwargs) -> None:
        self._emit(self.error_log.critical, msg, args, kwargs)

    def error(self, msg, *args, **kwargs) -> None:
        self._emit(self.error_log.error, msg, args, kwargs)

    def warning(self, msg, *args, **kwargs) -> None:
        self._emit(self.error_log.warning, msg, args, kwargs)

    def exception(self, msg, *args, **kwargs) -> None:
        self._emit(self.error_log.exception, msg, args, kwargs)
