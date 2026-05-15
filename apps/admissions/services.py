"""Services for processing admission records."""

from __future__ import annotations

from datetime import date as Date


def process_admissions(
    records: list[dict[str, str | None]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process admission records from the XLS extraction.

    Currently persists the raw records as a DailyAdmissionCount snapshot.

    Args:
        records: List of dicts with admission record data from the XLS.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.admissions.models import DailyAdmissionCount

    DailyAdmissionCount.objects.update_or_create(
        date=reference_date,
        defaults={
            "count": len(records),
            "raw_data": records,
        },
    )

    return {
        "total_records": len(records),
    }
