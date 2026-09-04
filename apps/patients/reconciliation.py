"""Canonical hospital-exit reconciliation (RPSA-S2).

Layered, evidence-linked reconciliation of effective hospital exits onto
canonical admissions. ``saida_em`` in ``America/Bahia`` is the only
authoritative closing time; ``alta_em`` never reaches this module.

Split of responsibilities:

- :func:`decide_discharge_match` is the pure ordered matching decision:
  it only reads and returns one of the eight canonical reconciliation
  statuses, reusing the RPSA-S1 identity resolver
  (:func:`apps.patients.services.resolve_admission_identity`) for the
  key, alias, exact-start and unique-local-date layers.
- :func:`apply_discharge_exit` is the transactional, row-locked
  application boundary: it performs the selected mutation and writes one
  append-only :class:`~apps.patients.models.ReconciliationEvent`.

Source adapters declare only the identifiers and temporal precision they
actually possess (:class:`DischargeExitEvidence`); unavailable matching
levels are skipped, never synthesized.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from django.db import transaction
from django.db.models import Q

from apps.patients.models import (
    EXIT_DEATH,
    EXIT_HOSPITAL_DISCHARGE,
    EXIT_UNKNOWN,
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)
from apps.patients.services import (
    MATCH_ALIAS,
    MATCH_CURRENT_KEY,
    MATCH_UNIQUE_LOCAL_DATE,
    TZ_ADMISSION_IDENTITY,
    _bahia_day_bounds,
    resolve_admission_identity,
)

logger = logging.getLogger(__name__)

EVIDENCE_SOURCE_DISCHARGE_RECORD = "discharge_record"
"""Evidence kind recorded in audit payloads for ``DischargeRecord`` rows."""

EVIDENCE_SOURCE_DEATH_RECORD = "death_record"
"""Evidence kind recorded in audit payloads for ``DeathRecord`` rows."""

MATCH_CONTAINING_PERIOD = "containing_period"
"""Match reason of the death-evidence period layer (RPSA-S3): the unique
canonical admission whose known period contains the exit datetime."""

REASON_NULL_ADMISSION_START = "null_admission_start"
"""Key/alias matched but the admission start is null: cannot validate time."""
REASON_CONTRADICTORY_STRONG_IDS = "contradictory_strong_ids"
"""Key/alias resolved one admission while the exact start points elsewhere."""
REASON_EXIT_BEFORE_ADMISSION = "exit_before_admission"
"""Effective exit is earlier than the matched admission start."""

_RECONCILABLE_STATUSES = (
    RECONCILIATION_STATUS_RECONCILED,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
)


@dataclass(frozen=True)
class DischargeExitEvidence:
    """Normalized exit evidence with only the precision it really has.

    A ``None`` field means that matching level is unavailable in the
    source shape and MUST be skipped (never synthesized). The discharge
    XLS, for instance, has no admission key and its ``data_internacao``
    is only an ``America/Bahia`` local date, so its evidence carries
    ``admission_key=None``, ``admission_start=None`` and a filled
    ``admission_local_date``.
    """

    patient_record: str
    exit_datetime: Optional[datetime]
    admission_key: Optional[str] = None
    admission_start: Optional[datetime] = None
    admission_local_date: Optional[date] = None
    source_system: str = "tasy"
    match_by_period: bool = False
    """Death-evidence opt-in to the unique-containing-period layer (RPSA-S3).

    Discharge evidence keeps the default (``False``): without an admission
    key, exact start or local date, no weaker level is ever evaluated."""


@dataclass(frozen=True)
class DischargeMatchDecision:
    """Outcome of the pure ordered matching for one evidence item."""

    status: str
    admission: Optional[Admission]
    match_reason: str
    candidate_count: int
    exit_type: str = EXIT_UNKNOWN
    reason_code: str = ""


def _decision(
    status: str,
    *,
    admission: Optional[Admission] = None,
    match_reason: str = "",
    candidate_count: Optional[int] = None,
    reason_code: str = "",
    exit_type: Optional[str] = None,
) -> DischargeMatchDecision:
    if candidate_count is None:
        candidate_count = 1 if admission is not None else 0
    if exit_type is None:
        exit_type = EXIT_HOSPITAL_DISCHARGE if admission is not None else EXIT_UNKNOWN
    return DischargeMatchDecision(
        status=status,
        admission=admission,
        match_reason=match_reason,
        candidate_count=candidate_count,
        exit_type=exit_type,
        reason_code=reason_code,
    )


def decide_discharge_match(
    *,
    evidence: DischargeExitEvidence,
) -> DischargeMatchDecision:
    """Resolve the canonical match decision for one discharge evidence.

    Matching order (fixed, fail-closed): current external admission key,
    historical key alias, patient plus exact admission start, patient
    plus a unique ``America/Bahia`` local admission date. Zero or
    multiple candidates fail closed; weaker levels are never evaluated
    once a stronger unique match succeeds. A key/alias match whose
    admission start is null, or whose episode period contradicts a
    supplied exact start, is ``conflict`` — never a heuristic choice.
    """
    if evidence.exit_datetime is None:
        return _decision(RECONCILIATION_STATUS_PENDING, candidate_count=0)

    patient = Patient.objects.filter(
        source_system=evidence.source_system,
        patient_source_key=evidence.patient_record,
    ).first()
    if patient is None:
        return _decision(RECONCILIATION_STATUS_PATIENT_NOT_FOUND, candidate_count=0)

    if evidence.admission_key or evidence.admission_start is not None:
        candidate, match_reason = _resolve_by_identity_layers(
            evidence, patient
        )
        if isinstance(candidate, DischargeMatchDecision):
            return candidate
    elif evidence.admission_local_date is not None:
        candidate, match_reason = _resolve_by_unique_local_date(
            evidence, patient
        )
        if isinstance(candidate, DischargeMatchDecision):
            return candidate
    elif evidence.match_by_period:
        # Death evidence carries no admission key, no exact start and no
        # local admission date: the only layer it may use is the unique
        # canonical admission whose known period contains the complete
        # death datetime (design decision 3).
        candidate, match_reason = _resolve_by_unique_containing_period(
            evidence, patient
        )
        if isinstance(candidate, DischargeMatchDecision):
            return candidate
    else:
        # No key, no exact start, no local date: no fallback to the
        # patient's latest admission is ever performed.
        return _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0)

    if candidate.admission_date is None:
        return _decision(
            RECONCILIATION_STATUS_CONFLICT,
            admission=candidate,
            match_reason=match_reason,
            reason_code=REASON_NULL_ADMISSION_START,
        )
    if evidence.exit_datetime < candidate.admission_date:
        return _decision(
            RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
            admission=candidate,
            match_reason=match_reason,
            reason_code=REASON_EXIT_BEFORE_ADMISSION,
        )
    if candidate.discharge_date == evidence.exit_datetime:
        return _decision(
            RECONCILIATION_STATUS_ALREADY_RECONCILED,
            admission=candidate,
            match_reason=match_reason,
            exit_type=_evidence_exit_type(evidence),
        )
    # Open admission (first close) or an unambiguous authoritative
    # correction of a prior exit value: both are `reconciled`, with the
    # prior value preserved in the append-only audit.
    return _decision(
        RECONCILIATION_STATUS_RECONCILED,
        admission=candidate,
        match_reason=match_reason,
        exit_type=_evidence_exit_type(evidence),
    )


def _resolve_by_identity_layers(
    evidence: DischargeExitEvidence,
    patient: Patient,
) -> tuple[Admission | DischargeMatchDecision, str]:
    """Key, alias and exact-start layers via the RPSA-S1 resolver."""
    match = resolve_admission_identity(
        patient=patient,
        source_system=evidence.source_system,
        source_admission_key=evidence.admission_key or "",
        admission_start=evidence.admission_start,
        admission_end=None,
    )
    if match.ambiguous:
        return (
            _decision(
                RECONCILIATION_STATUS_AMBIGUOUS,
                match_reason=match.match_reason,
                candidate_count=match.candidate_count,
            ),
            match.match_reason,
        )
    if match.admission is None:
        return (
            _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0),
            "",
        )
    if (
        match.match_reason in (MATCH_CURRENT_KEY, MATCH_ALIAS)
        and evidence.admission_start is not None
        and match.admission.admission_date is not None
        and match.admission.admission_date != evidence.admission_start
    ):
        return (
            _decision(
                RECONCILIATION_STATUS_CONFLICT,
                admission=match.admission,
                match_reason=match.match_reason,
                reason_code=REASON_CONTRADICTORY_STRONG_IDS,
            ),
            match.match_reason,
        )
    return match.admission, match.match_reason


def _evidence_exit_type(evidence: DischargeExitEvidence) -> Optional[str]:
    """Death evidence closes as ``death``; discharge evidence keeps the
    default ``hospital_discharge`` mapping inside :func:`_decision`."""
    return EXIT_DEATH if evidence.match_by_period else None


def _resolve_by_unique_containing_period(
    evidence: DischargeExitEvidence,
    patient: Patient,
) -> tuple[Admission | DischargeMatchDecision, str]:
    """Unique canonical admission whose known period contains the exit.

    Boundaries are inclusive on both ends (``admission_date <= exit`` and
    ``discharge_date is null or exit <= discharge_date``), consistent with
    the RPSA-S2 equality tripwires. An admission with a null start has no
    known period and can never contain the exit; zero or multiple
    candidates fail closed — no latest/open fallback is ever taken.
    """
    exit_at = evidence.exit_datetime
    if exit_at is None:
        # Defensive fail-closed: callers only route complete datetimes here.
        return (
            _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0),
            "",
        )
    candidates = list(
        Admission.objects.filter(
            patient=patient,
            source_system=evidence.source_system,
            admission_date__lte=exit_at,
        )
        .filter(Q(discharge_date__isnull=True) | Q(discharge_date__gte=exit_at))
        .order_by("admission_date", "pk")
    )
    if not candidates:
        return (
            _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0),
            "",
        )
    if len(candidates) > 1:
        return (
            _decision(
                RECONCILIATION_STATUS_AMBIGUOUS,
                match_reason=MATCH_CONTAINING_PERIOD,
                candidate_count=len(candidates),
                exit_type=EXIT_DEATH,
            ),
            MATCH_CONTAINING_PERIOD,
        )
    return candidates[0], MATCH_CONTAINING_PERIOD


def _resolve_by_unique_local_date(
    evidence: DischargeExitEvidence,
    patient: Patient,
) -> tuple[Admission | DischargeMatchDecision, str]:
    """Unique canonical admission on one ``America/Bahia`` local date."""
    local_date = evidence.admission_local_date
    if local_date is None:
        # Defensive fail-closed: callers only route date-only evidence here.
        return (
            _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0),
            "",
        )
    day_start, day_end = _bahia_day_bounds(
        datetime.combine(local_date, time.min, tzinfo=TZ_ADMISSION_IDENTITY)
    )
    same_day = list(
        Admission.objects.filter(
            patient=patient,
            source_system=evidence.source_system,
            admission_date__gte=day_start,
            admission_date__lt=day_end,
        )
    )
    if not same_day:
        return (
            _decision(RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, candidate_count=0),
            "",
        )
    if len(same_day) > 1:
        return (
            _decision(
                RECONCILIATION_STATUS_AMBIGUOUS,
                match_reason=MATCH_UNIQUE_LOCAL_DATE,
                candidate_count=len(same_day),
            ),
            MATCH_UNIQUE_LOCAL_DATE,
        )
    return same_day[0], MATCH_UNIQUE_LOCAL_DATE


def apply_discharge_exit(
    *,
    decision: DischargeMatchDecision,
    exit_datetime: datetime,
    exit_type: str,
    source_kind: str,
    source_id: int,
) -> str:
    """Apply a match decision transactionally under a row lock.

    Re-derives the final status from the locked admission (a race
    between decide and apply cannot corrupt clinical state), mutates
    ``Admission.discharge_date`` only for a first close or an
    unambiguous correction, and writes exactly one append-only
    :class:`~apps.patients.models.ReconciliationEvent` with structural
    before/after state (never patient identity). Returns the final
    reconciliation status.
    """
    final_status = decision.status
    reason_code = decision.reason_code
    prior: Optional[datetime] = None
    new: Optional[datetime] = None
    admission = decision.admission

    if admission is not None and decision.status in _RECONCILABLE_STATUSES:
        with transaction.atomic():
            locked = Admission.objects.select_for_update().get(pk=admission.pk)
            prior = locked.discharge_date
            final_status, reason_code = _apply_locked(
                locked, exit_datetime=exit_datetime
            )
            if final_status == RECONCILIATION_STATUS_RECONCILED:
                # First close (open admission) or unambiguous correction;
                # both store the authoritative saida_em value.
                locked.discharge_date = exit_datetime
                locked.save(update_fields=["discharge_date", "updated_at"])
                new = locked.discharge_date
            admission = locked
            # Append-only audit of every attempted reconciliation:
            # - a same-evidence repeat (re-extraction of an already
            #   audited record) stays silent, because its own prior
            #   reconcilable event already covers it (no duplicate
            #   mutation/audit);
            # - first-time evidence whose matched admission was closed at
            #   the same discharge time by another writer still gets
            #   exactly one structural event (status already_reconciled,
            #   linkage only: no clinical before/after change).
            if final_status == RECONCILIATION_STATUS_ALREADY_RECONCILED:
                # Only a prior reconcilable outcome (reconciled or
                # already_reconciled) of this very evidence counts as its
                # own event: an earlier failed attempt (e.g.
                # patient_not_found) never covers the structural linkage
                # audited below.
                has_own_event = ReconciliationEvent.objects.filter(
                    source_kind=source_kind,
                    source_id=source_id,
                    status__in=_RECONCILABLE_STATUSES,
                ).exists()
            else:
                has_own_event = False
            if not has_own_event:
                _write_audit(
                    decision=decision,
                    admission=admission,
                    status=final_status,
                    exit_type=exit_type,
                    reason_code=reason_code,
                    prior=prior,
                    new=new,
                    source_kind=source_kind,
                    source_id=source_id,
                )
    else:
        _write_audit(
            decision=decision,
            admission=admission,
            status=final_status,
            exit_type=exit_type,
            reason_code=reason_code,
            prior=prior,
            new=new,
            source_kind=source_kind,
            source_id=source_id,
        )

    logger.info(
        "exit reconciliation applied: source=%s/%s status=%s",
        source_kind,
        source_id,
        final_status,
    )
    return final_status


def _apply_locked(
    locked: Admission,
    *,
    exit_datetime: datetime,
) -> tuple[str, str]:
    """Derive the final status from the locked row without mutating it."""
    if locked.admission_date is None:
        return RECONCILIATION_STATUS_CONFLICT, REASON_NULL_ADMISSION_START
    if exit_datetime < locked.admission_date:
        return (
            RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
            REASON_EXIT_BEFORE_ADMISSION,
        )
    if locked.discharge_date == exit_datetime:
        return RECONCILIATION_STATUS_ALREADY_RECONCILED, ""
    return RECONCILIATION_STATUS_RECONCILED, ""


def _write_audit(
    *,
    decision: DischargeMatchDecision,
    admission: Optional[Admission],
    status: str,
    exit_type: str,
    reason_code: str,
    prior: Optional[datetime],
    new: Optional[datetime],
    source_kind: str,
    source_id: int,
) -> ReconciliationEvent:
    """Append exactly one audit row; application code never updates it."""
    return ReconciliationEvent.objects.create(
        source_kind=source_kind,
        source_id=source_id,
        admission=admission,
        status=status,
        exit_type=exit_type if admission is not None else EXIT_UNKNOWN,
        reason_code=reason_code or decision.reason_code,
        prior_discharge_date=prior,
        new_discharge_date=new,
        details_json={
            "match_reason": decision.match_reason,
            "candidate_count": decision.candidate_count,
            "admission_id": admission.pk if admission is not None else None,
        },
    )
