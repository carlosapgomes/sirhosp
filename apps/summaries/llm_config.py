"""Centralized LLM configuration from environment variables (STP-S3).

Loads phase 1 (fixed) and up to 4 phase 2 options from environment
variables. Provides typed accessors for the gateway and UI.

Exports:
    Phase1Config: immutable config for the canonical phase.
    Phase2Option: immutable config for a single phase-2 LLM option.
    LLMConfigError: raised when required env vars are missing.
    load_phase1_config: load the fixed phase-1 configuration.
    load_phase2_options: load enabled phase-2 options.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase1Config:
    """Fixed LLM configuration for the canonical phase 1.

    All fields are required.  Missing or empty values cause
    ``LLMConfigError`` at load time.
    """

    provider: str
    model: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class Phase2Option:
    """A single enabled LLM option for the render phase 2.

    Only options with ``enabled=True`` are returned by
    ``load_phase2_options``.  Options missing required fields
    (provider, model, base_url, api_key) are silently excluded
    even when ``enabled`` is set.
    """

    label: str
    provider: str
    model: str
    base_url: str
    api_key: str
    enabled: bool = True


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMConfigError(RuntimeError):
    """Raised when required LLM configuration is missing or invalid."""


# ---------------------------------------------------------------------------
# Phase 1 loader
# ---------------------------------------------------------------------------

_PHASE1_REQUIRED = [
    "SUMMARY_PHASE1_PROVIDER",
    "SUMMARY_PHASE1_MODEL",
    "SUMMARY_PHASE1_BASE_URL",
    "SUMMARY_PHASE1_API_KEY",
]


def load_phase1_config() -> Phase1Config:
    """Load required phase 1 LLM configuration from environment.

    Required env vars:

    * ``SUMMARY_PHASE1_PROVIDER``
    * ``SUMMARY_PHASE1_MODEL``
    * ``SUMMARY_PHASE1_BASE_URL``
    * ``SUMMARY_PHASE1_API_KEY``

    Returns:
        ``Phase1Config`` with all values set.

    Raises:
        LLMConfigError: If any required variable is missing or empty.
    """
    missing: list[str] = []
    values: dict[str, str] = {}

    for key in _PHASE1_REQUIRED:
        raw = os.environ.get(key, "")
        if not raw.strip():
            missing.append(key)
        else:
            values[key] = raw.strip()

    if missing:
        raise LLMConfigError(
            f"Missing or empty required phase-1 environment variables: "
            f"{', '.join(missing)}"
        )

    return Phase1Config(
        provider=values["SUMMARY_PHASE1_PROVIDER"],
        model=values["SUMMARY_PHASE1_MODEL"],
        base_url=values["SUMMARY_PHASE1_BASE_URL"],
        api_key=values["SUMMARY_PHASE1_API_KEY"],
    )


# ---------------------------------------------------------------------------
# Phase 2 loader
# ---------------------------------------------------------------------------

_MAX_PHASE2_OPTIONS = 4


def load_phase2_options() -> list[Phase2Option]:
    """Load configured phase 2 LLM options from environment.

    Reads up to 4 options from env vars with the pattern
    ``SUMMARY_PHASE2_OPTION_N_*`` where ``N`` is 1..4.

    Only options that meet **all** of the following criteria are returned:

    1. ``SUMMARY_PHASE2_OPTION_N_ENABLED`` equals ``true`` / ``True`` / ``1``
       (case-insensitive).
    2. All required fields (PROVIDER, MODEL, BASE_URL, API_KEY) are present
       and non-empty.

    Options that are disabled or have missing required fields are silently
    excluded.

    Returns:
        List of enabled ``Phase2Option`` instances (may be empty).
    """
    options: list[Phase2Option] = []

    for n in range(1, _MAX_PHASE2_OPTIONS + 1):
        prefix = f"SUMMARY_PHASE2_OPTION_{n}"

        enabled_raw = os.environ.get(f"{prefix}_ENABLED", "false").strip().lower()
        if enabled_raw not in ("true", "1"):
            continue

        provider = os.environ.get(f"{prefix}_PROVIDER", "").strip()
        model = os.environ.get(f"{prefix}_MODEL", "").strip()
        base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip()
        api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()

        # All required fields must be present and non-empty.
        if not all([provider, model, base_url, api_key]):
            continue

        label = os.environ.get(f"{prefix}_LABEL", "").strip()

        options.append(
            Phase2Option(
                label=label,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                enabled=True,
            )
        )

    return options
