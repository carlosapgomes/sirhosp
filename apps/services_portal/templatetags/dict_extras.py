"""Template tags/filters for services_portal."""

from django import template

register = template.Library()


@register.filter
def dict_key(value: dict, key: str) -> str:
    """Access a dictionary key that may contain special characters.

    Usage in template: ``{{ record.raw_data|dict_key:"QUARTO/LEITO" }}``
    Works around Django's limitation of not supporting keys with ``/``,
    ``-`` or spaces in dot-notation lookups.
    """
    if not isinstance(value, dict):
        return ""
    return value.get(key, "")


@register.filter
def dict_keys(value: dict) -> list:
    """Return the keys of a dictionary, excluding known technical fields."""
    if not isinstance(value, dict):
        return []
    return list(value.keys())
