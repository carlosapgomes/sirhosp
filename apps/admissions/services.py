"""Services for processing admission records."""

from __future__ import annotations

from datetime import date as Date


def process_admissions(
    records: list[dict[str, str | None]],
    *,
    reference_date: Date,
) -> dict[str, int]:
    """Process admission records from the XLS extraction.

    Persists both the daily aggregate and individual AdmissionRecord rows.

    Args:
        records: List of dicts with admission record data from the XLS.
        reference_date: The date these records refer to.

    Returns:
        A dict with metrics counters.
    """
    from apps.admissions.models import AdmissionRecord, DailyAdmissionCount

    daily_count, _created = DailyAdmissionCount.objects.update_or_create(
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
        data_internacao = _find_value(
            rec,
            "DATA INTERNACAO",
            "DATA_INTERNACAO",
            "DATA INTERNAÇÃO",
            "data_internacao",
            "Data Internação",
        )

        extra = {
            k: v
            for k, v in rec.items()
            if k
            not in {
                "PRONTUARIO",
                "NOME",
                "DATA INTERNACAO",
                "DATA_INTERNACAO",
                "DATA INTERNAÇÃO",
                "prontuario",
                "nome",
                "data_internacao",
                "Prontuário",
                "Paciente",
                "Data Internação",
            }
            and v
        }

        AdmissionRecord.objects.create(
            daily_count=daily_count,
            date=reference_date,
            prontuario=str(prontuario or ""),
            nome=str(nome or ""),
            data_internacao=str(data_internacao or ""),
            raw_extra=extra,
        )

    return {
        "total_records": len(records),
    }


def _find_value(record: dict, *keys: str) -> str | None:
    """Try multiple possible key names for a field (case-insensitive fallback)."""
    # Direct match first
    for key in keys:
        if key in record:
            return record[key]

    # Case-insensitive fallback
    for key in keys:
        for rk in record:
            if rk.upper().replace(" ", "_") == key.upper().replace(" ", "_"):
                return record[rk]

    return None
