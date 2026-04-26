"""Helpers for handling chunks without evolutions in path2 extraction flow."""

from __future__ import annotations

import re
from typing import Final

NO_EVOLUTIONS_WARNING_SUMMARY: Final[str] = (
    "Não existem Evoluções registradas no período informado"
)
EMPTY_CHUNK_STOP_THRESHOLD: Final[int] = 2


def is_no_evolutions_warning_message(message: str) -> bool:
    """Return True when text matches the source-system empty-evolutions warning."""
    normalized_message = re.sub(r"\s+", " ", (message or "").strip()).casefold()
    normalized_target = re.sub(
        r"\s+",
        " ",
        NO_EVOLUTIONS_WARNING_SUMMARY,
    ).casefold()
    return normalized_target in normalized_message


def update_empty_chunk_streak(
    *,
    previous_streak: int,
    chunk_has_report: bool,
    stop_threshold: int = EMPTY_CHUNK_STOP_THRESHOLD,
) -> tuple[int, bool]:
    """Update empty chunk streak and decide whether extraction should stop early."""
    if chunk_has_report:
        return 0, False

    next_streak = previous_streak + 1
    should_stop = stop_threshold > 0 and next_streak >= stop_threshold
    return next_streak, should_stop
