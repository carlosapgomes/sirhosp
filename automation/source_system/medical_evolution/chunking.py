"""Chunking utilities for splitting long date ranges into operational chunks.

This module is dependency-free (no Playwright, Django, or external imports)
so it can be safely imported by both the automation connector and the test suite.

Contract:
- Each chunk covers at most MAX_CHUNK_DAYS (15) days (inclusive).
- Consecutive chunks overlap by CHUNK_OVERLAP_DAYS (1) day to avoid edge losses.
- Chunk boundaries are deterministic for the same input range.
"""

from __future__ import annotations

from datetime import date, timedelta

MAX_CHUNK_DAYS: int = 15
CHUNK_OVERLAP_DAYS: int = 1


def build_chunks_for_interval(start: date, end: date) -> list[tuple[date, date]]:
    """Split a date range into chunks of at most MAX_CHUNK_DAYS.

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        List of (chunk_start, chunk_end) tuples covering the full range.
        Returns empty list if end < start.
    """
    if end < start:
        return []

    chunks: list[tuple[date, date]] = []
    cursor = start

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=MAX_CHUNK_DAYS - 1), end)
        chunks.append((cursor, chunk_end))

        if chunk_end >= end:
            break

        next_cursor = chunk_end - timedelta(days=CHUNK_OVERLAP_DAYS - 1)
        if next_cursor <= cursor:
            next_cursor = cursor + timedelta(days=1)

        cursor = next_cursor

    return chunks
