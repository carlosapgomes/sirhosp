"""Lookup-only template helpers for patient-flow findings (PFIF-S4).

The bulk findings map is built once per page render by the view, using the
PFIF-S3 classifier service. This module only resolves a key inside that
already-computed map so templates can render the badge. It performs no ORM
access, holds no classification rule, computes no age/48h/sector logic and
duplicates no label.
"""

from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.simple_tag(name="finding_for")
def finding_for(findings_map: dict[str, Any] | None, key: Any) -> Any:
    """Return the finding for ``key`` in the bulk map, or ``None``.

    Keys are census registros (prontuários); a blank key never matches.
    """
    if not findings_map or not key:
        return None
    return findings_map.get(str(key))
