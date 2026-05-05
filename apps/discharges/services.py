from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.ingestion.services import queue_demographics_only_run
from apps.patients.models import Admission, Patient


def process_discharges(
    patients: list[dict[str, str]],
    *,
    discharge_date: datetime | None = None,
) -> dict[str, int]:
    """Process discharged patients and reconcile missing mirror data.

    Recovery policy for gaps in local mirror:
      1. If patient is missing, create a minimal Patient and enqueue
         demographics_only ingestion.
      2. If matching admission is missing, create a synthetic admission period
         from PDF admission date to current extraction discharge date.
      3. Set discharge_date when admission is open.
    """
    effective_discharge_date = discharge_date or timezone.now()
    total_pdf = len(patients)
    patient_not_found = 0
    admission_not_found = 0
    already_discharged = 0
    discharge_set = 0
    recovered_patients_created = 0
    recovered_admissions_created = 0
    demographics_runs_enqueued = 0
    queued_demographics_records: set[str] = set()

    for patient_data in patients:
        prontuario = patient_data.get("prontuario", "").strip()
        nome = patient_data.get("nome", "").strip() or "PACIENTE SEM NOME"
        data_internacao_str = patient_data.get("data_internacao", "").strip()

        if not prontuario:
            continue

        patient = Patient.objects.filter(
            source_system="tasy",
            patient_source_key=prontuario,
        ).first()

        if patient is None:
            patient_not_found += 1
            patient = Patient.objects.create(
                source_system="tasy",
                patient_source_key=prontuario,
                name=nome,
            )
            recovered_patients_created += 1

            if prontuario not in queued_demographics_records:
                queue_demographics_only_run(patient_record=prontuario, batch=None)
                queued_demographics_records.add(prontuario)
                demographics_runs_enqueued += 1

        admission = _find_admission(
            patient,
            data_internacao_str,
            reference_datetime=effective_discharge_date,
        )
        if admission is None:
            admission_not_found += 1
            parsed_admission_date = _parse_admission_date(data_internacao_str)
            admission, created = _get_or_create_recovery_admission(
                patient=patient,
                patient_record=prontuario,
                patient_name=nome,
                parsed_admission_date=parsed_admission_date,
                discharge_datetime=effective_discharge_date,
            )
            if created:
                recovered_admissions_created += 1

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
        "recovered_patients_created": recovered_patients_created,
        "recovered_admissions_created": recovered_admissions_created,
        "demographics_runs_enqueued": demographics_runs_enqueued,
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


def _get_or_create_recovery_admission(
    *,
    patient: Patient,
    patient_record: str,
    patient_name: str,
    parsed_admission_date: date | None,
    discharge_datetime: datetime,
) -> tuple[Admission, bool]:
    source_admission_key = _build_recovery_admission_key(
        patient_record=patient_record,
        parsed_admission_date=parsed_admission_date,
        discharge_datetime=discharge_datetime,
    )

    admission_date = _build_recovery_admission_date(
        parsed_admission_date=parsed_admission_date,
        discharge_datetime=discharge_datetime,
    )

    admission, created = Admission.objects.get_or_create(
        source_system="tasy",
        source_admission_key=source_admission_key,
        defaults={
            "patient": patient,
            "admission_date": admission_date,
            "discharge_date": None,
            "source_patient_reference": patient_record,
            "ward": "",
            "bed": "",
        },
    )

    if not created and admission.patient_id != patient.pk:
        # Defensive guard against unexpected collision.
        admission.patient = patient
        admission.save(update_fields=["patient", "updated_at"])

    if patient.name == "PACIENTE SEM NOME" and patient_name and patient_name != "PACIENTE SEM NOME":
        patient.name = patient_name
        patient.save(update_fields=["name", "updated_at"])

    return admission, created


def _build_recovery_admission_date(
    *,
    parsed_admission_date: date | None,
    discharge_datetime: datetime,
) -> datetime:
    if parsed_admission_date is None:
        return discharge_datetime

    naive = datetime.combine(parsed_admission_date, datetime.min.time())
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _build_recovery_admission_key(
    *,
    patient_record: str,
    parsed_admission_date: date | None,
    discharge_datetime: datetime,
) -> str:
    admission_part = (
        parsed_admission_date.isoformat()
        if parsed_admission_date is not None
        else "unknown"
    )
    discharge_part = discharge_datetime.date().isoformat()
    raw = f"recovery|tasy|{patient_record}|{admission_part}|{discharge_part}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"recovery-{patient_record}-{admission_part}-{discharge_part}-{digest}"
