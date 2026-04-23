"""Tests for chunking contract: build_chunks_for_interval from path2.py (Slice S5).

Validates the operational contract that long windows (>29 days) are fragmented
into deterministic chunks of at most 15 days with configured overlap.

TDD: tests first (RED), then verify (GREEN), then refactor.

Reference spec: evolution-ingestion-on-demand —
"Long windows are chunked for source-system compatibility"
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import chunking module (dependency-free, no Playwright/Django imports)
# ---------------------------------------------------------------------------

_CHUNKING_FILE = (
    Path(__file__).resolve().parents[2]
    / "automation"
    / "source_system"
    / "medical_evolution"
    / "chunking.py"
)

_spec = importlib.util.spec_from_file_location("_chunking", _CHUNKING_FILE)  # noqa: E402
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

MAX_CHUNK_DAYS: int = _mod.MAX_CHUNK_DAYS
CHUNK_OVERLAP_DAYS: int = _mod.CHUNK_OVERLAP_DAYS
build_chunks_for_interval = _mod.build_chunks_for_interval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_in_chunk(chunk: tuple[date, date]) -> int:
    """Return inclusive day count of a (start, end) chunk."""
    return (chunk[1] - chunk[0]).days + 1


# ---------------------------------------------------------------------------
# 1. Basic contract — no chunk exceeds MAX_CHUNK_DAYS (15)
# ---------------------------------------------------------------------------


class TestChunkSizeLimit:
    """Every chunk produced by build_chunks_for_interval must be <= 15 days."""

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 1)),      # 1 day
            (date(2024, 1, 1), date(2024, 1, 15)),      # exactly 15 days
            (date(2024, 1, 1), date(2024, 1, 16)),      # 16 days
            (date(2024, 1, 1), date(2024, 1, 29)),      # 29 days
            (date(2024, 1, 1), date(2024, 1, 30)),      # 30 days (>29)
            (date(2024, 1, 1), date(2024, 3, 1)),       # 61 days
            (date(2024, 1, 1), date(2024, 6, 30)),      # 182 days (very long)
            (date(2023, 6, 15), date(2024, 6, 14)),     # 366 days (leap year)
        ],
        ids=lambda v: str(v),
    )
    def test_no_chunk_exceeds_max_days(self, start: date, end: date):
        chunks = build_chunks_for_interval(start, end)
        for i, chunk in enumerate(chunks):
            assert _days_in_chunk(chunk) <= MAX_CHUNK_DAYS, (
                f"Chunk {i+1} of ({start} to {end}) has "
                f"{_days_in_chunk(chunk)} days, exceeding {MAX_CHUNK_DAYS}"
            )

    def test_every_chunk_in_large_period_under_limit(self):
        """Period of 6 months must produce only chunks <= 15 days."""
        start = date(2024, 1, 1)
        end = date(2024, 6, 30)
        chunks = build_chunks_for_interval(start, end)

        assert len(chunks) > 0, "Must produce at least one chunk"
        for chunk in chunks:
            assert _days_in_chunk(chunk) <= MAX_CHUNK_DAYS


# ---------------------------------------------------------------------------
# 2. Full coverage — union of chunks covers the entire requested range
# ---------------------------------------------------------------------------


class TestChunkCoverage:
    """The union of all chunks must cover start to end without gaps."""

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 30)),      # 30 days
            (date(2024, 1, 1), date(2024, 3, 1)),        # 61 days
            (date(2024, 1, 1), date(2024, 6, 30)),       # 182 days
        ],
        ids=lambda v: str(v),
    )
    def test_first_chunk_starts_at_requested_start(self, start: date, end: date):
        chunks = build_chunks_for_interval(start, end)
        assert chunks[0][0] == start

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 30)),
            (date(2024, 1, 1), date(2024, 3, 1)),
            (date(2024, 1, 1), date(2024, 6, 30)),
        ],
        ids=lambda v: str(v),
    )
    def test_last_chunk_ends_at_requested_end(self, start: date, end: date):
        chunks = build_chunks_for_interval(start, end)
        assert chunks[-1][1] == end

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 30)),
            (date(2024, 1, 1), date(2024, 3, 1)),
            (date(2024, 1, 1), date(2024, 6, 30)),
        ],
        ids=lambda v: str(v),
    )
    def test_no_gaps_between_chunks(self, start: date, end: date):
        """Each chunk's start must be <= previous chunk's end + 1 (no uncovered days)."""
        chunks = build_chunks_for_interval(start, end)

        for i in range(1, len(chunks)):
            prev_end = chunks[i - 1][1]
            curr_start = chunks[i][0]
            # Because of overlap, curr_start should be <= prev_end + 1
            assert curr_start <= prev_end + timedelta(days=1), (
                f"Gap detected between chunk {i} and {i+1}: "
                f"prev_end={prev_end}, curr_start={curr_start}"
            )


# ---------------------------------------------------------------------------
# 3. Deterministic chunking — same input always produces same output
# ---------------------------------------------------------------------------


class TestChunkDeterminism:
    """build_chunks_for_interval must be deterministic."""

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 30)),
            (date(2024, 1, 1), date(2024, 6, 30)),
            (date(2024, 3, 15), date(2024, 9, 20)),
        ],
        ids=lambda v: str(v),
    )
    def test_repeated_calls_produce_same_result(self, start: date, end: date):
        result1 = build_chunks_for_interval(start, end)
        result2 = build_chunks_for_interval(start, end)
        assert result1 == result2

    def test_long_period_30_days_deterministic(self):
        """30-day period (>29 days) must always produce the same chunk set."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 30)

        results = [build_chunks_for_interval(start, end) for _ in range(10)]
        for r in results[1:]:
            assert r == results[0]


# ---------------------------------------------------------------------------
# 4. Overlap contract — consecutive chunks overlap by CHUNK_OVERLAP_DAYS
# ---------------------------------------------------------------------------


class TestChunkOverlap:
    """Consecutive chunks must overlap by at least CHUNK_OVERLAP_DAYS."""

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2024, 1, 1), date(2024, 1, 30)),
            (date(2024, 1, 1), date(2024, 3, 1)),
            (date(2024, 1, 1), date(2024, 6, 30)),
        ],
        ids=lambda v: str(v),
    )
    def test_overlap_between_consecutive_chunks(self, start: date, end: date):
        chunks = build_chunks_for_interval(start, end)

        if len(chunks) < 2:
            pytest.skip("Single chunk — no overlap to verify")

        for i in range(1, len(chunks)):
            prev_end = chunks[i - 1][1]
            curr_start = chunks[i][0]
            overlap = (prev_end - curr_start).days + 1
            assert overlap >= CHUNK_OVERLAP_DAYS, (
                f"Overlap between chunk {i} and {i+1} is {overlap} days, "
                f"expected at least {CHUNK_OVERLAP_DAYS}"
            )


# ---------------------------------------------------------------------------
# 5. Edge cases — boundary conditions
# ---------------------------------------------------------------------------


class TestChunkEdgeCases:
    """Edge cases for build_chunks_for_interval."""

    def test_single_day_produces_one_chunk(self):
        chunks = build_chunks_for_interval(date(2024, 1, 1), date(2024, 1, 1))
        assert len(chunks) == 1
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 1))

    def test_exactly_15_days_produces_one_chunk(self):
        chunks = build_chunks_for_interval(date(2024, 1, 1), date(2024, 1, 15))
        assert len(chunks) == 1
        assert _days_in_chunk(chunks[0]) == 15

    def test_16_days_produces_two_chunks(self):
        chunks = build_chunks_for_interval(date(2024, 1, 1), date(2024, 1, 16))
        assert len(chunks) == 2

    def test_29_days_produces_two_chunks(self):
        chunks = build_chunks_for_interval(date(2024, 1, 1), date(2024, 1, 29))
        assert len(chunks) == 2
        for chunk in chunks:
            assert _days_in_chunk(chunk) <= MAX_CHUNK_DAYS

    def test_30_days_produces_at_least_two_chunks(self):
        """30 days (>29) is the boundary case mentioned in the spec."""
        chunks = build_chunks_for_interval(date(2024, 1, 1), date(2024, 1, 30))
        assert len(chunks) >= 2, "30 days must be split into multiple chunks"
        for chunk in chunks:
            assert _days_in_chunk(chunk) <= MAX_CHUNK_DAYS

    def test_inverted_range_returns_empty(self):
        """If end < start, should return empty list."""
        chunks = build_chunks_for_interval(date(2024, 1, 15), date(2024, 1, 1))
        assert chunks == []

    def test_equal_start_end_produces_single_chunk(self):
        chunks = build_chunks_for_interval(date(2024, 6, 15), date(2024, 6, 15))
        assert len(chunks) == 1
        assert chunks[0] == (date(2024, 6, 15), date(2024, 6, 15))


# ---------------------------------------------------------------------------
# 6. Long-period regression (>29 days) — spec requirement
# ---------------------------------------------------------------------------


class TestLongPeriodChunking:
    """Regression: periods > 29 days must always chunk correctly.

    This is the core contract from the evolution-ingestion-on-demand spec:
    "WHEN requested extraction window is longer than 15 days,
     THEN the connector splits execution into chunks of at most 15 days"
    """

    @pytest.mark.parametrize(
        "total_days",
        [30, 31, 45, 60, 90, 120, 180, 365, 366],
        ids=lambda d: f"{d}_days",
    )
    def test_long_period_all_chunks_under_limit(self, total_days: int):
        start = date(2024, 1, 1)
        end = start + timedelta(days=total_days - 1)
        chunks = build_chunks_for_interval(start, end)

        assert len(chunks) > 1, f"{total_days} days should produce multiple chunks"
        for i, chunk in enumerate(chunks):
            assert _days_in_chunk(chunk) <= MAX_CHUNK_DAYS, (
                f"Chunk {i+1}/{len(chunks)} for {total_days}-day period "
                f"has {_days_in_chunk(chunk)} days"
            )

    @pytest.mark.parametrize(
        "total_days",
        [30, 45, 60, 90, 180],
        ids=lambda d: f"{d}_days",
    )
    def test_long_period_full_coverage(self, total_days: int):
        """Union of chunks must cover the entire period without gaps."""
        start = date(2024, 1, 1)
        end = start + timedelta(days=total_days - 1)
        chunks = build_chunks_for_interval(start, end)

        assert chunks[0][0] == start
        assert chunks[-1][1] == end

        # Verify no gaps
        covered = set()
        for cs, ce in chunks:
            d = cs
            while d <= ce:
                covered.add(d)
                d += timedelta(days=1)

        expected = set()
        d = start
        while d <= end:
            expected.add(d)
            d += timedelta(days=1)

        missing = expected - covered
        assert not missing, f"Missing dates in coverage: {sorted(missing)[:5]}..."
