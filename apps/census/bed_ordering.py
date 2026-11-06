"""Natural ordering of bed identifiers, shared by every bed list.

Bed labels sort by their alphanumeric segments, so ``2`` precedes ``10``
and ``UTI02`` precedes ``UTI10``; the raw lexicographic order of the
identifier text would place ``10`` before ``2``. This module is the single
home of that rule: the ``/beds/`` presentation and the daily statistics
report both consume it, so the two surfaces can never diverge.
"""

from __future__ import annotations

import re

_BED_TOKEN_RE = re.compile(r"(\d+)")


def _bed_tokens(bed: str) -> tuple[tuple[int, object], ...]:
    """Numeric-aware tokens of one bed label; digits sort before letters."""
    tokens: list[tuple[int, object]] = []
    for part in _BED_TOKEN_RE.split(bed):
        if not part:
            continue
        tokens.append((0, int(part)) if part.isdigit() else (1, part.upper()))
    return tuple(tokens)


def _normalized_text(value: str) -> str:
    """Normalized comparison text: strip, uppercase, collapse inner spaces."""
    return " ".join(value.split()).upper()


def natural_bed_key(bed: str) -> tuple[object, ...]:
    """Natural ordering key of one bed identifier alone.

    Rows without a bed come after every row with a bed.
    """
    cleaned = bed.strip()
    return (0 if cleaned else 1, _bed_tokens(cleaned))


def natural_bed_order_key(
    *, bed: str, name: str, record: str
) -> tuple[object, ...]:
    """Natural ordering key of one row that carries a bed.

    Bed labels sort naturally (see :func:`natural_bed_key`); normalized
    name and record break the remaining ties.
    """
    return (
        *natural_bed_key(bed),
        _normalized_text(name),
        record.strip(),
    )
