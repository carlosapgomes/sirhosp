from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.ingestion.services import (
    queue_admissions_only_run,
    queue_demographics_only_run,
)
from apps.patients.models import Admission, Patient

if TYPE_CHECKING:
    from apps.discharges.models import DischargeRecord

logger = logging.getLogger(__name__)


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
    ref_date = _operational_date(ref)

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
            # Date-based idempotency: already closed on the same operational day
            if _operational_date(exact_admission.discharge_date) == ref_date:
                return exact_admission

    # Fallback: most recent still-open admission
    open_admission = (
        Admission.objects.filter(
            patient=patient,
            discharge_date__isnull=True,
        )
        .order_by("-admission_date")
        .first()
    )
    if open_admission is not None:
        return open_admission

    # Final fallback: any admission closed on the same operational day.
    # Prevents creating a recovery admission when an admission with a
    # different admission_date was already closed on the same date.
    same_day_closed = (
        Admission.objects.filter(
            patient=patient,
            discharge_date__date=ref_date,
        )
        .order_by("-admission_date")
        .first()
    )
    return same_day_closed


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


def _operational_date(value: datetime) -> date:
    operational_tz = timezone.get_default_timezone()
    if timezone.is_naive(value):
        value = timezone.make_aware(value, operational_tz)
    return timezone.localdate(value, timezone=operational_tz)


def _build_recovery_admission_date(
    *,
    parsed_admission_date: date | None,
    discharge_datetime: datetime,
) -> datetime:
    if parsed_admission_date is None:
        return discharge_datetime

    naive = datetime.combine(parsed_admission_date, datetime.min.time())
    return timezone.make_aware(naive, timezone.get_default_timezone())


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
    discharge_part = _operational_date(discharge_datetime).isoformat()
    raw = f"recovery|tasy|{patient_record}|{admission_part}|{discharge_part}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"recovery-{patient_record}-{admission_part}-{discharge_part}-{digest}"


# ---------------------------------------------------------------------------
# Canonical exit reconciliation (RPSA-S2)
# ---------------------------------------------------------------------------


def reconcile_discharge_record(
    *,
    record: DischargeRecord,
    source_system: str = "tasy",
) -> str:
    """Offer one persisted ``DischargeRecord`` to canonical reconciliation.

    Uses only the identifiers/precision present in the discharge XLS
    shape: patient record plus ``America/Bahia`` local admission date
    (``data_internacao``) plus the effective exit (``saida_em``). The
    report has no admission key and no exact admission start, so the
    key/alias/exact-start matching levels are skipped, never synthesized.
    ``alta_em`` is never used here: a row without ``saida_em`` stays
    pending evidence and cannot close an admission.

    Evidence linkage/status is written in the same transaction as the
    admission mutation and the append-only audit. Missing mirror data
    results in a bounded, deduplicated source-synchronization request —
    never a synthetic patient or admission. Logs carry aggregate-safe
    fields only (record primary key and status), never patient identity.

    Returns the final reconciliation status (one of
    ``apps.patients.models.RECONCILIATION_STATUSES``).
    """
    from apps.patients.models import (  # noqa: PLC0415
        EXIT_HOSPITAL_DISCHARGE,
        RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
        RECONCILIATION_STATUS_ALREADY_RECONCILED,
        RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
        RECONCILIATION_STATUS_RECONCILED,
    )
    from apps.patients.reconciliation import (  # noqa: PLC0415
        EVIDENCE_SOURCE_DISCHARGE_RECORD,
        DischargeExitEvidence,
        apply_discharge_exit,
        decide_discharge_match,
    )

    exit_datetime = record.saida_em
    if exit_datetime is not None and timezone.is_naive(exit_datetime):
        exit_datetime = timezone.make_aware(exit_datetime)

    if exit_datetime is None:
        # Row lacks the effective exit: stays pending evidence. The
        # medical summary (alta_em) never closes an admission.
        logger.info(
            "discharge reconciliation skipped: record_id=%s status=%s",
            record.pk,
            record.reconciliation_status,
        )
        return record.reconciliation_status

    evidence = DischargeExitEvidence(
        patient_record=record.prontuario,
        exit_datetime=exit_datetime,
        admission_key=None,
        admission_start=None,
        admission_local_date=_parse_admission_date(record.data_internacao),
        source_system=source_system,
    )

    with transaction.atomic():
        decision = decide_discharge_match(evidence=evidence)
        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=exit_datetime,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind=EVIDENCE_SOURCE_DISCHARGE_RECORD,
            source_id=record.pk,
        )
        # Evidence-side linkage/status joins the same atomic block so a
        # crash can never close an admission while leaving the evidence
        # row stale.
        record.admission = (
            decision.admission
            if status in (
                RECONCILIATION_STATUS_RECONCILED,
                RECONCILIATION_STATUS_ALREADY_RECONCILED,
            )
            else None
        )
        record.reconciliation_status = status
        record.reconciled_at = timezone.now()
        record.save(
            update_fields=["admission", "reconciliation_status", "reconciled_at"],
        )

    if status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND:
        queued = _enqueue_missing_mirror_sync(
            record.prontuario,
            include_demographics=True,
        )
    elif status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND:
        queued = _enqueue_missing_mirror_sync(
            record.prontuario,
            include_demographics=False,
        )
    else:
        queued = {"admissions_only": 0, "demographics_only": 0}

    logger.info(
        "discharge reconciliation: record_id=%s status=%s "
        "admissions_sync_queued=%d demographics_sync_queued=%d",
        record.pk,
        status,
        queued["admissions_only"],
        queued["demographics_only"],
    )
    return status


def _enqueue_missing_mirror_sync(
    patient_record: str,
    *,
    include_demographics: bool,
) -> dict[str, int]:
    """Enqueue bounded, deduplicated source synchronization requests.

    At most one active (queued/running) run per intent and patient record
    is kept, so repeated unresolved evidence cannot flood the ingestion
    queue. No synthetic Patient/Admission is ever created from evidence.
    """
    from apps.ingestion.models import IngestionRun  # noqa: PLC0415

    active_intents = set(
        IngestionRun.objects.filter(
            status__in=("queued", "running"),
            intent__in=("admissions_only", "demographics_only"),
            parameters_json__patient_record=patient_record,
        ).values_list("intent", flat=True)
    )

    queued = {"admissions_only": 0, "demographics_only": 0}
    if "admissions_only" not in active_intents:
        queue_admissions_only_run(patient_record=patient_record)
        queued["admissions_only"] = 1
    if include_demographics and "demographics_only" not in active_intents:
        queue_demographics_only_run(patient_record=patient_record)
        queued["demographics_only"] = 1
    return queued
