"""Template filters for profession-type labels."""

from __future__ import annotations

from django import template

from apps.core.profession_types import to_display_label

register = template.Library()


@register.filter(name="profession_label")
def profession_label(value: str | None) -> str:
    """Render profession type token with UI-friendly label."""
    return to_display_label(value)
