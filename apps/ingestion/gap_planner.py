"""Temporal coverage and gap planning for cache-first ingestion (Slice S3).

Calculates which date-ranges within a requested window already have events
stored in the database, returning the gaps (sub-ranges with no coverage)
so the worker can extract only what is missing.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.utils import timezone as dj_timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.patients.models import Patient


def compute_coverage_gaps(
    *,
    patient_source_key: str,
    source_system: str,
    start_date: str,
    end_date: str,
    overlap_days: int = 1,
) -> list[dict[str, str]]:
    """Compute date-ranges with no existing events for a patient.

    Queries ClinicalEvent dates (day granularity, institutional timezone)
    for the given patient and returns contiguous gap windows where no
    events exist.

    Args:
        patient_source_key: Patient record identifier.
        source_system: Source system identifier (e.g. "tasy").
        start_date: Requested window start (YYYY-MM-DD).
        end_date: Requested window end (YYYY-MM-DD).
        overlap_days: Days to extend the first gap backward to capture
            events registered after the last extraction (default: 1).

    Returns:
        List of dicts with "start_date" and "end_date" keys representing
        contiguous date-ranges with no coverage. Empty list means full
        coverage.
    """
    window_start = date.fromisoformat(start_date)
    window_end = date.fromisoformat(end_date)

    # Build set of dates within the window that have events
    covered_dates: set[date] = set()

    patient = Patient.objects.filter(
        patient_source_key=patient_source_key,
        source_system=source_system,
    ).first()

    if patient is not None:
        events = ClinicalEvent.objects.filter(
            patient=patient,
            happened_at__date__gte=window_start,
            happened_at__date__lte=window_end,
        ).values_list("happened_at", flat=True)

        for happened_at in events:
            covered_dates.add(dj_timezone.localtime(happened_at).date())

    # Build all dates in the window
    all_dates: list[date] = []
    current = window_start
    while current <= window_end:
        all_dates.append(current)
        current += timedelta(days=1)

    # Find uncovered dates and group into contiguous gaps
    uncovered = [d for d in all_dates if d not in covered_dates]

    gaps = _group_contiguous_dates(uncovered)

    # Extend the first gap backward by overlap_days to capture events
    # registered after the last extraction (e.g. census ran at 21:00 but
    # events were created at 22:30 on a date already marked as covered).
    if overlap_days > 0 and gaps:
        extended_start = max(
            window_start,
            date.fromisoformat(gaps[0]["start_date"]) - timedelta(days=overlap_days),
        )
        gaps[0]["start_date"] = extended_start.isoformat()

    return gaps


def plan_extraction_windows(
    *,
    patient_source_key: str,
    source_system: str,
    start_date: str,
    end_date: str,
    overlap_days: int = 1,
) -> dict[str, Any]:
    """Determine extraction plan based on existing coverage.

    Args:
        patient_source_key: Patient record identifier.
        source_system: Source system identifier.
        start_date: Requested window start (YYYY-MM-DD).
        end_date: Requested window end (YYYY-MM-DD).
        overlap_days: Days to extend the first gap backward.

    Returns:
        Dict with:
            - skip_extraction: True if full coverage (no extraction needed).
            - windows: List of date-range dicts to extract (gaps).
            - gaps: Same as windows (alias for audit/logging).
    """
    gaps = compute_coverage_gaps(
        patient_source_key=patient_source_key,
        source_system=source_system,
        start_date=start_date,
        end_date=end_date,
        overlap_days=overlap_days,
    )

    return {
        "skip_extraction": len(gaps) == 0,
        "windows": gaps,
        "gaps": gaps,
    }


def _group_contiguous_dates(dates: list[date]) -> list[dict[str, str]]:
    """Group a sorted list of dates into contiguous windows.

    Args:
        dates: List of date objects (should be sorted ascending).

    Returns:
        List of dicts with "start_date" and "end_date" (ISO format strings).
    """
    if not dates:
        return []

    sorted_dates = sorted(dates)
    gaps: list[dict[str, str]] = []
    gap_start = sorted_dates[0]
    prev = sorted_dates[0]

    for d in sorted_dates[1:]:
        if (d - prev).days > 1:
            # Gap ended — emit the previous contiguous block
            gaps.append({
                "start_date": gap_start.isoformat(),
                "end_date": prev.isoformat(),
            })
            gap_start = d
        prev = d

    # Emit the last block
    gaps.append({
        "start_date": gap_start.isoformat(),
        "end_date": prev.isoformat(),
    })

    return gaps
