"""Services for processing death records."""

from __future__ import annotations

from datetime import date as Date


def process_deaths(
    records: list[dict[str, str]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process death records from the CSV extraction.

    Persists both the daily aggregate and individual DeathRecord rows.

    Args:
        records: List of dicts with death record data from the CSV.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.deaths.models import DailyDeathCount, DeathRecord

    daily_count, _created = DailyDeathCount.objects.update_or_create(
        date=reference_date,
        defaults={
            "count": len(records),
            "raw_data": records,
        },
    )

    # Delete old individual records and recreate
    daily_count.records.all().delete()

    for rec in records:
        prontuario = _find_value(rec, "PRONTUARIO", "prontuario", "Prontuário")
        nome = _find_value(rec, "NOME", "nome", "Paciente")
        data_obito = _find_value(
            rec,
            "OBITO",
            "DATA OBITO",
            "DATA_OBITO",
            "DATA ÓBITO",
            "data_obito",
            "Data Óbito",
        )

        extra = {
            k: v
            for k, v in rec.items()
            if k
            not in {
                "PRONTUARIO",
                "NOME",
                "OBITO",
                "DATA OBITO",
                "DATA_OBITO",
                "DATA ÓBITO",
                "prontuario",
                "nome",
                "data_obito",
                "Prontuário",
                "Paciente",
                "Data Óbito",
            }
            and v
        }

        DeathRecord.objects.create(
            daily_count=daily_count,
            date=reference_date,
            prontuario=str(prontuario or ""),
            nome=str(nome or ""),
            data_obito=str(data_obito or ""),
            raw_extra=extra,
        )

    return {
        "total_records": len(records),
    }


def _find_value(record: dict, *keys: str) -> str | None:
    """Try multiple possible key names for a field (case-insensitive fallback)."""
    for key in keys:
        if key in record:
            return record[key]

    for key in keys:
        norm = key.upper().replace(" ", "_")
        for rk in record:
            if rk.upper().replace(" ", "_") == norm:
                return record[rk]

    return None
