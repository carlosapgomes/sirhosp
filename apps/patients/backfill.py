"""Bounded dry-run backfill planning, apply and rollback (RPSA-S9).

Pure planning over approved cohorts plus orchestration helpers that
mutate exclusively through the online services:

- duplicates: :func:`apps.patients.admission_merge.decide_merge_eligibility`
  + ``merge_admissions`` (the online source-confirmation path, including
  fingerprint freshness re-validation under row locks);
- exact hospital discharges: ``DischargeRecord`` with a valid ``saida_em``
  and exactly one canonical same-patient same-local-admission-date
  admission, replayed via
  :func:`apps.discharges.services.reconcile_discharge_record`;
- complete deaths: evidence with a complete datetime and exactly one
  compatible admission, replayed via
  :func:`apps.deaths.services.reconcile_death_record`.

Everything else (temporal-only matches, absent evidence, ambiguity) is
counted for manual review only and never applied. The plan carries no
patient identity; apply/rollback record batch linkage append-only in the
existing audit payloads (``backfill.batch_uuid``/``item_order``) through
the ambient hook in :mod:`apps.patients.reconciliation`. This module
performs no direct ORM writes; every mutation happens inside an online
service. Summary/refresh pipelines are never started here.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union

from django.db import transaction
from django.utils import timezone

from apps.deaths.models import DeathRecord
from apps.deaths.services import _parse_death_datetime, reconcile_death_record
from apps.discharges.models import DischargeRecord
from apps.discharges.services import _parse_admission_date, reconcile_discharge_record
from apps.patients.admission_merge import (
    ELIGIBLE,
    AdmissionSourceConfirmation,
    SourceEpisode,
    decide_merge_eligibility,
    merge_admissions,
    rollback_admission_merge,
)
from apps.patients.models import (
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    AdmissionMergeOperation,
    ReconciliationEvent,
)
from apps.patients.reconciliation import (
    DischargeExitEvidence,
    backfill_batch_payload,
    decide_discharge_match,
    reverse_reconciliation,
)
from apps.patients.services import TZ_ADMISSION_IDENTITY

COHORT_DUPLICATES = "duplicates"
COHORT_DISCHARGES = "discharges"
COHORT_DEATHS = "deaths"
COHORT_ORDER = (COHORT_DUPLICATES, COHORT_DISCHARGES, COHORT_DEATHS)

KIND_RECONCILIATION_EVENT = "reconciliation_event"
KIND_MERGE_OPERATION = "merge_operation"

FIRST_APPLY_CAP = 50
"""First authorized canary: at most 50 items when no backfill batch exists."""

LATER_APPLY_CAP = 100
"""Later batches may rise to 100 only after at least one recorded batch."""

REVIEW_MULTIPLE_EPISODES = "multiple_episodes"
REVIEW_PAIR_SHAPE = "pair_shape"
REVIEW_STALE_CONFIRMATION = "stale_confirmation"
REVIEW_DATE_ONLY = "date_only"
REVIEW_MISSING_SAIDA_EM = "missing_saida_em"

_RECONCILED_STATUSES = (
    RECONCILIATION_STATUS_RECONCILED,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
)


class BackfillError(Exception):
    """Base class of the bounded backfill domain errors."""


class BackfillPreconditionError(BackfillError):
    """An apply precondition (limit/label/backup-ref/cap) is not met."""


class BackfillItemFailed(BackfillError):
    """One planned item no longer resolves as reconciled at apply time."""


class BackfillRollbackError(BackfillError):
    """Base class of the rollback domain errors."""


class BackfillRollbackNotFound(BackfillRollbackError):
    """The selector resolves to no batch or operation."""


class BackfillRollbackAmbiguous(BackfillRollbackError):
    """The selector resolves to more than one audit kind."""


class BackfillRollbackConflict(BackfillRollbackError):
    """A grouped item post-state diverged; the rollback wrote nothing."""


# ---------------------------------------------------------------------------
# Canary cap without new persistence: prior batches are counted by distinct
# batch_uuid across the two existing payload locations.
# ---------------------------------------------------------------------------


def count_prior_backfill_batches() -> int:
    """Count distinct backfill batch UUIDs in the append-only payloads."""
    reconciliation_batches = set(
        ReconciliationEvent.objects.filter(
            details_json__backfill__batch_uuid__isnull=False,
        ).values_list("details_json__backfill__batch_uuid", flat=True)
    )
    merge_batches = set(
        AdmissionMergeOperation.objects.filter(
            relation_manifest__backfill__batch_uuid__isnull=False,
        ).values_list("relation_manifest__backfill__batch_uuid", flat=True)
    )
    return len(reconciliation_batches | merge_batches)


def current_apply_cap() -> int:
    """50 for the first canary; 100 once at least one batch was recorded."""
    return FIRST_APPLY_CAP if count_prior_backfill_batches() == 0 else LATER_APPLY_CAP


# ---------------------------------------------------------------------------
# Pure plan objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateItem:
    """One source-confirmed open/closed pair pending merge."""

    canonical_id: int
    duplicate_id: int
    confirmation: AdmissionSourceConfirmation
    fingerprint: str


@dataclass(frozen=True)
class DischargeItem:
    """One discharge evidence row to replay via the online service."""

    record_id: int


@dataclass(frozen=True)
class DeathItem:
    """One death evidence row to replay via the online service."""

    record_id: int


PlanPayload = Union[DuplicateItem, DischargeItem, DeathItem]


@dataclass(frozen=True)
class PlanItem:
    """One ordered backfill operation inside the merged plan."""

    order: int
    cohort: str
    payload: PlanPayload


@dataclass(frozen=True)
class CohortPlan:
    """Aggregate counts plus the bounded items of one cohort."""

    cohort: str
    total: int
    items: tuple[PlanItem, ...]

    @property
    def truncated(self) -> bool:
        return self.total > len(self.items)


@dataclass(frozen=True)
class BackfillPlan:
    """Pure plan: per-cohort counts, operation bounds and manual review."""

    cap: int
    limit: Optional[int]
    duplicates: CohortPlan
    discharges: CohortPlan
    deaths: CohortPlan
    manual_review: dict[str, int]
    items: tuple[PlanItem, ...]


@dataclass(frozen=True)
class BackfillApplyResult:
    """Structural outcome of one bounded apply batch."""

    batch_uuid: uuid.UUID
    items: int
    applied: dict[str, int]


@dataclass(frozen=True)
class BatchRollbackResult:
    """Structural outcome of one atomic batch rollback."""

    batch_uuid: uuid.UUID
    reversed_items: int
    reversed: dict[str, int]


@dataclass(frozen=True)
class OperationRollbackResult:
    """Structural outcome of one single-operation rollback."""

    kind: str


# ---------------------------------------------------------------------------
# Cohort selection (reads only; never applies fuzzy fallbacks)
# ---------------------------------------------------------------------------


def _bahia_local_date(value: datetime) -> date:
    return value.astimezone(TZ_ADMISSION_IDENTITY).date()


def _duplicate_candidates() -> tuple[list[DuplicateItem], dict[str, int]]:
    """Discover source-confirmed open/closed pairs, oldest pk first.

    Candidates are groups of exactly two canonical admissions of one
    patient on one ``America/Bahia`` local admission date with one open
    and one closed row. The confirmation is scoped to the pair (the
    closed row's authoritative episode, captured when that row was last
    written by the source snapshot) and freshness requires the closed
    row's capture to postdate the open row's latest local change; a
    stale or unscopable pair is manual review, never applied.
    """
    review: dict[str, int] = defaultdict(int)
    groups: dict[tuple[int, date], list[Admission]] = defaultdict(list)
    rows = Admission.objects.filter(admission_date__isnull=False).order_by("pk")
    for admission in rows:
        if admission.admission_date is None:
            continue  # filtered above; kept explicit for type narrowing
        key = (admission.patient_id, _bahia_local_date(admission.admission_date))
        groups[key].append(admission)

    items: list[DuplicateItem] = []
    for (patient_id, local_date), members in groups.items():
        if len(members) == 1:
            continue
        if len(members) > 2:
            review[f"{COHORT_DUPLICATES}:{REVIEW_MULTIPLE_EPISODES}"] += len(members)
            continue
        older, newer = members
        if older.admission_date is None or newer.admission_date is None:
            continue  # unscopable without a known start (filtered above)
        closed, opened = (
            (older, newer) if older.discharge_date is not None else (newer, older)
        )
        if closed.discharge_date is None:  # two open rows: not a merge pair
            review[f"{COHORT_DUPLICATES}:{REVIEW_PAIR_SHAPE}"] += 2
            continue
        if closed.updated_at < opened.updated_at:
            review[f"{COHORT_DUPLICATES}:{REVIEW_STALE_CONFIRMATION}"] += 2
            continue
        confirmation = AdmissionSourceConfirmation(
            patient_record=(
                closed.source_patient_reference or f"patient-{patient_id}"
            ),
            local_admission_date=local_date,
            captured_at=closed.updated_at,
            failed=False,
            episodes=(
                SourceEpisode(
                    source_admission_key=closed.source_admission_key,
                    admission_start=closed.admission_date,
                    admission_end=closed.discharge_date,
                ),
            ),
        )
        eligibility = decide_merge_eligibility(confirmation=confirmation)
        if eligibility.decision != ELIGIBLE:
            review[f"{COHORT_DUPLICATES}:{eligibility.reason_code}"] += 2
            continue
        items.append(
            DuplicateItem(
                canonical_id=older.pk,
                duplicate_id=newer.pk,
                confirmation=confirmation,
                fingerprint=eligibility.fingerprint,
            )
        )
    items.sort(key=lambda item: (item.canonical_id, item.duplicate_id))
    return items, dict(review)


def _discharge_candidates() -> tuple[list[DischargeItem], dict[str, int]]:
    """Exact hospital discharges: valid ``saida_em`` plus a unique same-day
    canonical admission. Temporal-only or absent evidence is review-only."""
    review: dict[str, int] = defaultdict(int)
    items: list[DischargeItem] = []
    candidates = DischargeRecord.objects.exclude(
        reconciliation_status__in=_RECONCILED_STATUSES
    ).order_by("pk")
    for record in candidates:
        saida = record.saida_em
        if saida is not None and timezone.is_naive(saida):
            saida = timezone.make_aware(saida)
        if saida is None:
            review[f"{COHORT_DISCHARGES}:{REVIEW_MISSING_SAIDA_EM}"] += 1
            continue
        decision = decide_discharge_match(
            evidence=DischargeExitEvidence(
                patient_record=record.prontuario,
                exit_datetime=saida,
                admission_local_date=_parse_admission_date(record.data_internacao),
            )
        )
        if decision.status == RECONCILIATION_STATUS_RECONCILED:
            items.append(DischargeItem(record_id=record.pk))
        else:
            review[f"{COHORT_DISCHARGES}:{decision.status}"] += 1
    return items, dict(review)


def _death_candidates() -> tuple[list[DeathItem], dict[str, int]]:
    """Complete deaths: complete datetime plus exactly one compatible
    admission. Date-only evidence is review-only and never synthesized."""
    review: dict[str, int] = defaultdict(int)
    items: list[DeathItem] = []
    candidates = DeathRecord.objects.exclude(
        reconciliation_status__in=_RECONCILED_STATUSES
    ).order_by("pk")
    for record in candidates:
        exit_datetime = _parse_death_datetime(record.data_obito)
        if exit_datetime is None:
            review[f"{COHORT_DEATHS}:{REVIEW_DATE_ONLY}"] += 1
            continue
        decision = decide_discharge_match(
            evidence=DischargeExitEvidence(
                patient_record=record.prontuario,
                exit_datetime=exit_datetime,
                match_by_period=True,
            )
        )
        if decision.status == RECONCILIATION_STATUS_RECONCILED:
            items.append(DeathItem(record_id=record.pk))
        else:
            review[f"{COHORT_DEATHS}:{decision.status}"] += 1
    return items, dict(review)


def build_backfill_plan(*, limit: Optional[int] = None) -> BackfillPlan:
    """Build the pure deterministic plan (no ORM writes).

    Cohorts execute in the mandated order — duplicates, exact hospital
    discharges, complete deaths — each in stable primary-key order; the
    limit applies to the merged plan before any write. Dry-run bounds the
    preview by the current canary cap when no explicit limit is given.
    """
    cap = current_apply_cap()
    bound = limit if limit is not None else cap
    duplicate_items, duplicate_review = _duplicate_candidates()
    discharge_items, discharge_review = _discharge_candidates()
    death_items, death_review = _death_candidates()
    manual_review: dict[str, int] = {}
    for partial in (duplicate_review, discharge_review, death_review):
        for reason, count in partial.items():
            manual_review[reason] = count

    ordered: list[tuple[str, PlanPayload]] = []
    ordered += [(COHORT_DUPLICATES, item) for item in duplicate_items]
    ordered += [(COHORT_DISCHARGES, item) for item in discharge_items]
    ordered += [(COHORT_DEATHS, item) for item in death_items]
    items = tuple(
        PlanItem(order=order, cohort=cohort, payload=payload)
        for order, (cohort, payload) in enumerate(ordered[:bound], start=1)
    )

    def cohort_plan(cohort: str, total: int) -> CohortPlan:
        return CohortPlan(
            cohort=cohort,
            total=total,
            items=tuple(item for item in items if item.cohort == cohort),
        )

    return BackfillPlan(
        cap=cap,
        limit=limit,
        duplicates=cohort_plan(COHORT_DUPLICATES, len(duplicate_items)),
        discharges=cohort_plan(COHORT_DISCHARGES, len(discharge_items)),
        deaths=cohort_plan(COHORT_DEATHS, len(death_items)),
        manual_review=manual_review,
        items=items,
    )


# ---------------------------------------------------------------------------
# Bounded apply: one transaction per batch, online services only
# ---------------------------------------------------------------------------


def _execute_item(item: PlanItem) -> None:
    payload = item.payload
    if isinstance(payload, DuplicateItem):
        merge_admissions(
            first=Admission.all_objects.get(pk=payload.duplicate_id),
            second=Admission.all_objects.get(pk=payload.canonical_id),
            confirmation=payload.confirmation,
            expected_fingerprint=payload.fingerprint,
        )
    elif isinstance(payload, DischargeItem):
        status = reconcile_discharge_record(
            record=DischargeRecord.objects.get(pk=payload.record_id)
        )
        if status != RECONCILIATION_STATUS_RECONCILED:
            raise BackfillItemFailed(
                f"discharge evidence {payload.record_id} resolved '{status}' "
                "at apply time."
            )
    else:
        status = reconcile_death_record(
            record=DeathRecord.objects.get(pk=payload.record_id)
        )
        if status != RECONCILIATION_STATUS_RECONCILED:
            raise BackfillItemFailed(
                f"death evidence {payload.record_id} resolved '{status}' "
                "at apply time."
            )


def apply_backfill_plan(*, plan: BackfillPlan) -> BackfillApplyResult:
    """Apply the bounded plan inside ONE transaction with batch linkage.

    Every item mutation goes through the online services while the
    ambient backfill payload stamps ``backfill.batch_uuid``/``item_order``
    into the newly created audit rows. Any item failure raises and the
    whole transaction rolls back with zero writes.
    """
    if plan.limit is None or plan.limit <= 0:
        raise BackfillPreconditionError("Apply requires a positive limit.")
    if plan.limit > plan.cap:
        raise BackfillPreconditionError(
            f"Apply limit {plan.limit} exceeds the canary cap of {plan.cap}."
        )
    batch_uuid = uuid.uuid4()
    applied = {cohort: 0 for cohort in COHORT_ORDER}
    with transaction.atomic():
        for item in plan.items:
            with backfill_batch_payload(
                {"batch_uuid": str(batch_uuid), "item_order": item.order}
            ):
                _execute_item(item)
            applied[item.cohort] += 1
    return BackfillApplyResult(
        batch_uuid=batch_uuid,
        items=len(plan.items),
        applied=applied,
    )


# ---------------------------------------------------------------------------
# Rollback: batch (two-phase, atomic, reverse order) and single operation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchItem:
    """One audit row grouped into a backfill batch."""

    order: int
    kind: str
    event: Optional[ReconciliationEvent] = None
    merge_operation: Optional[AdmissionMergeOperation] = None


def collect_backfill_batch_items(*, batch_uuid: uuid.UUID) -> list[BatchItem]:
    """Group the batch's items from the two payload locations, by order."""
    key = str(batch_uuid)
    items: list[BatchItem] = []
    for event in ReconciliationEvent.objects.filter(
        details_json__backfill__batch_uuid=key
    ):
        items.append(
            BatchItem(
                order=int(event.details_json["backfill"]["item_order"]),
                kind=KIND_RECONCILIATION_EVENT,
                event=event,
            )
        )
    for operation in AdmissionMergeOperation.objects.filter(
        relation_manifest__backfill__batch_uuid=key
    ):
        items.append(
            BatchItem(
                order=int(operation.relation_manifest["backfill"]["item_order"]),
                kind=KIND_MERGE_OPERATION,
                merge_operation=operation,
            )
        )
    items.sort(key=lambda item: item.order)
    return items


def _validate_batch_post_states(items: list[BatchItem]) -> None:
    """Phase 1 (read-only): every grouped item must still match its
    recorded post-state; any conflict aborts before any mutation."""
    conflicts = 0
    for item in items:
        if item.kind == KIND_MERGE_OPERATION:
            operation = item.merge_operation
            if operation is None:
                conflicts += 1
                continue
            if operation.rolled_back_at is not None:
                conflicts += 1
                continue
            still_merged = Admission.all_objects.filter(
                pk=operation.merged_admission_id,
                merged_into_id=operation.canonical_admission_id,
            ).exists()
            if not still_merged:
                conflicts += 1
            continue
        event = item.event
        if event is None:
            conflicts += 1
            continue
        if event.details_json.get("rollback_of"):
            conflicts += 1
        elif event.status != RECONCILIATION_STATUS_RECONCILED:
            conflicts += 1
        elif event.admission_id is None:
            conflicts += 1
        else:
            admission = Admission.all_objects.filter(pk=event.admission_id).first()
            if admission is None or admission.discharge_date != event.new_discharge_date:
                conflicts += 1
    if conflicts:
        raise BackfillRollbackConflict(
            f"{conflicts} of {len(items)} batch items no longer match the "
            "recorded post-state; rollback aborted with zero writes."
        )


def rollback_backfill_batch(*, batch_uuid: uuid.UUID) -> BatchRollbackResult:
    """Reverse a whole backfill batch atomically in reverse item order.

    Phase 1 validates every post-state read-only; phase 2 reverses all
    items inside ONE transaction — any conflict rolls back everything
    with zero writes. Inverse reconciliation events and the sanctioned
    merge rollback marks are appended, linked to the same batch UUID.
    """
    items = collect_backfill_batch_items(batch_uuid=batch_uuid)
    if not items:
        raise BackfillRollbackNotFound(
            "No backfill batch resolves for the given batch UUID."
        )
    _validate_batch_post_states(items)
    reversed_counts = {KIND_RECONCILIATION_EVENT: 0, KIND_MERGE_OPERATION: 0}
    with transaction.atomic():
        for item in reversed(items):
            with backfill_batch_payload(
                {"batch_uuid": str(batch_uuid), "item_order": item.order}
            ):
                if item.kind == KIND_MERGE_OPERATION:
                    if item.merge_operation is None:
                        raise BackfillRollbackConflict(
                            "Batch item payload is inconsistent; rollback "
                            "aborted with zero writes."
                        )
                    operation = AdmissionMergeOperation.objects.get(
                        pk=item.merge_operation.pk
                    )
                    rollback_admission_merge(operation=operation)
                else:
                    if item.event is None:
                        raise BackfillRollbackConflict(
                            "Batch item payload is inconsistent; rollback "
                            "aborted with zero writes."
                        )
                    reverse_reconciliation(event=item.event)
            reversed_counts[item.kind] += 1
    return BatchRollbackResult(
        batch_uuid=batch_uuid,
        reversed_items=len(items),
        reversed=reversed_counts,
    )


def rollback_single_operation(
    *, operation_uuid: uuid.UUID
) -> OperationRollbackResult:
    """Reverse exactly one online operation by its operation UUID.

    The operation namespace (reconciliation events and merge operations)
    is disjoint from the batch namespace (backfill payload linkage), so a
    selector can never be mistaken for a batch.
    """
    event = ReconciliationEvent.objects.filter(operation_uuid=operation_uuid).first()
    merge_operation = AdmissionMergeOperation.objects.filter(
        operation_uuid=operation_uuid
    ).first()
    if event is not None and merge_operation is not None:
        raise BackfillRollbackAmbiguous(
            "The operation UUID resolves ambiguously to both a reconciliation "
            "event and a merge operation."
        )
    if event is not None:
        reverse_reconciliation(event=event)
        return OperationRollbackResult(kind=KIND_RECONCILIATION_EVENT)
    if merge_operation is not None:
        rollback_admission_merge(operation=merge_operation)
        return OperationRollbackResult(kind=KIND_MERGE_OPERATION)
    raise BackfillRollbackNotFound(
        "No reconciliation event or merge operation resolves for the "
        "given operation UUID."
    )
