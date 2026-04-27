"""Tests for summary window planner (APS-S3 RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Helpers – kept minimal; no Django DB needed for pure computation
# ---------------------------------------------------------------------------


def _plan(admission_date, target_end_date, **kwargs):
    """Import and call the planner (imported inside each test to allow
    running before the planner module exists)."""
    from apps.summaries.planner import plan_windows

    return plan_windows(admission_date, target_end_date, **kwargs)


# ---------------------------------------------------------------------------
# Generate mode (no prior state)
# ---------------------------------------------------------------------------


class TestGenerateMode:
    """Backfill / initial generation: windows start at admission_date."""

    def test_generate_single_chunk_short_period(self):
        """When the period is shorter than chunk_days, one window covers it all."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 3),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        assert windows == [(date(2025, 1, 1), date(2025, 1, 3))]

    def test_generate_two_chunks_with_overlap(self):
        """Chunks of 5 days with overlap 2 across a 10-day period."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 10),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        # W0: Jan 1-5; W1: Jan 4-8 (start=prev_end-overlap+1=5-2+1=4); W2: Jan 7-10
        assert windows == [
            (date(2025, 1, 1), date(2025, 1, 5)),
            (date(2025, 1, 4), date(2025, 1, 8)),
            (date(2025, 1, 7), date(2025, 1, 10)),
        ]

    def test_generate_many_chunks_long_admission(self):
        """Long admission gets deterministic windows in order."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 20),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        expected = [
            (date(2025, 1, 1), date(2025, 1, 5)),
            (date(2025, 1, 4), date(2025, 1, 8)),
            (date(2025, 1, 7), date(2025, 1, 11)),
            (date(2025, 1, 10), date(2025, 1, 14)),
            (date(2025, 1, 13), date(2025, 1, 17)),
            (date(2025, 1, 16), date(2025, 1, 20)),
        ]
        assert windows == expected

    def test_generate_last_window_clamped_to_target_end(self):
        """Last window should not exceed target_end_date."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 9),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        # W0: 1-5, W1: 4-8, W2: 7-9 (clamped)
        assert windows == [
            (date(2025, 1, 1), date(2025, 1, 5)),
            (date(2025, 1, 4), date(2025, 1, 8)),
            (date(2025, 1, 7), date(2025, 1, 9)),
        ]

    def test_generate_windows_are_ordered(self):
        """Windows must be sorted by start date ascending."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 30),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        starts = [w[0] for w in windows]
        assert starts == sorted(starts)
        assert len(windows) > 1

    def test_generate_with_different_chunk_sizes(self):
        """Planner respects non-default chunk_days and overlap_days."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 12),
            mode="generate",
            chunk_days=7,
            overlap_days=3,
        )
        # step=4 → W0: 1-7, W1: 5-11, W2: 9-12 (clamped)
        assert windows == [
            (date(2025, 1, 1), date(2025, 1, 7)),
            (date(2025, 1, 5), date(2025, 1, 11)),
            (date(2025, 1, 9), date(2025, 1, 12)),
        ]


# ---------------------------------------------------------------------------
# Update mode (prior coverage exists)
# ---------------------------------------------------------------------------


class TestUpdateMode:
    """Incremental update: starts from prior coverage_end minus overlap."""

    def test_update_starts_from_coverage_end_minus_overlap_plus_one(self):
        """Update mode begins at coverage_end - overlap + 1."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 15),
            mode="update",
            prior_coverage_end=date(2025, 1, 5),
            chunk_days=5,
            overlap_days=2,
        )
        # coverage_end=5, overlap=2 → start = 5-2+1 = 4
        assert windows[0][0] == date(2025, 1, 4)

    def test_update_does_not_go_before_admission_date(self):
        """Update start is clamped to admission_date."""
        windows = _plan(
            admission_date=date(2025, 2, 1),
            target_end_date=date(2025, 2, 15),
            mode="update",
            prior_coverage_end=date(2025, 1, 25),
            chunk_days=5,
            overlap_days=2,
        )
        # prior_coverage_end is before admission_date → clamp to admission_date
        assert windows[0][0] == date(2025, 2, 1)

    def test_update_with_coverage_already_at_target(self):
        """When coverage already reaches target, return empty list."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 5),
            mode="update",
            prior_coverage_end=date(2025, 1, 5),
            chunk_days=5,
            overlap_days=2,
        )
        assert windows == []

    def test_update_with_coverage_after_target(self):
        """When coverage exceeds target, return empty list."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 5),
            mode="update",
            prior_coverage_end=date(2025, 1, 10),
            chunk_days=5,
            overlap_days=2,
        )
        assert windows == []

    def test_update_generates_correct_chunks(self):
        """Update produces the right windows from overlap start to target."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 18),
            mode="update",
            prior_coverage_end=date(2025, 1, 10),
            chunk_days=5,
            overlap_days=2,
        )
        # start = 10-2+1 = 9
        assert windows == [
            (date(2025, 1, 9), date(2025, 1, 13)),
            (date(2025, 1, 12), date(2025, 1, 16)),
            (date(2025, 1, 15), date(2025, 1, 18)),
        ]


# ---------------------------------------------------------------------------
# Regenerate mode (full reprocessing regardless of prior state)
# ---------------------------------------------------------------------------


class TestRegenerateMode:
    """Regenerate ignores prior state and starts from admission_date."""

    def test_regenerate_ignores_prior_coverage(self):
        """Even with prior_coverage_end provided, regenerate starts at
        admission_date."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 10),
            mode="regenerate",
            prior_coverage_end=date(2025, 1, 5),
            chunk_days=5,
            overlap_days=2,
        )
        assert windows[0][0] == date(2025, 1, 1)
        assert windows == [
            (date(2025, 1, 1), date(2025, 1, 5)),
            (date(2025, 1, 4), date(2025, 1, 8)),
            (date(2025, 1, 7), date(2025, 1, 10)),
        ]

    def test_regenerate_same_as_generate(self):
        """Regenerate produces the same windows as generate for the same input."""
        gen_windows = _plan(
            admission_date=date(2025, 3, 1),
            target_end_date=date(2025, 3, 12),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        reg_windows = _plan(
            admission_date=date(2025, 3, 1),
            target_end_date=date(2025, 3, 12),
            mode="regenerate",
            chunk_days=5,
            overlap_days=2,
        )
        assert gen_windows == reg_windows


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestPlannerEdgeCases:
    """Edge case scenarios for the window planner."""

    def test_single_day_period(self):
        """Admission and target end on the same day → one window."""
        windows = _plan(
            admission_date=date(2025, 1, 10),
            target_end_date=date(2025, 1, 10),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        assert windows == [(date(2025, 1, 10), date(2025, 1, 10))]

    def test_each_window_has_correct_duration(self):
        """Every window (except possibly last) is exactly chunk_days long."""
        windows = _plan(
            admission_date=date(2025, 6, 1),
            target_end_date=date(2025, 6, 20),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        for idx, (start, end) in enumerate(windows):
            duration = (end - start).days + 1
            if idx < len(windows) - 1:
                assert duration == 5, f"Window {idx}: {start}..{end} is {duration} days"
            else:
                assert duration <= 5, f"Last window {idx}: {start}..{end} is {duration} > 5 days"

    def test_overlap_is_respected(self):
        """Consecutive windows have the expected overlap."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 30),
            mode="generate",
            chunk_days=5,
            overlap_days=2,
        )
        for i in range(len(windows) - 1):
            prev_end = windows[i][1]
            next_start = windows[i + 1][0]
            overlap = (prev_end - next_start).days + 1
            assert overlap == 2, (
                f"Window {i} ({windows[i]}) → Window {i + 1} ({windows[i + 1]}): "
                f"overlap={overlap}, expected 2"
            )

    def test_large_overlap(self):
        """Overlap >= chunk_days → each window advances by 1 day (degenerate)."""
        windows = _plan(
            admission_date=date(2025, 1, 1),
            target_end_date=date(2025, 1, 5),
            mode="generate",
            chunk_days=3,
            overlap_days=3,
        )
        # With step = max(1, chunk_days - overlap_days) = max(1, 0) = 1
        # W0: 1-3, W1: 2-4, W2: 3-5
        assert windows == [
            (date(2025, 1, 1), date(2025, 1, 3)),
            (date(2025, 1, 2), date(2025, 1, 4)),
            (date(2025, 1, 3), date(2025, 1, 5)),
        ]
