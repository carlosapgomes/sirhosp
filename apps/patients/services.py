"""Patient navigation services (Slice S4) and admission identity (RPSA-S1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, QuerySet

from apps.patients.models import Admission, AdmissionSourceAlias, Patient

if TYPE_CHECKING:
    from apps.clinical_docs.models import ClinicalEvent
    from apps.ingestion.models import IngestionRun

TZ_ADMISSION_IDENTITY = ZoneInfo("America/Bahia")
"""Institutional timezone for admission local-date identity matching."""

MATCH_CURRENT_KEY = "current_key"
MATCH_ALIAS = "alias"
MATCH_EXACT_START = "exact_start"
MATCH_UNIQUE_LOCAL_DATE = "unique_local_date"


@dataclass(frozen=True)
class AdmissionIdentityMatch:
    """Outcome of layered admission identity resolution.

    ``ambiguous`` means the layered resolver found multiple same-day
    candidates and the caller MUST change nothing (fail closed).
    """

    admission: Admission | None
    match_reason: str
    ambiguous: bool
    candidate_count: int


def _bahia_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    """UTC-inclusive bounds of the admission's `America/Bahia` local day."""
    local_day = value.astimezone(TZ_ADMISSION_IDENTITY).date()
    start = datetime.combine(local_day, time.min, tzinfo=TZ_ADMISSION_IDENTITY)
    return start, start + timedelta(days=1)


def resolve_admission_identity(
    *,
    patient: Patient,
    source_system: str,
    source_admission_key: str,
    admission_start: datetime | None,
    admission_end: datetime | None,
) -> AdmissionIdentityMatch:
    """Resolve one canonical admission using layered identity signals.

    Precedence (spec `patient-admission-mirror`, RPSA-S1):
      1. Current external key ``(source_system, source_admission_key)`` of
         this patient.
      2. Historical alias of one canonical admission of this patient.
      3. Patient plus exact admission start; multiple rows sharing one
         identical period represent a single duplicated episode and collapse
         to the oldest row instead of becoming an ambiguity.
      4. Patient plus a unique `America/Bahia` local admission date.

    Zero or multiple same-day candidates fail closed: the returned match is
    ambiguous and the caller must not mutate any admission. Only canonical
    rows (never rows already merged into another) are considered. The key and
    alias are patient-scoped matching signals, never clinical identity: a key
    or alias observed for another patient never matches.
    """
    admissions = Admission.objects.all()  # default manager: canonical only

    if source_admission_key:
        by_key = admissions.filter(
            patient=patient,
            source_system=source_system,
            source_admission_key=source_admission_key,
        ).first()
        if by_key is not None:
            return AdmissionIdentityMatch(
                admission=by_key,
                match_reason=MATCH_CURRENT_KEY,
                ambiguous=False,
                candidate_count=1,
            )

        # Alias uniqueness (uq_admission_source_alias_key) guarantees at most
        # one hit; .first() never selects among ambiguous candidates here.
        alias = (
            AdmissionSourceAlias.objects.filter(
                source_system=source_system,
                alias_key=source_admission_key,
                admission__patient=patient,
                admission__merged_into__isnull=True,
            )
            .select_related("admission")
            .first()
        )
        if alias is not None:
            return AdmissionIdentityMatch(
                admission=alias.admission,
                match_reason=MATCH_ALIAS,
                ambiguous=False,
                candidate_count=1,
            )

    if admission_start is not None:
        exact = list(
            admissions.filter(
                patient=patient,
                source_system=source_system,
                admission_date=admission_start,
            )
        )
        if len(exact) == 1:
            return AdmissionIdentityMatch(
                admission=exact[0],
                match_reason=MATCH_EXACT_START,
                ambiguous=False,
                candidate_count=1,
            )
        if len(exact) > 1:
            identical_periods = {
                (row.admission_date, row.discharge_date) for row in exact
            }
            if len(identical_periods) == 1:
                oldest = min(exact, key=lambda row: row.pk)
                return AdmissionIdentityMatch(
                    admission=oldest,
                    match_reason=MATCH_EXACT_START,
                    ambiguous=False,
                    candidate_count=len(exact),
                )
            return AdmissionIdentityMatch(
                admission=None,
                match_reason=MATCH_EXACT_START,
                ambiguous=True,
                candidate_count=len(exact),
            )

        day_start, day_end = _bahia_day_bounds(admission_start)
        same_day = list(
            admissions.filter(
                patient=patient,
                source_system=source_system,
                admission_date__gte=day_start,
                admission_date__lt=day_end,
            )
        )
        if len(same_day) == 1:
            return AdmissionIdentityMatch(
                admission=same_day[0],
                match_reason=MATCH_UNIQUE_LOCAL_DATE,
                ambiguous=False,
                candidate_count=1,
            )
        if len(same_day) > 1:
            return AdmissionIdentityMatch(
                admission=None,
                match_reason=MATCH_UNIQUE_LOCAL_DATE,
                ambiguous=True,
                candidate_count=len(same_day),
            )

    return AdmissionIdentityMatch(
        admission=None,
        match_reason="",
        ambiguous=False,
        candidate_count=0,
    )


def ensure_admission_alias(
    *,
    admission: Admission,
    source_system: str,
    alias_key: str,
) -> bool:
    """Persist an observed external key as alias of the canonical admission.

    Idempotent: an existing alias is left untouched. Returns True only when
    the alias row was created by this call.
    """
    normalized = (alias_key or "").strip()
    if not normalized:
        return False
    _, created = AdmissionSourceAlias.objects.get_or_create(
        source_system=source_system,
        alias_key=normalized,
        defaults={"admission": admission},
    )
    return created


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
        admissions_total=Count("admissions", distinct=True),
        admissions_with_events=Count(
            "admissions",
            filter=Q(admissions__events__isnull=False),
            distinct=True,
        ),
        admissions_without_events=(
            Count("admissions", distinct=True)
            - Count(
                "admissions",
                filter=Q(admissions__events__isnull=False),
                distinct=True,
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


def merge_patients(
    *,
    keep: Patient,
    merge: Patient,
    run: IngestionRun | None = None,
) -> dict[str, int]:
    """Merge 'merge' patient into 'keep' patient.

    Re-points all Admissions and ClinicalEvents from merge to keep,
    records the merge in PatientIdentifierHistory, and deletes merge.

    Args:
        keep: Patient to preserve.
        merge: Patient to merge and delete.
        run: Optional IngestionRun for audit trail.

    Returns:
        Dict with counts: admissions_moved, events_moved
    """
    from apps.clinical_docs.models import ClinicalEvent
    from apps.patients.models import PatientIdentifierHistory

    if keep.pk == merge.pk:
        raise ValueError("Cannot merge a patient into itself.")

    # Re-point admissions. ``all_objects`` is required: the default manager
    # hides rows with ``merged_into`` set, and skipping them here would leave
    # them cascading away with the deleted patient.
    admissions_moved = Admission.all_objects.filter(
        patient=merge
    ).update(patient=keep)

    # Re-point clinical events
    events_moved = ClinicalEvent.objects.filter(
        patient=merge
    ).update(patient=keep)

    # Record the merge
    PatientIdentifierHistory.objects.create(
        patient=keep,
        identifier_type="patient_merge",
        old_value=merge.patient_source_key,
        new_value=keep.patient_source_key,
        ingestion_run=run,
    )

    # Delete the merged patient
    merge.delete()

    return {
        "admissions_moved": admissions_moved,
        "events_moved": events_moved,
    }


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
