"""RPAP-S5: one-shot read-only aggregate health evaluation for the
census-to-evolution ingestion pipeline.

This module answers "is the pipeline healthy?" using strictly aggregate
metrics over the configured window:

- batch-bound invariants: succeeded empty admissions, missing full-sync
  follow-up after settling, duplicate batch-owned demographics;
- active work age (oldest queued/running run of a supported intent);
- full-sync terminal outcome (succeeded/failed, events created, failures
  grouped by normalized reason);
- exit reconciliation (RPSA-S10): review-queue backlog by status group
  (pending/ambiguous/conflict evidence plus open stale-admission cases
  as a fourth group), source-confirmed duplicate admissions, discharge
  extraction coverage keyed by extraction date from durable
  ``IngestionRun``/``IngestionRunStageMetric`` metadata and the count of
  canonical open admissions absent from the most recent census;
- optional domain freshness (latest movement, admission update and
  clinical event).

Reconciliation evidence is aggregate-only: ``ReconciliationEvent`` rows
are append-only audit and are never counted as pending work. Coverage
distinguishes nonzero success from confirmed zero (``zero_confirmed``
with two attempts on the ``discharge_persistence`` stage) and never
reads in-memory extraction results or ``DailyDischargeCount``. Health
reports an operator-action condition for large coverage gaps; it NEVER
starts recovery itself and never creates cases.

The evaluation is read-only: it never creates, updates or deletes rows and
never calls the source system, browser automation, the network or another
command. Output layers (the management command) must render only aggregated
values; this module never returns identifiers, parameter payloads, clinical
text or raw errors. Batch+patient correspondence keys stay in ephemeral
memory.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from django.db.models import Count, Exists, Max, Min, OuterRef, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.ingestion.extractors.patient_flow_snapshot import (
    OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
    EncounterRecency,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric
from apps.patients.models import (
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    Admission,
    StaleAdmissionCase,
)
from apps.patients.services import TZ_ADMISSION_IDENTITY

# ---------------------------------------------------------------------------
# Configurable defaults (documented in deploy/README.md)
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_HOURS = 24
DEFAULT_SETTLING_MINUTES = 60
DEFAULT_MAX_ACTIVE_AGE_MINUTES = 120
DEFAULT_MAX_FULL_SYNC_FAILURE_PERCENT = 20.0
DEFAULT_MIN_FULL_SYNC_TERMINAL_SAMPLE = 5

# RPSA-S10 reconciliation thresholds with safe defaults, documented in
# deploy/README.md section 6.1 together with the daily integrity command.
DEFAULT_MISSING_DATES_MAX = 7
DEFAULT_BACKLOG_AGE_MAX_HOURS = 48
DEFAULT_CONFLICT_MAX_COUNT = 0
DEFAULT_DUPLICATE_MAX_COUNT = 0

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

# RPSA-S10: durable discharge extraction coverage keys and review-queue
# backlog groups. Anchors reuse the RPSA-S6 review-queue semantics.
_DISCHARGE_INTENT = "discharge_extraction"
DISCHARGE_PERSISTENCE_STAGE = "discharge_persistence"
_CENSUS_SOURCE_SYSTEM = "tasy"
_CONFIRMED_ZERO_MIN_ATTEMPTS = 2
_BACKLOG_GROUP_PENDING = "pending"
_BACKLOG_GROUP_AMBIGUOUS = "ambiguous"
_BACKLOG_GROUP_CONFLICT = "conflict"
_BACKLOG_GROUP_STALE_CASES = "stale_cases"
_AGE_THRESHOLD_GROUPS = (_BACKLOG_GROUP_PENDING, _BACKLOG_GROUP_AMBIGUOUS)

# Stable violation codes shared with the management command output.
V_EMPTY_SUCCESS = "empty_success"
V_MISSING_FULL_SYNC = "missing_full_sync"
V_DUPLICATE_DEMOGRAPHICS = "duplicate_demographics"
V_ACTIVE_QUEUE_AGE = "active_queue_age"
V_FULL_SYNC_FAILURE_RATE = "full_sync_failure_rate"
V_MOVEMENT_FRESHNESS = "movement_freshness"
V_ADMISSION_FRESHNESS = "admission_freshness"
V_EVENT_FRESHNESS = "event_freshness"
V_BACKLOG_AGE = "reconciliation_backlog_age"
V_CONFLICT_EVIDENCE = "reconciliation_conflict_evidence"
V_DUPLICATE_PAIR = "reconciliation_duplicate_pair"
V_EXTRACTION_GAP = "extraction_coverage_gap"


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
    missing_dates_max: int = DEFAULT_MISSING_DATES_MAX
    backlog_age_max_hours: int = DEFAULT_BACKLOG_AGE_MAX_HOURS
    conflict_max_count: int = DEFAULT_CONFLICT_MAX_COUNT
    duplicate_max_count: int = DEFAULT_DUPLICATE_MAX_COUNT


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
class BacklogGroupStats:
    """One review-queue backlog group: count plus oldest anchor age."""

    name: str
    count: int
    oldest_age_hours: int | None


@dataclass(frozen=True)
class ExtractionCoverageStats:
    """Durable discharge-extraction coverage keyed by extraction date."""

    dates_total: int = 0
    complete_dates: int = 0
    incomplete_dates: int = 0
    missing_dates: int = 0
    gap_count: int = 0
    gap_first_date: date | None = None
    gap_last_date: date | None = None


@dataclass(frozen=True)
class ReconciliationHealthStats:
    """Aggregate reconciliation section (RPSA-S10), identity-free."""

    backlog: tuple[BacklogGroupStats, ...]
    duplicate_pairs: int
    open_outside_census: int
    coverage: ExtractionCoverageStats


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
    reconciliation: ReconciliationHealthStats
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
    reconciliation = _evaluate_exit_reconciliation(config, now, violations)

    return HealthResult(
        window_hours=config.window_hours,
        invariants=invariants,
        queue=queue,
        full_sync=full_sync,
        freshness=freshness,
        reconciliation=reconciliation,
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
# RPSA-S10: exit reconciliation (backlog, duplicates, coverage, census)
# ---------------------------------------------------------------------------


def _evaluate_exit_reconciliation(
    config: HealthConfig,
    now: datetime,
    violations: list[HealthViolation],
) -> ReconciliationHealthStats:
    """Evaluate reconciliation health strictly read-only and identity-free."""
    backlog = _evaluate_backlog_groups(config, now, violations)
    duplicate_pairs = _evaluate_duplicate_pairs(config, violations)
    coverage = _evaluate_extraction_coverage(config, violations)
    open_outside_census = _evaluate_open_outside_census()
    return ReconciliationHealthStats(
        backlog=backlog,
        duplicate_pairs=duplicate_pairs,
        open_outside_census=open_outside_census,
        coverage=coverage,
    )


def _evaluate_backlog_groups(
    config: HealthConfig,
    now: datetime,
    violations: list[HealthViolation],
) -> tuple[BacklogGroupStats, ...]:
    """Count and age the review-queue backlog per status group.

    Groups follow the RPSA-S6 review-queue semantics: pending, ambiguous
    and conflict ``DischargeRecord``/``DeathRecord`` evidence plus open
    ``StaleAdmissionCase`` rows as a fourth group. ``ReconciliationEvent``
    rows are append-only audit and are never counted as pending work.
    """
    groups: list[BacklogGroupStats] = []
    for name, status in (
        (_BACKLOG_GROUP_PENDING, RECONCILIATION_STATUS_PENDING),
        (_BACKLOG_GROUP_AMBIGUOUS, RECONCILIATION_STATUS_AMBIGUOUS),
        (_BACKLOG_GROUP_CONFLICT, RECONCILIATION_STATUS_CONFLICT),
    ):
        count, anchor = _evidence_backlog(status)
        groups.append(_backlog_group(name, count, anchor, now))

    open_cases = StaleAdmissionCase.objects.filter(resolved_at__isnull=True).aggregate(
        count=Count("pk"), oldest=Min("first_absence_at")
    )
    groups.append(
        _backlog_group(
            _BACKLOG_GROUP_STALE_CASES,
            int(open_cases["count"]),
            open_cases["oldest"],
            now,
        )
    )

    for group in groups:
        if group.name not in _AGE_THRESHOLD_GROUPS:
            continue
        if group.oldest_age_hours is None:
            continue
        if group.oldest_age_hours > config.backlog_age_max_hours:
            violations.append(HealthViolation(V_BACKLOG_AGE, 1))
    conflict_count = _find_group(groups, _BACKLOG_GROUP_CONFLICT).count
    if conflict_count > config.conflict_max_count:
        violations.append(HealthViolation(V_CONFLICT_EVIDENCE, conflict_count))
    return tuple(groups)


def _evidence_backlog(status: str) -> tuple[int, datetime | None]:
    """Count and oldest anchor of one evidence status across exit kinds.

    Anchors mirror the RPSA-S6 review queue: ``saida_em`` else ``alta_em``
    for discharge evidence; ``obito_em`` else midnight (UTC) of the death
    date for death evidence. Rows without any anchor keep their count but
    contribute no age.
    """
    discharge = DischargeRecord.objects.filter(
        reconciliation_status=status
    ).aggregate(
        count=Count("pk"),
        oldest_exit=Min("saida_em"),
        oldest_after_exit=Min("alta_em", filter=Q(saida_em__isnull=True)),
    )
    death = DeathRecord.objects.filter(reconciliation_status=status).aggregate(
        count=Count("pk"),
        oldest_death=Min("obito_em"),
        oldest_date_only=Min("date", filter=Q(obito_em__isnull=True)),
    )
    count = int(discharge["count"]) + int(death["count"])
    anchors = [
        value
        for value in (
            discharge["oldest_exit"],
            discharge["oldest_after_exit"],
            death["oldest_death"],
            _midnight_utc(death["oldest_date_only"]),
        )
        if value is not None
    ]
    return count, (min(anchors) if anchors else None)


def _backlog_group(
    name: str,
    count: int,
    anchor: datetime | None,
    now: datetime,
) -> BacklogGroupStats:
    oldest_age_hours: int | None = None
    if anchor is not None:
        oldest_age_hours = _rounded_hours(
            max(0.0, (now - anchor).total_seconds() / 3600.0)
        )
    return BacklogGroupStats(
        name=name, count=count, oldest_age_hours=oldest_age_hours
    )


def _find_group(
    groups: list[BacklogGroupStats], name: str
) -> BacklogGroupStats:
    return next(group for group in groups if group.name == name)


def _evaluate_duplicate_pairs(
    config: HealthConfig,
    violations: list[HealthViolation],
) -> int:
    """Count source-confirmed duplicate pairs (RPSA-S9 cohort shape)."""
    duplicate_pairs = _confirmed_duplicate_pairs()
    if duplicate_pairs > config.duplicate_max_count:
        violations.append(HealthViolation(V_DUPLICATE_PAIR, duplicate_pairs))
    return duplicate_pairs


def _confirmed_duplicate_pairs() -> int:
    """Open canonical admissions with a fresher same-day closed twin.

    One correlated COUNT over canonical admissions: same patient, same
    ``America/Bahia`` local admission date, closed row at least as fresh
    (``updated_at``) as the open row — the exact RPSA-S9 duplicate-cohort
    shape. Merged rows left the canonical manager and never count.
    """
    closed_twin = (
        Admission.objects.filter(
            discharge_date__isnull=False,
            admission_date__isnull=False,
        )
        .annotate(
            closed_local_date=TruncDate(
                "admission_date", tzinfo=TZ_ADMISSION_IDENTITY
            )
        )
        .filter(
            patient_id=OuterRef("patient_id"),
            closed_local_date=OuterRef("open_local_date"),
            updated_at__gte=OuterRef("updated_at"),
        )
    )
    return (
        Admission.objects.filter(
            discharge_date__isnull=True,
            admission_date__isnull=False,
        )
        .annotate(
            open_local_date=TruncDate(
                "admission_date", tzinfo=TZ_ADMISSION_IDENTITY
            )
        )
        .filter(Exists(closed_twin))
        .count()
    )


def _evaluate_extraction_coverage(
    config: HealthConfig,
    violations: list[HealthViolation],
) -> ExtractionCoverageStats:
    """Classify discharge coverage from durable metadata only.

    Never reads in-memory extraction results or ``DailyDischargeCount``
    (derived, not coverage). A gap above ``missing_dates_max`` is an
    operator-action violation; health never starts recovery itself.
    """
    coverage = _extraction_coverage_stats()
    if coverage.gap_count > config.missing_dates_max:
        violations.append(HealthViolation(V_EXTRACTION_GAP, coverage.gap_count))
    return coverage


def _extraction_coverage_stats() -> ExtractionCoverageStats:
    """Key discharge runs by extraction date and classify each date."""
    persist_details: dict[int, list[Any]] = defaultdict(list)
    stage_rows = IngestionRunStageMetric.objects.filter(
        stage_name=DISCHARGE_PERSISTENCE_STAGE,
        run__intent=_DISCHARGE_INTENT,
    ).values_list("run_id", "details_json")
    for run_id, details_json in stage_rows:
        persist_details[run_id].append(details_json)

    best: dict[date, int] = {}
    runs = IngestionRun.objects.filter(intent=_DISCHARGE_INTENT).values_list(
        "pk", "status", "parameters_json"
    )
    for run_id, status, parameters_json in runs:
        extraction_date = _extraction_date(parameters_json)
        if extraction_date is None:
            continue
        level = 0
        if status == "succeeded":
            level = 1
            if any(
                _stage_confirms_complete(details)
                for details in persist_details.get(run_id, ())
            ):
                level = 2
        if level > best.get(extraction_date, -1):
            best[extraction_date] = level

    complete = sum(1 for level in best.values() if level == 2)
    incomplete = sum(1 for level in best.values() if level == 1)
    missing = len(best) - complete - incomplete
    gap_dates = sorted(day for day, level in best.items() if level < 2)
    return ExtractionCoverageStats(
        dates_total=len(best),
        complete_dates=complete,
        incomplete_dates=incomplete,
        missing_dates=missing,
        gap_count=len(gap_dates),
        gap_first_date=gap_dates[0] if gap_dates else None,
        gap_last_date=gap_dates[-1] if gap_dates else None,
    )


def _extraction_date(parameters_json: Any) -> date | None:
    """Durable extraction date key: ``ref_date`` ISO, else ``date`` br."""
    if not isinstance(parameters_json, dict):
        return None
    ref_date = parameters_json.get("ref_date")
    if isinstance(ref_date, str) and ref_date:
        try:
            return date.fromisoformat(ref_date)
        except ValueError:
            return None
    raw_date = parameters_json.get("date")
    if isinstance(raw_date, str) and raw_date:
        try:
            return datetime.strptime(raw_date, "%d/%m/%Y").date()
        except ValueError:
            return None
    return None


def _stage_confirms_complete(details_json: Any) -> bool:
    """Rows persisted, or zero confirmed by two attempts, means complete."""
    if not isinstance(details_json, dict):
        return False
    if _non_negative_int(details_json.get("total_records")) > 0:
        return True
    if details_json.get("zero_confirmed") is not True:
        return False
    attempts = _non_negative_int(details_json.get("attempt_count"))
    return attempts >= _CONFIRMED_ZERO_MIN_ATTEMPTS


def _non_negative_int(value: Any) -> int:
    """Coerce a durable JSON counter to a non-negative int (else zero)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _evaluate_open_outside_census() -> int:
    """Count open canonical admissions absent from the latest census.

    Informational only: no threshold, no case creation (RPSA-S5 owns
    case creation). Presence keys reuse the census-comparable record
    (tasy source, stripped ``patient_source_key``) against the occupied
    rows of the single most recent capture.
    """
    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]
    if latest is None:
        return 0
    occupied = {
        value.strip()
        for value in CensusSnapshot.objects.filter(
            captured_at=latest, bed_status=BedStatus.OCCUPIED
        ).values_list("prontuario", flat=True)
    }
    occupied.discard("")
    absent = 0
    open_admissions = Admission.objects.filter(discharge_date__isnull=True)
    for admission in open_admissions.select_related("patient"):
        patient = admission.patient
        if patient.source_system != _CENSUS_SOURCE_SYSTEM:
            absent += 1
            continue
        record = (patient.patient_source_key or "").strip()
        if not record or record not in occupied:
            absent += 1
    return absent


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


def _rounded_hours(hours: float) -> int:
    """Round a float hour count to a whole number for display."""
    return int(round(hours))


def _midnight_utc(value: date | None) -> datetime | None:
    """UTC midnight of a date-only anchor (RPSA-S6 review-queue rule)."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=dt_timezone.utc)
