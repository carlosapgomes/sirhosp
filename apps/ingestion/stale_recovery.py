"""Stale IngestionRun recovery service.

The service intentionally uses only operational identifiers and timestamps. It
never reads patient payload fields when reporting or mutating stale runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.ingestion.batch_closure import try_close_batch
from apps.ingestion.models import IngestionRun

DEFAULT_HEARTBEAT_GRACE = timedelta(minutes=10)
DEFAULT_MAX_RUNS_PER_SWEEP = 20
DEFAULT_STALE_LIMIT = timedelta(minutes=60)
DEFAULT_INTENT_LIMITS = {
    "admissions_only": timedelta(minutes=20),
    "demographics_only": timedelta(minutes=20),
    "full_sync": timedelta(minutes=60),
    "census_extraction": timedelta(minutes=120),
}
SAFE_ERROR_MESSAGE = "Stale recovery marked this running ingestion run as failed."


@dataclass(frozen=True)
class StaleRunCandidate:
    """Operational summary for a stale recovery candidate."""

    run_id: int
    batch_id: int | None
    intent: str
    status: str
    worker_label: str
    reference_at: datetime
    age_seconds: int
    worker_heartbeat_at: datetime | None
    stale_limit_seconds: int


@dataclass(frozen=True)
class StaleRecoveryResult:
    """Outcome of one stale-recovery sweep."""

    candidates: list[StaleRunCandidate]
    apply: bool
    max_runs_per_sweep: int
    aborted: bool = False
    abort_reason: str = ""
    marked_failed_run_ids: list[int] = field(default_factory=list)
    skipped_run_ids: list[int] = field(default_factory=list)
    closed_batch_ids: list[int] = field(default_factory=list)

    @property
    def dry_run(self) -> bool:
        return not self.apply


def _normalise_intent(intent: str | None) -> str:
    return (intent or "").strip()


def _limit_for_intent(
    intent: str | None,
    intent_limits: dict[str, timedelta] | None,
    default_limit: timedelta,
) -> timedelta:
    limits = intent_limits or DEFAULT_INTENT_LIMITS
    return limits.get(_normalise_intent(intent), default_limit)


def _reference_time(run: IngestionRun) -> datetime:
    return (
        run.processing_started_at
        or run.queued_at
        or run.started_at
        or timezone.now()
    )


def find_stale_run_candidates(
    *,
    now: datetime | None = None,
    heartbeat_grace: timedelta = DEFAULT_HEARTBEAT_GRACE,
    intent_limits: dict[str, timedelta] | None = None,
    default_limit: timedelta = DEFAULT_STALE_LIMIT,
) -> list[StaleRunCandidate]:
    """Return running runs whose age and heartbeat classify them abandoned."""
    current_time = now or timezone.now()
    candidates: list[StaleRunCandidate] = []

    runs = (
        IngestionRun.objects.filter(status="running")
        .only(
            "id",
            "batch_id",
            "status",
            "intent",
            "worker_label",
            "worker_heartbeat_at",
            "processing_started_at",
            "queued_at",
            "started_at",
        )
        .order_by("id")
    )
    for run in runs:
        reference_at = _reference_time(run)
        stale_limit = _limit_for_intent(run.intent, intent_limits, default_limit)
        age = current_time - reference_at
        heartbeat_is_stale = (
            run.worker_heartbeat_at is None
            or current_time - run.worker_heartbeat_at > heartbeat_grace
        )
        if age <= stale_limit or not heartbeat_is_stale:
            continue

        candidates.append(
            StaleRunCandidate(
                run_id=run.pk,
                batch_id=run.batch_id,
                intent=_normalise_intent(run.intent),
                status=run.status,
                worker_label=run.worker_label,
                reference_at=reference_at,
                age_seconds=int(age.total_seconds()),
                worker_heartbeat_at=run.worker_heartbeat_at,
                stale_limit_seconds=int(stale_limit.total_seconds()),
            )
        )

    return candidates


def _build_safe_error_message(candidate: StaleRunCandidate) -> str:
    age_minutes = candidate.age_seconds // 60
    limit_minutes = candidate.stale_limit_seconds // 60
    return (
        f"{SAFE_ERROR_MESSAGE} "
        f"run_id={candidate.run_id} intent={candidate.intent or 'unknown'} "
        f"age_minutes={age_minutes} limit_minutes={limit_minutes}."
    )


def recover_stale_ingestion_runs(
    *,
    apply: bool,
    now: datetime | None = None,
    heartbeat_grace: timedelta = DEFAULT_HEARTBEAT_GRACE,
    intent_limits: dict[str, timedelta] | None = None,
    default_limit: timedelta = DEFAULT_STALE_LIMIT,
    max_runs_per_sweep: int = DEFAULT_MAX_RUNS_PER_SWEEP,
) -> StaleRecoveryResult:
    """Inspect or terminally fail abandoned running ingestion runs.

    Dry-run mode returns candidates without mutation. Apply mode aborts without
    mutation when the candidate count exceeds ``max_runs_per_sweep``.
    """
    current_time = now or timezone.now()
    candidates = find_stale_run_candidates(
        now=current_time,
        heartbeat_grace=heartbeat_grace,
        intent_limits=intent_limits,
        default_limit=default_limit,
    )

    if not apply:
        return StaleRecoveryResult(
            candidates=candidates,
            apply=False,
            max_runs_per_sweep=max_runs_per_sweep,
        )

    if len(candidates) > max_runs_per_sweep:
        return StaleRecoveryResult(
            candidates=candidates,
            apply=True,
            max_runs_per_sweep=max_runs_per_sweep,
            aborted=True,
            abort_reason="candidate_count_exceeded_limit",
        )

    marked_failed_run_ids: list[int] = []
    skipped_run_ids: list[int] = []
    batch_ids_to_close: set[int] = set()

    with transaction.atomic():
        for candidate in candidates:
            updated = IngestionRun.objects.filter(
                pk=candidate.run_id,
                status="running",
            ).update(
                status="failed",
                finished_at=current_time,
                timed_out=True,
                failure_reason="timeout",
                next_retry_at=None,
                error_message=_build_safe_error_message(candidate),
            )
            if updated == 1:
                marked_failed_run_ids.append(candidate.run_id)
                if candidate.batch_id is not None:
                    batch_ids_to_close.add(candidate.batch_id)
            else:
                skipped_run_ids.append(candidate.run_id)

        closed_batch_ids: list[int] = []
        for batch_id in sorted(batch_ids_to_close):
            run = (
                IngestionRun.objects.select_related("batch")
                .filter(pk__in=marked_failed_run_ids, batch_id=batch_id)
                .first()
            )
            if run is not None and try_close_batch(run.batch, now=current_time):
                closed_batch_ids.append(batch_id)

    return StaleRecoveryResult(
        candidates=candidates,
        apply=True,
        max_runs_per_sweep=max_runs_per_sweep,
        marked_failed_run_ids=marked_failed_run_ids,
        skipped_run_ids=skipped_run_ids,
        closed_batch_ids=closed_batch_ids,
    )
