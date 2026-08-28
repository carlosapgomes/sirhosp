"""CFC-S1: read-only characterization of the fail-only full-sync cohort.

This module answers "who is chronically failing full-sync, why, when and
at which stage?" using strictly aggregate metrics over a configurable
window:

- fail-only cohort detection: patients with at least ``min_attempts``
  terminal full-sync runs in the window and zero successes;
- failure reason distribution of the cohort and, as contrast baseline, of
  the fail-then-ok patients (failures followed by a success);
- per-stage duration profiles (median/p90 seconds) and the terminal
  failing stage distribution for the cohort's failed runs;
- aggregated 24-bucket hourly histogram (UTC) of the cohort's failed runs.

Privacy contract (same discipline as the pipeline health check): patient
keys are grouped only in ephemeral memory via
``parameters_json__patient_record`` and never cross the service boundary.
The evaluation is read-only (SELECT aggregates only); the management
command renders only allowlisted metric names, counts, durations,
percentiles, hours and failure reasons — never identifiers, parameter
payloads, clinical text, URLs or raw errors.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from django.utils import timezone

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

# ---------------------------------------------------------------------------
# Configurable defaults (documented in deploy/README.md)
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_HOURS = 168
DEFAULT_MIN_ATTEMPTS = 3
DEFAULT_MAX_PER_STAGE_ROWS = 5000

_FULL_SYNC_INTENTS = ("full_sync", "full_admission_sync")
_TERMINAL_STATUSES = ("succeeded", "failed")
_NONE_REASON_LABEL = "none"
_NONE_STAGE_LABEL = "none"
_HOURS_PER_DAY = 24


# ---------------------------------------------------------------------------
# Value objects (frozen; aggregates only, never identities)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterizationConfig:
    """Operator-supplied window and cohort floor settings."""

    window_hours: int = DEFAULT_WINDOW_HOURS
    min_attempts: int = DEFAULT_MIN_ATTEMPTS
    max_per_stage_rows: int = DEFAULT_MAX_PER_STAGE_ROWS


@dataclass(frozen=True)
class FailOnlyCohort:
    """Aggregate shape of the fail-only cohort (never per-patient)."""

    cohort_patients: int = 0
    cohort_failed_runs: int = 0
    attempts_median: float | None = None
    attempts_max: int = 0
    first_failure_age_hours: int | None = None
    last_failure_age_hours: int | None = None


@dataclass(frozen=True)
class ReasonDistribution:
    """(reason, count) pairs, deterministically sorted by label."""

    cohort: tuple[tuple[str, int], ...] = ()
    contrast: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class StageTimingProfile:
    """Duration profile of one stage over the cohort's failed runs."""

    stage_name: str
    duration_median_seconds: float
    duration_p90_seconds: float
    samples: int


@dataclass(frozen=True)
class HourlyDistribution:
    """24-bucket hourly (UTC) histogram of failed cohort runs."""

    hours: tuple[tuple[int, int], ...] = tuple(
        (hour, 0) for hour in range(_HOURS_PER_DAY)
    )


@dataclass(frozen=True)
class CharacterizationResult:
    """Full aggregate characterization of the fail-only cohort."""

    window_hours: int
    min_attempts: int
    cohort: FailOnlyCohort
    reasons: ReasonDistribution
    stage_profiles: tuple[StageTimingProfile, ...] = ()
    terminal_failing_stages: tuple[tuple[str, int], ...] = ()
    hourly: HourlyDistribution = HourlyDistribution()


# ---------------------------------------------------------------------------
# Characterization
# ---------------------------------------------------------------------------


def characterize_fullsync_failures(
    config: CharacterizationConfig,
    *,
    now: datetime | None = None,
) -> CharacterizationResult:
    """Characterize the fail-only full-sync cohort over the window.

    Read-only: only two bounded SELECTs. ``now`` defaults to
    ``timezone.now()`` and is injectable for deterministic tests. Patient
    keys are grouped in ephemeral memory and never returned.
    """
    now = now or timezone.now()
    since = now - timedelta(hours=config.window_hours)

    # Query 1: terminal full-sync runs inside the window. The patient key
    # (parameters_json__patient_record) stays in ephemeral memory only.
    terminal_rows = IngestionRun.objects.filter(
        intent__in=_FULL_SYNC_INTENTS,
        status__in=_TERMINAL_STATUSES,
        finished_at__gte=since,
    ).values_list(
        "pk",
        "parameters_json__patient_record",
        "status",
        "failure_reason",
        "finished_at",
        "queued_at",
    )

    runs_by_patient: dict[object, list[tuple]] = {}
    for row in terminal_rows:
        run_pk, patient_record, status, reason, finished_at, queued_at = row
        runs_by_patient.setdefault(patient_record, []).append(
            (
                run_pk,
                status,
                reason or _NONE_REASON_LABEL,
                finished_at,
                queued_at,
            )
        )

    cohort_patients = _select_fail_only_patients(runs_by_patient, config)
    fail_then_ok_patients = _select_fail_then_ok_patients(runs_by_patient)

    cohort_failed: list[tuple] = []
    for patient in cohort_patients:
        cohort_failed.extend(
            run for run in runs_by_patient[patient] if run[1] == "failed"
        )

    cohort = _aggregate_cohort(cohort_failed, runs_by_patient, cohort_patients, now)
    reasons = _aggregate_reasons(cohort_failed, runs_by_patient, fail_then_ok_patients)
    hourly = _aggregate_hourly(cohort_failed)
    stage_profiles, terminal_stages = _aggregate_stages(
        cohort_failed, config.max_per_stage_rows
    )

    return CharacterizationResult(
        window_hours=config.window_hours,
        min_attempts=config.min_attempts,
        cohort=cohort,
        reasons=reasons,
        stage_profiles=stage_profiles,
        terminal_failing_stages=terminal_stages,
        hourly=hourly,
    )


# ---------------------------------------------------------------------------
# Cohort selection (ephemeral keys)
# ---------------------------------------------------------------------------


def _select_fail_only_patients(
    runs_by_patient: dict[object, list[tuple]],
    config: CharacterizationConfig,
) -> list[object]:
    """Patients with >= min_attempts terminal runs and zero successes."""
    return [
        patient
        for patient, runs in runs_by_patient.items()
        if len(runs) >= config.min_attempts
        and all(run[1] != "succeeded" for run in runs)
    ]


def _select_fail_then_ok_patients(
    runs_by_patient: dict[object, list[tuple]],
) -> list[object]:
    """Patients with at least one success AND at least one failure.

    They are the contrast baseline (failures that recovered), never part
    of the fail-only cohort.
    """
    return [
        patient
        for patient, runs in runs_by_patient.items()
        if any(run[1] == "succeeded" for run in runs)
        and any(run[1] == "failed" for run in runs)
    ]


# ---------------------------------------------------------------------------
# Aggregates (only counts/ages/percentiles leave these helpers)
# ---------------------------------------------------------------------------


def _aggregate_cohort(
    cohort_failed: list[tuple],
    runs_by_patient: dict[object, list[tuple]],
    cohort_patients: list[object],
    now: datetime,
) -> FailOnlyCohort:
    attempts = [len(runs_by_patient[patient]) for patient in cohort_patients]
    attempts_median = float(median(attempts)) if attempts else None
    attempts_max = max(attempts) if attempts else 0

    fail_times = [run[3] for run in cohort_failed if run[3] is not None]
    first_failure_age_hours = None
    last_failure_age_hours = None
    if fail_times:
        first_failure_age_hours = _rounded_hours(now - min(fail_times))
        last_failure_age_hours = _rounded_hours(now - max(fail_times))

    return FailOnlyCohort(
        cohort_patients=len(cohort_patients),
        cohort_failed_runs=len(cohort_failed),
        attempts_median=attempts_median,
        attempts_max=attempts_max,
        first_failure_age_hours=first_failure_age_hours,
        last_failure_age_hours=last_failure_age_hours,
    )


def _aggregate_reasons(
    cohort_failed: list[tuple],
    runs_by_patient: dict[object, list[tuple]],
    fail_then_ok_patients: list[object],
) -> ReasonDistribution:
    cohort_reasons = Counter(run[2] for run in cohort_failed)
    contrast_failed = [
        run
        for patient in fail_then_ok_patients
        for run in runs_by_patient[patient]
        if run[1] == "failed"
    ]
    contrast_reasons = Counter(run[2] for run in contrast_failed)
    return ReasonDistribution(
        cohort=tuple(sorted(cohort_reasons.items())),
        contrast=tuple(sorted(contrast_reasons.items())),
    )


def _aggregate_hourly(cohort_failed: list[tuple]) -> HourlyDistribution:
    hourly = Counter(
        run[4].hour for run in cohort_failed if run[4] is not None
    )
    return HourlyDistribution(
        hours=tuple((hour, hourly.get(hour, 0)) for hour in range(_HOURS_PER_DAY))
    )


def _aggregate_stages(
    cohort_failed: list[tuple],
    max_per_stage_rows: int,
) -> tuple[tuple[StageTimingProfile, ...], tuple[tuple[str, int], ...]]:
    if not cohort_failed:
        return (), ()

    failed_run_pks = [run[0] for run in cohort_failed]
    stage_rows = IngestionRunStageMetric.objects.filter(
        run_id__in=failed_run_pks
    ).values_list("run_id", "stage_name", "status", "started_at", "finished_at")

    durations_by_stage: dict[str, list[tuple]] = {}
    failed_stages_by_run: dict[int, list[tuple]] = {}
    for run_id, stage_name, status, started_at, finished_at in stage_rows:
        if started_at is not None and finished_at is not None:
            durations_by_stage.setdefault(stage_name, []).append(
                (started_at, (finished_at - started_at).total_seconds())
            )
        if status == "failed":
            failed_stages_by_run.setdefault(run_id, []).append(
                (started_at, stage_name)
            )

    profiles = tuple(
        StageTimingProfile(
            stage_name=stage_name,
            duration_median_seconds=_median_seconds(durations, max_per_stage_rows),
            duration_p90_seconds=_p90_seconds(durations, max_per_stage_rows),
            samples=min(len(durations), max_per_stage_rows),
        )
        for stage_name, durations in sorted(durations_by_stage.items())
    )

    terminal = Counter(
        _terminal_stage(failed_stages_by_run.get(run[0], [])) for run in cohort_failed
    )
    return profiles, tuple(sorted(terminal.items()))


def _terminal_stage(failed_stages: list[tuple]) -> str:
    """Stage label of the failed stage with the latest started_at.

    ``none`` when the failed run carries no failed stage metric.
    """
    if not failed_stages:
        return _NONE_STAGE_LABEL
    _started_at, stage_name = max(failed_stages, key=lambda item: item[0] or datetime.min)
    return stage_name


def _median_seconds(rows: list[tuple], cap: int) -> float:
    """Median duration of the most recent ``cap`` rows."""
    durations = _capped_sorted_durations(rows, cap)
    if not durations:
        return 0.0
    return float(median(durations))


def _p90_seconds(rows: list[tuple], cap: int) -> float:
    """Nearest-rank 90th percentile of the capped duration sample."""
    durations = _capped_sorted_durations(rows, cap)
    if not durations:
        return 0.0
    index = math.ceil(0.90 * len(durations)) - 1
    return float(durations[index])


def _capped_sorted_durations(rows: list[tuple], cap: int) -> list[float]:
    """Most recent ``cap`` rows (by started_at), ascending durations."""
    most_recent = sorted(rows, key=lambda item: item[0] or datetime.min, reverse=True)[
        :cap
    ]
    return sorted(duration for _started_at, duration in most_recent)


def _rounded_hours(delta: timedelta) -> int:
    """Round a duration delta to whole hours for display."""
    return int(round(delta.total_seconds() / 3600.0))
