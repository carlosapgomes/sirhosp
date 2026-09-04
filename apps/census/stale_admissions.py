"""Two-census absence detection and bounded source confirmation (RPSA-S5).

Conservative stale-admission detection from accepted complete census runs:

- An accepted complete census run is one whose snapshots pass
  ``validate_snapshot_completeness`` exactly as ``process_census_snapshot``
  enforces it; the processed run id is reused verbatim. Rejected or
  incomplete runs neither advance nor reset an absence sequence.
- The first absence observation starts one case per open canonical
  admission only for a presence-to-absence transition against the
  preceding accepted complete run (the first usable complete census is a
  baseline only, per the ``census-snapshot-processing`` spec).
- A second consecutive accepted absence plus at least 30 minutes makes
  the case eligible for one bounded ``admissions_only`` source
  confirmation. Case-level cooldowns govern re-enqueues: 6 hours after an
  inconclusive attempt, 24 hours after a conclusive no-exit response
  (boundary equality is eligible). Patients carrying ``conflict``
  reconciliation evidence join the same bounded, deduplicated,
  cooldown-governed route; their stateless cooldown is anchored on the
  evidence row's own ``reconciled_at`` because conflict patients have no
  absence case to hang state on.
- Absence never writes ``Admission.discharge_date``. Output is structural
  only: counts, statuses, run ids and ages — never patient identity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import (
    resolve_single_census_run,
    validate_snapshot_completeness,
)
from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import queue_admissions_only_run
from apps.patients.models import (
    RECONCILIATION_STATUS_CONFLICT,
    Admission,
    Patient,
    StaleAdmissionCase,
)

logger = logging.getLogger(__name__)

CONCLUSIVE_NO_EXIT_COOLDOWN = timedelta(hours=24)
INCONCLUSIVE_COOLDOWN = timedelta(hours=6)
MIN_ELIGIBILITY_IDLE = timedelta(minutes=30)
MAX_ENQUEUES_PER_CYCLE = 100

STALE_ADMISSION_SWEEP_LOCK_KEY = 31082025
"""Distinct safety-sweep advisory lock key.

Deliberately different from the orchestrator's ``ADVISORY_LOCK_KEY`` and
pinned so by test; the hourly sweep must never block or be blocked by the
census orchestrator lock.
"""

_ACTIVE_RUN_STATUSES = ("queued", "running")
_CENSUS_EXTRACTION_INTENT = "census_extraction"
_CENSUS_SOURCE_SYSTEM = "tasy"
_ADMISSIONS_ONLY_INTENT = "admissions_only"


@dataclass(frozen=True)
class _AcceptedCensusRun:
    """Accepted complete census run with its occupied patient records."""

    run_id: int
    captured_at: datetime
    occupied_keys: frozenset[str]


@dataclass(frozen=True)
class _EnqueueCandidate:
    """One bounded-confirmation candidate (case or conflict evidence)."""

    anchor: datetime
    kind: str  # "case" (census absence) or "conflict" (evidence)
    patient_record: str
    case_pk: int | None = None


# ---------------------------------------------------------------------------
# Accepted-run resolution (ground truth: reuse the processing-side gate)
# ---------------------------------------------------------------------------


def _resolve_accepted_census_run(
    run_id: int | None,
) -> _AcceptedCensusRun | None:
    """Resolve one accepted complete census run, or ``None``.

    Mirrors ``process_census_snapshot``: explicit run id selects that
    run's snapshots, otherwise the latest ``captured_at``; completeness
    comes from ``validate_snapshot_completeness`` and provenance from
    ``resolve_single_census_run`` (never a weaker reimplementation).
    """
    if run_id is not None:
        snapshots = CensusSnapshot.objects.filter(ingestion_run_id=run_id)
        provenance = resolve_single_census_run(snapshots)
        if provenance != run_id:
            return None
    else:
        latest_captured = CensusSnapshot.objects.aggregate(
            latest=Max("captured_at")
        )["latest"]
        if latest_captured is None:
            return None
        snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)
        provenance = resolve_single_census_run(snapshots)
        if provenance is None:
            return None

    coverage = validate_snapshot_completeness(snapshots)
    if not coverage["accepted"]:
        return None

    occupied = frozenset(
        prontuario.strip()
        for prontuario in snapshots.filter(bed_status=BedStatus.OCCUPIED)
        .exclude(prontuario="")
        .values_list("prontuario", flat=True)
    )
    captured_at = (
        snapshots.aggregate(latest=Max("captured_at"))["latest"]
        or timezone.now()
    )
    return _AcceptedCensusRun(
        run_id=int(provenance),
        captured_at=captured_at,
        occupied_keys=occupied,
    )


def _preceding_accepted_run(
    current: _AcceptedCensusRun,
) -> _AcceptedCensusRun | None:
    """Latest accepted complete census run strictly before ``current``.

    Primary keys and ``auto_now_add`` timestamps grow together for
    ingestion runs, so pk order is the deterministic creation order.
    """
    candidate_ids = (
        IngestionRun.objects.filter(
            intent=_CENSUS_EXTRACTION_INTENT,
            status="succeeded",
            pk__lt=current.run_id,
        )
        .order_by("-pk")
        .values_list("pk", flat=True)
    )
    for candidate_id in candidate_ids:
        resolved = _resolve_accepted_census_run(candidate_id)
        if resolved is not None:
            return resolved
    return None


def _patient_record(patient: Patient) -> str | None:
    """Census-comparable patient record key, or ``None`` if not usable."""
    if patient.source_system != _CENSUS_SOURCE_SYSTEM:
        return None
    key = (patient.patient_source_key or "").strip()
    return key or None


# ---------------------------------------------------------------------------
# Post-census observation
# ---------------------------------------------------------------------------


def observe_accepted_census_run(
    run_id: int | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Record absence observations for one accepted complete census run.

    Best-effort post-census hook: the orchestrator guards this call so an
    unexpected failure never fails the census cycle nor leaks its lock.
    Rejected, incomplete or provenance-ambiguous runs change nothing.
    """
    moment = now or timezone.now()
    accepted = _resolve_accepted_census_run(run_id)
    if accepted is None:
        return {
            "accepted": False,
            "run_id": run_id,
            "cases_created": 0,
            "cases_advanced": 0,
            "cases_resolved_reappeared": 0,
        }

    created = advanced = resolved = 0
    with transaction.atomic():
        open_cases = list(
            StaleAdmissionCase.objects.select_related(
                "admission__patient"
            ).filter(resolved_at__isnull=True)
        )
        # Merged duplicates left the clinical scan: their cases freeze
        # (never advanced nor resolved by census observation).
        cases_by_admission = {
            case.admission_id: case
            for case in open_cases
            if case.admission.merged_into_id is None
        }

        # 1. Reappearance resolves census-only suspicion without source
        #    mutation (explicit exit evidence stays untouched).
        for case in open_cases:
            if case.admission.merged_into_id is not None:
                continue
            record = _patient_record(case.admission.patient)
            if record is None or record not in accepted.occupied_keys:
                continue
            case.resolved_at = moment
            case.resolution_reason = (
                StaleAdmissionCase.ResolutionReason.REAPPEARED
            )
            case.save(
                update_fields=[
                    "resolved_at",
                    "resolution_reason",
                    "updated_at",
                ]
            )
            resolved += 1

        # 2. Absences: advance open cases idempotently; start one case per
        #    open canonical admission on a presence-to-absence transition.
        preceding: _AcceptedCensusRun | None = None
        for admission in Admission.objects.filter(
            discharge_date__isnull=True
        ).select_related("patient"):
            record = _patient_record(admission.patient)
            if record is None or record in accepted.occupied_keys:
                continue
            open_case = cases_by_admission.get(admission.pk)
            if open_case is not None:
                if open_case.last_absence_run_id == accepted.run_id:
                    continue  # same run observed twice: idempotent
                open_case.last_absence_run_id = accepted.run_id
                open_case.last_absence_at = accepted.captured_at
                open_case.save(
                    update_fields=[
                        "last_absence_run",
                        "last_absence_at",
                        "updated_at",
                    ]
                )
                advanced += 1
                continue
            if preceding is None:
                preceding = _preceding_accepted_run(accepted)
            if preceding is None or record not in preceding.occupied_keys:
                continue  # baseline or no presence-to-absence transition
            StaleAdmissionCase.objects.create(
                admission=admission,
                first_absence_run_id=accepted.run_id,
                first_absence_at=accepted.captured_at,
                last_absence_run_id=accepted.run_id,
                last_absence_at=accepted.captured_at,
            )
            created += 1

    logger.info(
        "stale-admission observation: run=%d created=%d advanced=%d "
        "resolved=%d",
        accepted.run_id,
        created,
        advanced,
        resolved,
    )

    result: dict[str, object] = {
        "accepted": True,
        "run_id": accepted.run_id,
        "cases_created": created,
        "cases_advanced": advanced,
        "cases_resolved_reappeared": resolved,
    }
    result["confirmation"] = evaluate_and_enqueue_stale_admission_cases(
        now=moment
    )
    return result


# ---------------------------------------------------------------------------
# Bounded evaluation/enqueue pass (post-census and hourly safety sweep)
# ---------------------------------------------------------------------------


def _cooling_down(case: StaleAdmissionCase, moment: datetime) -> bool:
    """Case-level cooldown; boundary equality is eligible."""
    if not case.last_enqueue_outcome or case.last_outcome_at is None:
        return False
    if (
        case.last_enqueue_outcome
        == StaleAdmissionCase.EnqueueOutcome.INCONCLUSIVE
    ):
        return moment - case.last_outcome_at < INCONCLUSIVE_COOLDOWN
    if (
        case.last_enqueue_outcome
        == StaleAdmissionCase.EnqueueOutcome.CONCLUSIVE_NO_EXIT
    ):
        return moment - case.last_outcome_at < CONCLUSIVE_NO_EXIT_COOLDOWN
    return False


def _active_admissions_only_records() -> set[str]:
    """Patient records with an active equivalent confirmation run."""
    return {
        record
        for record in IngestionRun.objects.filter(
            status__in=_ACTIVE_RUN_STATUSES,
            intent=_ADMISSIONS_ONLY_INTENT,
        ).values_list("parameters_json__patient_record", flat=True)
        if record
    }


def _conflict_evidence_anchors() -> dict[str, datetime]:
    """Latest ``reconciled_at`` per patient carrying conflict evidence."""
    anchors: dict[str, datetime] = {}
    for evidence_model in (DischargeRecord, DeathRecord):
        rows = evidence_model.objects.filter(
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT
        ).values_list("prontuario", "reconciled_at")
        for prontuario, reconciled_at in rows:
            record = (prontuario or "").strip()
            if not record or reconciled_at is None:
                continue
            current = anchors.get(record)
            if current is None or reconciled_at > current:
                anchors[record] = reconciled_at
    return anchors


def evaluate_and_enqueue_stale_admission_cases(
    *,
    now: datetime | None = None,
    max_enqueues: int = MAX_ENQUEUES_PER_CYCLE,
) -> dict[str, int]:
    """Bounded evaluation/enqueue pass; aggregate-safe counters only.

    Classifies pending enqueue outcomes from the confirmation run status
    plus admission state, resolves cases whose admission exited, and
    enqueues at most ``max_enqueues`` deduplicated ``admissions_only``
    runs in deterministic oldest-first order. The remainder stays
    eligible. Never writes clinical exit state.
    """
    moment = now or timezone.now()
    counters: dict[str, int] = {
        "open_cases": 0,
        "resolved_exit_confirmed": 0,
        "classified_inconclusive": 0,
        "classified_conclusive": 0,
        "enqueued_cases": 0,
        "enqueued_conflict": 0,
        "skipped_active_run": 0,
        "skipped_cooldown": 0,
        "not_yet_eligible": 0,
        "deferred_over_cap": 0,
    }
    candidates: list[_EnqueueCandidate] = []

    with transaction.atomic():
        # 1. Cases whose admission already exited elsewhere: the suspicion
        #    was confirmed; close the case without touching the admission.
        settled = StaleAdmissionCase.objects.filter(
            resolved_at__isnull=True,
            admission__discharge_date__isnull=False,
        )
        for case in settled:
            case.resolved_at = moment
            case.resolution_reason = (
                StaleAdmissionCase.ResolutionReason.EXIT_CONFIRMED
            )
            case.save(
                update_fields=[
                    "resolved_at",
                    "resolution_reason",
                    "updated_at",
                ]
            )
            counters["resolved_exit_confirmed"] += 1

        open_cases = list(
            StaleAdmissionCase.objects.select_related(
                "admission__patient", "last_enqueued_run"
            ).filter(
                resolved_at__isnull=True,
                admission__discharge_date__isnull=True,
                admission__merged_into__isnull=True,
            )
        )
        counters["open_cases"] = len(open_cases)

        # 2. Outcome classification at the next evaluation: run status
        #    plus admission/evidence state (admission still open here).
        for case in open_cases:
            confirmation_run = case.last_enqueued_run
            if confirmation_run is None or case.last_enqueue_outcome:
                continue
            if confirmation_run.status == "failed":
                case.last_enqueue_outcome = (
                    StaleAdmissionCase.EnqueueOutcome.INCONCLUSIVE
                )
                case.last_outcome_at = confirmation_run.finished_at or moment
                case.save(
                    update_fields=[
                        "last_enqueue_outcome",
                        "last_outcome_at",
                        "updated_at",
                    ]
                )
                counters["classified_inconclusive"] += 1
            elif confirmation_run.status == "succeeded":
                case.last_enqueue_outcome = (
                    StaleAdmissionCase.EnqueueOutcome.CONCLUSIVE_NO_EXIT
                )
                case.last_outcome_at = confirmation_run.finished_at or moment
                case.save(
                    update_fields=[
                        "last_enqueue_outcome",
                        "last_outcome_at",
                        "updated_at",
                    ]
                )
                counters["classified_conclusive"] += 1

        active_records = _active_admissions_only_records()

        # 3. Eligible absence cases.
        for case in open_cases:
            record = _patient_record(case.admission.patient)
            if record is None:
                continue
            if case.first_absence_run_id == case.last_absence_run_id:
                counters["not_yet_eligible"] += 1
                continue
            if moment - case.first_absence_at < MIN_ELIGIBILITY_IDLE:
                counters["not_yet_eligible"] += 1
                continue
            if _cooling_down(case, moment):
                counters["skipped_cooldown"] += 1
                continue
            if record in active_records:
                counters["skipped_active_run"] += 1
                continue
            candidates.append(
                _EnqueueCandidate(
                    anchor=case.first_absence_at,
                    kind="case",
                    patient_record=record,
                    case_pk=case.pk,
                )
            )

        # 4. Conflict-evidence route through the same bounded path.
        for record, anchor in _conflict_evidence_anchors().items():
            if moment - anchor < CONCLUSIVE_NO_EXIT_COOLDOWN:
                counters["skipped_cooldown"] += 1
                continue
            if record in active_records:
                counters["skipped_active_run"] += 1
                continue
            candidates.append(
                _EnqueueCandidate(
                    anchor=anchor,
                    kind="conflict",
                    patient_record=record,
                )
            )

        # 5. Deterministic oldest-first selection under the shared cap.
        candidates.sort(
            key=lambda candidate: (
                candidate.anchor,
                candidate.kind,
                candidate.patient_record,
            )
        )
        for candidate in candidates:
            if candidate.patient_record in active_records:
                # Enqueued earlier inside this same pass.
                counters["skipped_active_run"] += 1
                continue
            if counters["enqueued_cases"] + counters["enqueued_conflict"] >= (
                max_enqueues
            ):
                counters["deferred_over_cap"] += 1
                continue
            run = queue_admissions_only_run(
                patient_record=candidate.patient_record
            )
            if candidate.case_pk is not None:
                StaleAdmissionCase.objects.filter(
                    pk=candidate.case_pk
                ).update(
                    last_enqueued_run=run,
                    last_enqueued_at=moment,
                    last_enqueue_outcome="",
                    last_outcome_at=None,
                    updated_at=moment,
                )
                counters["enqueued_cases"] += 1
            else:
                counters["enqueued_conflict"] += 1
            active_records.add(candidate.patient_record)

    logger.info(
        "stale-admission confirmation pass: enqueued_cases=%d "
        "enqueued_conflict=%d skipped_active=%d skipped_cooldown=%d "
        "deferred=%d",
        counters["enqueued_cases"],
        counters["enqueued_conflict"],
        counters["skipped_active_run"],
        counters["skipped_cooldown"],
        counters["deferred_over_cap"],
    )
    return counters


# ---------------------------------------------------------------------------
# Safety sweep advisory lock (distinct from the orchestrator lock)
# ---------------------------------------------------------------------------


def acquire_stale_admission_sweep_lock() -> bool:
    """Try to acquire the safety-sweep coordination lock (non-blocking)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            [STALE_ADMISSION_SWEEP_LOCK_KEY],
        )
        (acquired,) = cursor.fetchone()
    return bool(acquired)


def release_stale_admission_sweep_lock() -> bool:
    """Release the safety-sweep coordination lock."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s)",
            [STALE_ADMISSION_SWEEP_LOCK_KEY],
        )
        (released,) = cursor.fetchone()
    return bool(released)
