"""Profession type normalization and display helpers."""

from __future__ import annotations

_CANONICAL_OVERRIDES = {
    "phisiotherapy": "fisioterapia",
    "physiotherapy": "fisioterapia",
}


def to_canonical_profession_type(profession_type: str | None) -> str:
    """Normalize profession type token to canonical value."""
    if not profession_type:
        return ""

    normalized = profession_type.strip().lower()
    return _CANONICAL_OVERRIDES.get(normalized, normalized)


def to_display_label(profession_type: str | None) -> str:
    """Return UI label for a profession type token."""
    return to_canonical_profession_type(profession_type)
