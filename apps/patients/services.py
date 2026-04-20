"""Patient navigation services (Slice S4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, QuerySet

from apps.patients.models import Admission, Patient

if TYPE_CHECKING:
    from apps.clinical_docs.models import ClinicalEvent


def get_patient_or_404(patient_id: int) -> Patient:
    """Get patient by ID or raise DoesNotExist."""
    return Patient.objects.get(pk=patient_id)


def list_admissions_for_patient(patient_id: int) -> QuerySet[Admission]:
    """List all admissions for a patient, ordered by date descending.

    Annotates each admission with event_count for display.
    """
    return (
        Admission.objects.filter(patient_id=patient_id)
        .annotate(event_count=Count("events"))
        .order_by("-admission_date")
    )


def get_admission_or_404(admission_id: int) -> Admission:
    """Get admission by ID with related patient, or raise DoesNotExist."""
    return Admission.objects.select_related("patient").get(pk=admission_id)


def list_events_for_admission(
    admission_id: int,
    profession_type: str | None = None,
) -> QuerySet[ClinicalEvent]:
    """List clinical events for an admission, optionally filtered by profession.

    Returns events ordered by happened_at descending (most recent first).
    """
    from apps.clinical_docs.models import ClinicalEvent

    qs = ClinicalEvent.objects.filter(admission_id=admission_id)

    if profession_type:
        qs = qs.filter(profession_type=profession_type)

    return qs.order_by("-happened_at")


def get_profession_types_for_admission(admission_id: int) -> list[str]:
    """Get distinct profession types present in an admission's events."""
    from apps.clinical_docs.models import ClinicalEvent

    return list(
        ClinicalEvent.objects.filter(admission_id=admission_id)
        .values_list("profession_type", flat=True)
        .distinct()
        .order_by("profession_type")
    )
