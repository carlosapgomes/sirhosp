"""Summary window planner — deterministic chunking with overlap (APS-S3).

Provides plan_windows() for splitting an admission timeline into
deterministic date windows suitable for LLM processing.

Rules:
  - generate/regenerate: start at admission_date.
  - update: start at prior_coverage_end - overlap_days + 1 (clamped to
    admission_date). If prior coverage already reaches or exceeds
    target_end_date, return empty list.
  - Each window is chunk_days long; consecutive windows overlap by
    overlap_days days. The final window is clamped to target_end_date.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def plan_windows(
    admission_date: date,
    target_end_date: date,
    *,
    mode: str = "generate",
    prior_coverage_end: Optional[date] = None,
    chunk_days: int = 5,
    overlap_days: int = 2,
) -> list[tuple[date, date]]:
    """Plan deterministic date windows for a summary run.

    Args:
        admission_date: Start of the admission.
        target_end_date: End of the target period (inclusive).
        mode: One of ``"generate"``, ``"update"``, ``"regenerate"``.
        prior_coverage_end: End date of previous coverage (required for
            ``"update"`` mode; ignored for ``"generate"`` and
            ``"regenerate"``).
        chunk_days: Length of each chunk window in days (default 5).
        overlap_days: Number of overlapping days between consecutive
            windows (default 2).

    Returns:
        Sorted list of ``(window_start, window_end)`` tuples.  Every
        ``window_end`` is guaranteed >= ``window_start`` and <=
        ``target_end_date``.
    """
    if chunk_days < 1:
        raise ValueError(f"chunk_days must be >= 1, got {chunk_days}")
    if overlap_days < 0:
        raise ValueError(f"overlap_days must be >= 0, got {overlap_days}")

    # ---- Determine effective start ----
    if mode == "update" and prior_coverage_end is not None:
        # Start from prior coverage_end - overlap + 1, but never before
        # admission_date.
        start = max(
            admission_date,
            prior_coverage_end - timedelta(days=overlap_days - 1),
        )
        # If coverage already reaches or exceeds the target, nothing to do.
        if prior_coverage_end >= target_end_date:
            return []
    else:
        # generate / regenerate (or update without prior coverage): start
        # from admission_date, ignoring any prior state.
        start = admission_date

    # If start is already past target_end_date, return empty.
    if start > target_end_date:
        return []

    # ---- Build windows with sliding step ----
    # step = max(1, chunk_days - overlap_days) so windows always advance.
    step = max(1, chunk_days - overlap_days)
    windows: list[tuple[date, date]] = []

    cursor = start
    while cursor <= target_end_date:
        window_start = cursor
        window_end = min(
            window_start + timedelta(days=chunk_days - 1),
            target_end_date,
        )
        windows.append((window_start, window_end))
        if window_end >= target_end_date:
            break
        cursor = window_start + timedelta(days=step)

    return windows
