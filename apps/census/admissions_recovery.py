"""Bounded, dry-run-by-default recovery of current-census admissions.

RPAP-S4: plans admissions recovery from the latest complete census with
unique successful census-run provenance and, on explicit apply, enqueues at
most ``limit`` ``admissions_only`` runs (via the canonical
:func:`apps.ingestion.services.queue_admissions_only_run`) inside a single
recovery batch. Everything outside ``apply_current_census_admissions_recovery``
is read-only; output structures carry only aggregate counts, never patient
identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import (
    resolve_single_census_run,
    validate_snapshot_completeness,
)
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.ingestion.services import queue_admissions_only_run

if TYPE_CHECKING:
    from django.db.models import QuerySet

MAX_RECOVERY_LIMIT: int = 100
"""Operator-provided apply limit is an integer between 1 and this value."""

RECOVERY_BATCH_PURPOSE: str = "admissions_recovery"
"""Stable notes_json marker identifying a recovery batch."""

_CENSUS_RUN_INTENT: str = "census_extraction"
_ADMISSIONS_INTENT: str = "admissions_only"
_ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")


class CensusAdmissionsRecoveryError(Exception):
    """Recovery cannot plan from the current census.

    ``reason`` is one of the fixed sanitized categories
    (``missing_snapshot``, ``incomplete_snapshot``,
    ``ambiguous_provenance``, ``unresolved_census_run``). The message never
    carries patient, HTML, URL or credential data.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RecoveryPlan:
    """Aggregate-only planning counts for one recovery execution."""

    census_run_id: int
    candidates: int
    eligible: int
    excluded_active: int
    excluded_recovered: int
    excluded_no_identifier: int
    limit_applicable: int


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of an explicit bounded apply."""

    batch_id: int | None
    runs_created: int
    plan: RecoveryPlan


@dataclass(frozen=True)
class _CensusSource:
    """Resolved latest complete census with a unique successful run."""

    census_run_id: int
    snapshots: QuerySet[CensusSnapshot]


def _resolve_census_source() -> _CensusSource:
    """Resolve the latest complete census with unique successful run.

    Raises :class:`CensusAdmissionsRecoveryError` with a fixed sanitized
    reason when no snapshot exists, the snapshot group is incomplete, the
    provenance does not resolve to one census run, or the resolved run is
    not a successful census extraction run. ``captured_at`` is used only to
    select the latest group, never as an idempotency key.
    """
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]
    if latest_captured is None:
        raise CensusAdmissionsRecoveryError("missing_snapshot")

    snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    coverage = validate_snapshot_completeness(snapshots)
    if not coverage["accepted"]:
        raise CensusAdmissionsRecoveryError("incomplete_snapshot")

    census_run_id = resolve_single_census_run(snapshots)
    if census_run_id is None:
        raise CensusAdmissionsRecoveryError("ambiguous_provenance")

    if not IngestionRun.objects.filter(
        pk=census_run_id,
        intent=_CENSUS_RUN_INTENT,
        status="succeeded",
    ).exists():
        raise CensusAdmissionsRecoveryError("unresolved_census_run")

    return _CensusSource(census_run_id=census_run_id, snapshots=snapshots)


def _occupied_candidates(
    source: _CensusSource,
) -> tuple[list[str], int]:
    """Deduplicated deterministic occupied prontuarios plus no-id count.

    Returns (candidates, no_identifier) where candidates are unique
    non-empty prontuarios of OCCUPIED beds ordered deterministically and
    no_identifier is the number of occupied rows without a usable
    prontuario.
    """
    rows = list(
        source.snapshots.filter(bed_status=BedStatus.OCCUPIED)
        .order_by("prontuario", "pk")
        .values_list("prontuario", flat=True)
    )
    no_identifier = sum(1 for raw in rows if not (raw or "").strip())

    candidates: list[str] = []
    seen: set[str] = set()
    for raw in rows:
        prontuario = (raw or "").strip()
        if not prontuario or prontuario in seen:
            continue
        seen.add(prontuario)
        candidates.append(prontuario)
    return candidates, no_identifier


def _exclusion_records(census_run_id: int) -> tuple[set[str], set[str]]:
    """Records already covered by active work or prior recovery batches.

    Returns ``(active, recovered)`` where active holds prontuarios with a
    queued/running ``admissions_only`` run anywhere and recovered holds
    prontuarios already present in a recovery batch of the same census run,
    regardless of the terminal outcome of those runs.
    """
    active = set(
        IngestionRun.objects.filter(
            intent=_ADMISSIONS_INTENT,
            status__in=_ACTIVE_RUN_STATUSES,
        ).values_list("parameters_json__patient_record", flat=True)
    )

    recovery_batch_ids = list(
        CensusExecutionBatch.objects.filter(
            notes_json__purpose=RECOVERY_BATCH_PURPOSE,
            notes_json__census_run_id=str(census_run_id),
        ).values_list("pk", flat=True)
    )
    recovered: set[str] = set()
    if recovery_batch_ids:
        recovered = set(
            IngestionRun.objects.filter(
                intent=_ADMISSIONS_INTENT,
                batch_id__in=recovery_batch_ids,
            ).values_list("parameters_json__patient_record", flat=True)
        )
    return active, recovered


def _build_plan(
    source: _CensusSource, limit: int | None
) -> tuple[RecoveryPlan, list[str]]:
    """Compute aggregate counts and the deterministic eligible list."""
    candidates, no_identifier = _occupied_candidates(source)
    active, recovered = _exclusion_records(source.census_run_id)

    excluded_active = sum(1 for pront in candidates if pront in active)
    excluded_recovered = sum(1 for pront in candidates if pront in recovered)
    eligible = [
        pront
        for pront in candidates
        if pront not in active and pront not in recovered
    ]
    limit_applicable = (
        min(limit, len(eligible)) if limit is not None else len(eligible)
    )

    plan = RecoveryPlan(
        census_run_id=source.census_run_id,
        candidates=len(candidates),
        eligible=len(eligible),
        excluded_active=excluded_active,
        excluded_recovered=excluded_recovered,
        excluded_no_identifier=no_identifier,
        limit_applicable=limit_applicable,
    )
    return plan, eligible


def plan_current_census_admissions_recovery(
    *, limit: int | None = None
) -> RecoveryPlan:
    """Plan recovery from the latest complete census (read-only).

    Raises :class:`CensusAdmissionsRecoveryError` when the census is
    missing, incomplete, ambiguous or not a successful census run. Never
    creates or alters batch, run, patient, admission, movement or event.
    """
    source = _resolve_census_source()
    plan, _eligible = _build_plan(source, limit)
    return plan


def apply_current_census_admissions_recovery(*, limit: int) -> ApplyResult:
    """Apply recovery explicitly: one bounded batch, idempotent under races.

    Runs inside a transaction and serializes concurrent recoveries of the
    same census run on the census ``IngestionRun`` row, then re-evaluates
    exclusions so a second evaluator never duplicates the first. Creates at
    most ``limit`` ``admissions_only`` runs in a single recovery batch
    linked to the census run reference and aggregate-only metadata. Never
    creates an empty batch and never mutates historical runs.
    """
    with transaction.atomic():
        source = _resolve_census_source()
        # RPAP-S4 R4: the census run row is the serialization point for
        # concurrent applies of the same census; after acquiring the lock
        # the exclusions below are re-evaluated against the latest state.
        IngestionRun.objects.select_for_update().get(pk=source.census_run_id)

        plan, eligible = _build_plan(source, limit)
        to_enqueue = eligible[:limit]
        if not to_enqueue:
            return ApplyResult(batch_id=None, runs_created=0, plan=plan)

        batch = CensusExecutionBatch.objects.create(
            status="running",
            notes_json={
                "purpose": RECOVERY_BATCH_PURPOSE,
                "census_run_id": str(source.census_run_id),
                "limit": limit,
                "candidates": plan.candidates,
                "eligible": plan.eligible,
                "excluded_active": plan.excluded_active,
                "excluded_recovered": plan.excluded_recovered,
                "excluded_no_identifier": plan.excluded_no_identifier,
                "patients_enqueued": len(to_enqueue),
            },
        )
        for prontuario in to_enqueue:
            queue_admissions_only_run(
                patient_record=prontuario,
                batch=batch,
            )
        batch.enqueue_finished_at = timezone.now()
        batch.save(update_fields=["enqueue_finished_at", "notes_json"])

        return ApplyResult(
            batch_id=batch.pk,
            runs_created=len(to_enqueue),
            plan=plan,
        )
