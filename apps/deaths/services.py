"""Services for processing death records."""

from __future__ import annotations

from datetime import date as Date


def process_deaths(
    records: list[dict[str, str]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process death records from the CSV extraction.

    Currently a minimal placeholder — persists the raw records
    as a DailyDeathCount snapshot.

    Args:
        records: List of dicts with death record data from the CSV.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.deaths.models import DailyDeathCount

    DailyDeathCount.objects.update_or_create(
        date=reference_date,
        defaults={
            "count": len(records),
            "raw_data": records,
        },
    )

    return {
        "total_records": len(records),
    }
