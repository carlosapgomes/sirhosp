from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.patients.models import Admission, Patient


def process_discharges(
    patients: list[dict[str, str]],
    *,
    discharge_date: datetime | None = None,
) -> dict[str, int]:
    """Process a list of discharged patients and update Admission.discharge_date.

    For each patient in the list:
      1. Look up Patient by patient_source_key (prontuario).
         If not found, skip and count as patient_not_found.
      2. Find the matching Admission by data_internacao, then fall back to
         the most recent admission without discharge_date.
      3. If the exact matching admission was already discharged in the last
         24 hours, skip and count as already_discharged.
      4. Set discharge_date and count as discharge_set.

    Args:
        patients: List of patient dicts from PDF extraction.
        discharge_date: Explicit discharge datetime. If None, uses timezone.now().
            Use this when reprocessing historical PDFs to preserve the correct date.
    """
    effective_discharge_date = discharge_date or timezone.now()
    total_pdf = len(patients)
    patient_not_found = 0
    admission_not_found = 0
    already_discharged = 0
    discharge_set = 0

    for patient_data in patients:
        prontuario = patient_data.get("prontuario", "").strip()
        data_internacao_str = patient_data.get("data_internacao", "").strip()

        if not prontuario:
            continue

        try:
            patient = Patient.objects.get(
                source_system="tasy",
                patient_source_key=prontuario,
            )
        except Patient.DoesNotExist:
            patient_not_found += 1
            continue

        admission = _find_admission(
            patient, data_internacao_str,
            reference_datetime=effective_discharge_date,
        )
        if admission is None:
            admission_not_found += 1
            continue

        if admission.discharge_date is not None:
            already_discharged += 1
            continue

        admission.discharge_date = effective_discharge_date
        admission.save(update_fields=["discharge_date", "updated_at"])
        discharge_set += 1

    return {
        "total_pdf": total_pdf,
        "patient_not_found": patient_not_found,
        "admission_not_found": admission_not_found,
        "already_discharged": already_discharged,
        "discharge_set": discharge_set,
    }


def _find_admission(
    patient: Patient,
    data_internacao_str: str,
    *,
    reference_datetime: datetime | None = None,
) -> Admission | None:
    parsed_date = _parse_admission_date(data_internacao_str)
    ref = reference_datetime or timezone.now()

    if parsed_date is not None:
        exact_admission = (
            Admission.objects.filter(
                patient=patient,
                admission_date__date=parsed_date,
            )
            .order_by("-admission_date")
            .first()
        )
        if exact_admission is not None:
            if exact_admission.discharge_date is None:
                return exact_admission
            if exact_admission.discharge_date >= ref - timedelta(hours=24):
                return exact_admission

    return (
        Admission.objects.filter(
            patient=patient,
            discharge_date__isnull=True,
        )
        .order_by("-admission_date")
        .first()
    )


def _parse_admission_date(raw_date: str) -> date | None:
    if not raw_date:
        return None

    try:
        return datetime.strptime(raw_date, "%d/%m/%Y").date()
    except (ValueError, OverflowError):
        return None
