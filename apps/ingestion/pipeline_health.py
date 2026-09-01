"""RPAP-S5: one-shot read-only aggregate health evaluation for the
census-to-evolution ingestion pipeline.

This module answers "is the pipeline healthy?" using strictly aggregate
metrics over the configured window:

- batch-bound invariants: succeeded empty admissions, missing full-sync
  follow-up after settling, duplicate batch-owned demographics;
- active work age (oldest queued/running run of a supported intent);
- full-sync terminal outcome (succeeded/failed, events created, failures
  grouped by normalized reason);
- optional domain freshness (latest movement, admission update and
  clinical event).

The evaluation is read-only: it never creates, updates or deletes rows and
never calls the source system, browser automation, the network or another
command. Output layers (the management command) must render only aggregated
values; this module never returns identifiers, parameter payloads, clinical
text or raw errors. Batch+patient correspondence keys stay in ephemeral
memory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.census.models import PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.extractors.patient_flow_snapshot import (
    OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
    EncounterRecency,
)
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission

# ---------------------------------------------------------------------------
# Configurable defaults (documented in deploy/README.md)
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_HOURS = 24
DEFAULT_SETTLING_MINUTES = 60
DEFAULT_MAX_ACTIVE_AGE_MINUTES = 120
DEFAULT_MAX_FULL_SYNC_FAILURE_PERCENT = 20.0
DEFAULT_MIN_FULL_SYNC_TERMINAL_SAMPLE = 5

# Supported work intents: anything else is not part of this pipeline's
# queue-age contract (e.g. historical backfill runs).
_ACTIVE_INTENTS = (
    "admissions_only",
    "demographics_only",
    "full_sync",
    "full_admission_sync",
)
_FULL_SYNC_INTENTS = ("full_sync", "full_admission_sync")
_NONE_REASON_LABEL = "none"

# PFIF-S5: the only evidence that may exclude a batch-bound empty
# admissions success from the ``empty_success`` invariant is the exact
# closed stage outcome recorded by the S1/S2 workers: a succeeded
# ``encounter_fallback`` stage whose details carry the allowlisted outcome
# AND recency values. Anything else (unknown outcome, wrong stage,
# boundary/stale/none recency, partial or forged details, failed stage)
# stays an anomaly. Shared with the portal presentation (single source).
ENCOUNTER_FALLBACK_STAGE = "encounter_fallback"
RECENT_CONFIRMED_RECENCY = EncounterRecency.RECENT_CONFIRMED.value

# Stable violation codes shared with the management command output.
V_EMPTY_SUCCESS = "empty_success"
V_MISSING_FULL_SYNC = "missing_full_sync"
V_DUPLICATE_DEMOGRAPHICS = "duplicate_demographics"
V_ACTIVE_QUEUE_AGE = "active_queue_age"
V_FULL_SYNC_FAILURE_RATE = "full_sync_failure_rate"
V_MOVEMENT_FRESHNESS = "movement_freshness"
V_ADMISSION_FRESHNESS = "admission_freshness"
V_EVENT_FRESHNESS = "event_freshness"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthConfig:
    """Operator-supplied window, settling and threshold settings."""

    window_hours: int = DEFAULT_WINDOW_HOURS
    settling_minutes: int = DEFAULT_SETTLING_MINUTES
    max_active_age_minutes: int = DEFAULT_MAX_ACTIVE_AGE_MINUTES
    max_full_sync_failure_percent: float = DEFAULT_MAX_FULL_SYNC_FAILURE_PERCENT
    min_full_sync_terminal_sample: int = DEFAULT_MIN_FULL_SYNC_TERMINAL_SAMPLE
    max_movement_age_hours: int | None = None
    max_admission_age_hours: int | None = None
    max_event_age_hours: int | None = None


@dataclass(frozen=True)
class BatchInvariants:
    empty_success_count: int = 0
    missing_full_sync_count: int = 0
    duplicate_demographics_count: int = 0
    recognized_recent_encounter_count: int = 0


@dataclass(frozen=True)
class QueueStats:
    active_count: int = 0
    oldest_age_minutes: int = 0


@dataclass(frozen=True)
class FullSyncStats:
    terminal_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    events_created: int = 0
    failure_reasons: tuple[tuple[str, int], ...] = ()
    failure_percent: float | None = None


@dataclass(frozen=True)
class FreshnessStats:
    movement_present: bool = False
    movement_age_minutes: int | None = None
    admission_present: bool = False
    admission_age_minutes: int | None = None
    event_present: bool = False
    event_age_minutes: int | None = None


@dataclass(frozen=True)
class HealthViolation:
    """A single violated invariant/threshold with its aggregate count."""

    code: str
    count: int


@dataclass(frozen=True)
class HealthResult:
    """Aggregate evaluation result; ``healthy`` means no violations."""

    window_hours: int
    invariants: BatchInvariants
    queue: QueueStats
    full_sync: FullSyncStats
    freshness: FreshnessStats
    violations: tuple[HealthViolation, ...] = ()

    @property
    def healthy(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_pipeline_health(
    config: HealthConfig,
    *,
    now: datetime | None = None,
) -> HealthResult:
    """Evaluate the pipeline over ``config.window_hours`` ending at ``now``.

    Read-only: only SELECT aggregates. ``now`` defaults to
    ``timezone.now()`` and is injectable for deterministic tests.
    """
    now = now or timezone.now()
    since = now - timedelta(hours=config.window_hours)
    violations: list[HealthViolation] = []

    invariants = _evaluate_batch_invariants(config, now, since, violations)
    queue = _evaluate_queue(config, now, violations)
    full_sync = _evaluate_full_sync(config, since, violations)
    freshness = _evaluate_freshness(config, now, violations)

    return HealthResult(
        window_hours=config.window_hours,
        invariants=invariants,
        queue=queue,
        full_sync=full_sync,
        freshness=freshness,
        violations=tuple(violations),
    )


def _evaluate_batch_invariants(
    config: HealthConfig,
    now: datetime,
    since: datetime,
    violations: list[HealthViolation],
) -> BatchInvariants:
    window_empty = IngestionRun.objects.filter(
        status="succeeded",
        intent="admissions_only",
        batch_id__isnull=False,
        admissions_seen=0,
        finished_at__gte=since,
    )
    empty_total = window_empty.count()

    # PFIF-S5 (R1): an empty success is "recognized" only with the exact
    # allowlisted encounter-fallback evidence; the strict join conditions
    # below reject wrong stage, wrong status, unknown outcome and any
    # recency other than ``recent_confirmed``. DISTINCT keeps the count
    # correct even if a run ever carried more than one matching stage row.
    recognized = (
        window_empty.filter(
            stage_metrics__stage_name=ENCOUNTER_FALLBACK_STAGE,
            stage_metrics__status="succeeded",
            stage_metrics__details_json__outcome=(
                OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION
            ),
            stage_metrics__details_json__recency=RECENT_CONFIRMED_RECENCY,
        )
        .values("pk")
        .distinct()
        .count()
    )
    empty_success = empty_total - recognized

    # Succeeded non-empty batch-bound admissions (batch, patient) keys with
    # their finish time; only keys settled long enough are compared against
    # the full-sync follow-up set.
    admissions_rows = IngestionRun.objects.filter(
        status="succeeded",
        intent="admissions_only",
        batch_id__isnull=False,
        admissions_seen__gt=0,
        finished_at__gte=since,
    ).values_list("batch_id", "parameters_json__patient_record", "finished_at")
    settled_at = now - timedelta(minutes=config.settling_minutes)
    settled_non_empty = {
        (batch_id, patient_record)
        for batch_id, patient_record, finished_at in admissions_rows
        if finished_at is not None and finished_at <= settled_at
    }

    # A full-sync follow-up is enqueued immediately after the admissions
    # run succeeds, so any corresponding key is also inside the window;
    # bounding the set keeps the ephemeral comparison small.
    full_sync_keys = set(
        IngestionRun.objects.filter(
            intent__in=_FULL_SYNC_INTENTS,
            batch_id__isnull=False,
            queued_at__gte=since,
        ).values_list("batch_id", "parameters_json__patient_record")
    )
    missing_full_sync = len(settled_non_empty - full_sync_keys)

    demographics_pairs = Counter(
        IngestionRun.objects.filter(
            intent="demographics_only",
            batch_id__isnull=False,
            queued_at__gte=since,
        ).values_list("batch_id", "parameters_json__patient_record")
    )
    duplicate_demographics = sum(
        1 for count in demographics_pairs.values() if count > 1
    )

    if empty_success:
        violations.append(HealthViolation(V_EMPTY_SUCCESS, empty_success))
    if missing_full_sync:
        violations.append(
            HealthViolation(V_MISSING_FULL_SYNC, missing_full_sync)
        )
    if duplicate_demographics:
        violations.append(
            HealthViolation(V_DUPLICATE_DEMOGRAPHICS, duplicate_demographics)
        )

    return BatchInvariants(
        empty_success_count=empty_success,
        missing_full_sync_count=missing_full_sync,
        duplicate_demographics_count=duplicate_demographics,
        recognized_recent_encounter_count=recognized,
    )


def _evaluate_queue(
    config: HealthConfig,
    now: datetime,
    violations: list[HealthViolation],
) -> QueueStats:
    active = IngestionRun.objects.filter(
        status__in=("queued", "running"),
        intent__in=_ACTIVE_INTENTS,
    )
    active_count = active.count()
    oldest = active.order_by("queued_at").first()
    oldest_age_minutes = 0
    if oldest is not None:
        oldest_age_minutes = _rounded_minutes(
            max(0.0, (now - oldest.queued_at).total_seconds() / 60.0)
        )
    if oldest_age_minutes > config.max_active_age_minutes:
        violations.append(HealthViolation(V_ACTIVE_QUEUE_AGE, 1))
    return QueueStats(
        active_count=active_count,
        oldest_age_minutes=oldest_age_minutes,
    )


def _evaluate_full_sync(
    config: HealthConfig,
    since: datetime,
    violations: list[HealthViolation],
) -> FullSyncStats:
    terminal = IngestionRun.objects.filter(
        intent__in=_FULL_SYNC_INTENTS,
        status__in=("succeeded", "failed"),
        finished_at__gte=since,
    )
    aggregated = terminal.aggregate(
        succeeded=Count("pk", filter=Q(status="succeeded")),
        failed=Count("pk", filter=Q(status="failed")),
        events_created=Coalesce(Sum("events_created"), 0),
    )
    succeeded = int(aggregated["succeeded"])
    failed = int(aggregated["failed"])
    terminal_count = succeeded + failed
    events_created = int(aggregated["events_created"])

    reasons = tuple(
        sorted(
            (reason or _NONE_REASON_LABEL, count)
            for reason, count in terminal.filter(status="failed")
            .values("failure_reason")
            .annotate(count=Count("pk"))
            .values_list("failure_reason", "count")
        )
    )
    failure_percent: float | None = None
    if terminal_count:
        failure_percent = round(100.0 * failed / terminal_count, 1)
    if (
        terminal_count >= config.min_full_sync_terminal_sample
        and failure_percent is not None
        and failure_percent > config.max_full_sync_failure_percent
    ):
        violations.append(HealthViolation(V_FULL_SYNC_FAILURE_RATE, 1))

    return FullSyncStats(
        terminal_count=terminal_count,
        succeeded_count=succeeded,
        failed_count=failed,
        events_created=events_created,
        failure_reasons=reasons,
        failure_percent=failure_percent,
    )


def _evaluate_freshness(
    config: HealthConfig,
    now: datetime,
    violations: list[HealthViolation],
) -> FreshnessStats:
    movement_present, movement_age = _latest_age_minutes(
        now, PatientMovement.objects.all(), "last_seen_at"
    )
    admission_present, admission_age = _latest_age_minutes(
        now, Admission.objects.all(), "updated_at"
    )
    event_present, event_age = _latest_age_minutes(
        now, ClinicalEvent.objects.all(), "created_at"
    )

    _freshness_violation(
        config.max_movement_age_hours,
        movement_present,
        movement_age,
        V_MOVEMENT_FRESHNESS,
        violations,
    )
    _freshness_violation(
        config.max_admission_age_hours,
        admission_present,
        admission_age,
        V_ADMISSION_FRESHNESS,
        violations,
    )
    _freshness_violation(
        config.max_event_age_hours,
        event_present,
        event_age,
        V_EVENT_FRESHNESS,
        violations,
    )

    return FreshnessStats(
        movement_present=movement_present,
        movement_age_minutes=movement_age,
        admission_present=admission_present,
        admission_age_minutes=admission_age,
        event_present=event_present,
        event_age_minutes=event_age,
    )


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _freshness_violation(
    max_age_hours: int | None,
    present: bool,
    age_minutes: int | None,
    code: str,
    violations: list[HealthViolation],
) -> None:
    """Append a freshness violation only when an operator threshold is set.

    Absence of the domain timestamp is unhealthy only when the
    corresponding threshold is active; otherwise freshness is
    informational (R4).
    """
    if max_age_hours is None:
        return
    if not present or age_minutes is None or age_minutes > max_age_hours * 60:
        violations.append(HealthViolation(code, 1))


def _latest_age_minutes(
    now: datetime,
    queryset,
    field: str,
) -> tuple[bool, int | None]:
    """Return (present, rounded age in minutes) of the latest row value."""
    latest = queryset.aggregate(latest=Max(field))["latest"]
    if latest is None:
        return False, None
    return True, _rounded_minutes(max(0.0, (now - latest).total_seconds() / 60.0))


def _rounded_minutes(minutes: float) -> int:
    """Round a float minute count to a whole number for display."""
    return int(round(minutes))
