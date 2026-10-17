"""Conservative write eligibility for one admission (PEND-S1, D3).

Writes are allowed only on the single canonical open admission of a
patient who is present exactly once in the latest occupied census
photo. Absence or ambiguity blocks with the exact PI-03 notice and
never invents data, moves the user, or triggers ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    CLOSED_EPISODE_MESSAGE,
    INELIGIBLE_MESSAGE,
    NOT_CURRENT_MESSAGE,
)
from apps.pending_items.queries import (
    CUT_ABSENT,
    CUT_AMBIGUOUS_IDENTITY,
    CUT_AMBIGUOUS_OCCUPATION,
    CUT_MULTIPLE_OPEN,
    CUT_OK,
    classify_patient,
    resolve_patient_detail,
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
    """Decide whether an admission accepts pending-item writes.

    Consumes the same conservative classification core as the aggregate
    cut and indicators (design D3); this wrapper only adds the
    admission-specific reasons and keeps the exact PI-03 notices.
    """
    if admission.merged_into_id is not None:
        return WriteEligibility(False, REASON_MERGED, None)
    if admission.discharge_date is not None:
        return WriteEligibility(False, REASON_CLOSED, None)

    source_key = Patient.objects.filter(pk=admission.patient_id).values_list(
        "patient_source_key", flat=True
    ).first()
    if source_key is None:
        return WriteEligibility(False, REASON_ABSENT, None)

    detail = resolve_patient_detail(source_key)
    # Same precedence as the original rule: an ambiguous identity wins
    # over photo absence or occupation checks.
    if len(detail.identity_rows) > 1:
        return WriteEligibility(False, REASON_AMBIGUOUS, None)
    if not detail.has_photo:
        return WriteEligibility(False, REASON_ABSENT, None)

    outcome = classify_patient(
        cells=detail.cells,
        identity_rows=detail.identity_rows,
        open_ids=detail.open_ids,
    )
    if outcome.status in (CUT_ABSENT, CUT_AMBIGUOUS_IDENTITY):
        return WriteEligibility(False, REASON_ABSENT, None)
    if outcome.status in (CUT_AMBIGUOUS_OCCUPATION, CUT_MULTIPLE_OPEN):
        return WriteEligibility(False, REASON_AMBIGUOUS, None)
    assert outcome.status == CUT_OK
    if outcome.open_admission_id != admission.pk:
        return WriteEligibility(False, REASON_NOT_CURRENT, None)
    return WriteEligibility(True, REASON_OK, admission.pk)


def require_write_eligibility(admission: Admission) -> Admission:
    """Return the admission or raise with the user-facing notice."""
    outcome = check_write_eligibility(admission)
    if outcome.eligible:
        return admission
    raise IneligibleAdmissionError(reason_message(outcome.reason))
