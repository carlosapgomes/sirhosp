"""Patient navigation services (Slice S4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, Q, QuerySet

from apps.patients.models import Admission, Patient

if TYPE_CHECKING:
    from apps.clinical_docs.models import ClinicalEvent


def search_patients_with_coverage(
    query: str | None = None,
) -> QuerySet[Patient]:
    """Search patients annotated with admission coverage metrics.

    Returns patients ordered by name, each annotated with:
      - admissions_total: count of all known admissions
      - admissions_with_events: count of admissions that have at least 1 event

    The "without events" count is computed in the template as
    total - with_events to keep the SQL simple.
    """
    qs = Patient.objects.annotate(
        admissions_total=Count("admissions"),
        admissions_with_events=Count(
            "admissions",
            filter=Q(admissions__events__isnull=False),
        ),
        admissions_without_events=(
            Count("admissions")
            - Count(
                "admissions",
                filter=Q(admissions__events__isnull=False),
            )
        ),
    )
    if query:
        qs = qs.filter(
            Q(name__icontains=query) | Q(patient_source_key__icontains=query)
        )
    return qs.order_by("name")


def search_patients(query: str | None = None) -> QuerySet[Patient]:
    """Search patients by name or patient_source_key.

    If query is None or empty, returns all patients ordered by name.
    Search is case-insensitive and uses partial matching (icontains).
    """
    qs = Patient.objects.all()
    if query:
        qs = qs.filter(
            Q(name__icontains=query) | Q(patient_source_key__icontains=query)
        )
    return qs.order_by("name")


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
