"""Conservative write eligibility for one admission (PEND-S1, D3).

Writes are allowed only on the single canonical open admission of a
patient who is present exactly once in the latest occupied census
photo. Absence or ambiguity blocks with the exact PI-03 notice and
never invents data, moves the user, or triggers ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Max

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    CLOSED_EPISODE_MESSAGE,
    INELIGIBLE_MESSAGE,
    NOT_CURRENT_MESSAGE,
)

REASON_OK = "ok"
REASON_MERGED = "merged"
REASON_CLOSED = "closed"
REASON_ABSENT = "absent"
REASON_AMBIGUOUS = "ambiguous"
REASON_NOT_CURRENT = "not_current"


class IneligibleAdmissionError(Exception):
    """The admission cannot accept pending-item writes in its state."""


@dataclass(frozen=True)
class WriteEligibility:
    """Conservative eligibility outcome for one admission."""

    eligible: bool
    reason: str
    current_admission_id: int | None


def reason_message(reason: str) -> str:
    """User-facing notice for an ineligible outcome."""
    if reason in (REASON_ABSENT, REASON_AMBIGUOUS):
        return INELIGIBLE_MESSAGE
    if reason == REASON_CLOSED:
        return CLOSED_EPISODE_MESSAGE
    return NOT_CURRENT_MESSAGE


def check_write_eligibility(admission: Admission) -> WriteEligibility:
    """Decide whether an admission accepts pending-item writes."""
    if admission.merged_into_id is not None:
        return WriteEligibility(False, REASON_MERGED, None)
    if admission.discharge_date is not None:
        return WriteEligibility(False, REASON_CLOSED, None)

    source_key = Patient.objects.filter(pk=admission.patient_id).values_list(
        "patient_source_key", flat=True
    ).first()
    if source_key is None:
        return WriteEligibility(False, REASON_ABSENT, None)
    if (
        Patient.objects.filter(patient_source_key=source_key).count() > 1
    ):
        return WriteEligibility(False, REASON_AMBIGUOUS, None)

    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]
    if latest is None:
        return WriteEligibility(False, REASON_ABSENT, None)
    occupations = set(
        CensusSnapshot.objects.filter(
            captured_at=latest,
            bed_status=BedStatus.OCCUPIED,
            prontuario=source_key,
        ).values_list("setor", "leito")
    )
    if not occupations:
        return WriteEligibility(False, REASON_ABSENT, None)
    if len(occupations) > 1:
        return WriteEligibility(False, REASON_AMBIGUOUS, None)

    open_ids = list(
        Admission.objects.filter(
            patient_id=admission.patient_id,
            discharge_date__isnull=True,
        ).values_list("pk", flat=True)
    )
    if len(open_ids) > 1:
        return WriteEligibility(False, REASON_AMBIGUOUS, None)
    if open_ids != [admission.pk]:
        return WriteEligibility(False, REASON_NOT_CURRENT, None)
    return WriteEligibility(True, REASON_OK, admission.pk)


def require_write_eligibility(admission: Admission) -> Admission:
    """Return the admission or raise with the user-facing notice."""
    outcome = check_write_eligibility(admission)
    if outcome.eligible:
        return admission
    raise IneligibleAdmissionError(reason_message(outcome.reason))
