"""Canonical private origins for dev verification.

The CLI and the MCP recipe resolve both operational origins from one
private dotenv file outside the checkout. There is no compiled fallback,
no application ``.env`` lookup, no process-environment override and no
interpolation: the operator-owned file is the only source.

Resolution is pure string validation. It never creates the file, never
touches ``os.environ`` and never opens a socket: production is refused by
comparison, never probed. Diagnostics name the offending key and reason,
never the configured value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEV_KEY = "SIRHOSP_VERIFY_DEV_ORIGIN"
PROD_KEY = "SIRHOSP_VERIFY_PROD_ORIGIN"


def canonical_profile_path() -> Path:
    """The single private profile location, resolved per call.

    Computed at call time (not import time) so the home directory in
    effect for the process applies. Tests point ``HOME`` at a temporary
    directory; the CLI never passes an explicit path.
    """
    return Path.home() / ".config" / "sirhosp" / "verification.env"


class OriginConfigError(Exception):
    """A private origin is missing or unsafe; safe to show the operator."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"{key}: {reason}")
        self.key = key
        self.reason = reason


@dataclass(frozen=True)
class VerificationOrigins:
    """Validated, canonicalized operational origins. Immutable per open."""

    dev: str
    prod: str


def _read_profile(profile: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise OriginConfigError("profile", "origin configuration parser unavailable") from exc
    try:
        is_file = profile.is_file()
    except OSError as exc:
        raise OriginConfigError("profile", "origin configuration unreadable") from exc
    if not is_file:
        raise OriginConfigError("profile", "origin configuration file is missing")
    try:
        # No interpolation: a value is used exactly as the operator wrote it.
        values = dotenv_values(profile, interpolate=False)
    except (OSError, ValueError) as exc:
        raise OriginConfigError("profile", "origin configuration unreadable") from exc
    return {key: value for key, value in values.items() if isinstance(value, str)}


def _normalize_origin(key: str, raw: str) -> str:
    value = raw.strip()
    if not value:
        raise OriginConfigError(key, "origin is empty")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise OriginConfigError(key, "origin URL is invalid") from None
    if parts.scheme != "https":
        raise OriginConfigError(key, "origin must be an absolute https URL")
    host = (parts.hostname or "").strip().lower()
    # Strict hostname so interpolated fragments ("${...}", "$...") or
    # userinfo remnants can never slip through as an opaque valid host.
    labels = host.split(".")
    if not labels or any(
        not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", label) for label in labels
    ):
        raise OriginConfigError(key, "origin host is invalid")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise OriginConfigError(key, "origin must not carry userinfo")
    try:
        port = parts.port
    except ValueError:
        raise OriginConfigError(key, "origin port is invalid") from None
    if port is not None and (port < 1 or port > 65535):
        raise OriginConfigError(key, "origin port is invalid")
    if parts.query or parts.fragment:
        raise OriginConfigError(key, "origin must not carry query or fragment")
    if parts.path not in ("", "/"):
        raise OriginConfigError(key, "origin must not carry an application path")
    if port is None or port == 443:
        return f"https://{host}"
    return f"https://{host}:{port}"


def resolve_origins(profile_path: Path | str | None = None) -> VerificationOrigins:
    """Resolve and validate both origins from the private profile.

    ``profile_path`` exists only as a test seam; production callers use
    the canonical path. The process environment is never consulted.
    """
    profile = Path(profile_path) if profile_path is not None else canonical_profile_path()
    values = _read_profile(profile)
    dev_raw = values.get(DEV_KEY)
    if dev_raw is None:
        raise OriginConfigError(DEV_KEY, "origin is missing")
    prod_raw = values.get(PROD_KEY)
    if prod_raw is None:
        raise OriginConfigError(PROD_KEY, "origin is missing")
    dev = _normalize_origin(DEV_KEY, dev_raw)
    prod = _normalize_origin(PROD_KEY, prod_raw)
    if dev == prod:
        raise OriginConfigError(DEV_KEY, "dev origin matches the production origin")
    return VerificationOrigins(dev=dev, prod=prod)


def resolve_dev_origin(profile_path: Path | str | None = None) -> str:
    """The validated canonical dev origin; the only usable journey target."""
    return resolve_origins(profile_path).dev
