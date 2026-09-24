"""Deterministic selection of the statistical day window (DSRS-S1).

The statistical day of one ``America/Bahia`` local date ``D`` is bounded by two
accepted census photographs:

- **opening**: the first accepted census extraction run completed in
  ``[D 00:00, D 03:00)``; it may have started on the previous civil day;
- **closing**: the last accepted census extraction run started at/after
  ``D 20:00`` and completed before ``D+1 00:00``, always distinct from the
  opening;
- **anchor**: the last accepted census extraction run completed before the
  opening started; it is only a comparison base and never day evidence.

A census extraction run is *accepted* only when it succeeded, owns one complete
snapshot photograph (existing sector-coverage gate) whose rows resolve to that
single execution, and resolves the exact official occupancy measurement of the
same run. ``CensusExecutionBatch.finished_at`` never participates: it reports
the drain of clinical synchronization work, not the census photograph.

This module is read-only. It selects boundaries and reports structured reasons;
event derivation, persistence, page and export belong to later slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import QuerySet

from apps.census.models import CensusSnapshot, OccupancyMeasurement
from apps.census.services import (
    resolve_single_census_run,
    validate_snapshot_completeness,
)
from apps.ingestion.models import IngestionRun

# America/Bahia literal — never an inherited default timezone.
BAHIA_TZ = ZoneInfo("America/Bahia")

CENSUS_RUN_INTENT: str = "census_extraction"
"""Stable ingestion intent that owns a full hospital census photograph."""

OPENING_WINDOW_START = time(0, 0)
"""Opening window start (inclusive), local Bahia time."""

OPENING_WINDOW_END = time(3, 0)
"""Opening window end (exclusive), local Bahia time."""

CLOSING_WINDOW_START = time(20, 0)
"""Closing window start (inclusive), local Bahia time."""

INCOMPLETE_MISSING_OPENING = "missing_accepted_opening_census"
"""Structured reason: no accepted census completed in the opening window."""

INCOMPLETE_MISSING_CLOSING = "missing_accepted_closing_census"
"""Structured reason: no accepted census completed in the closing window."""

INCOMPLETE_OPENING_EQUALS_CLOSING = "closing_not_distinct_from_opening"
"""Structured reason: a single anomalous run would supply both boundaries."""

QUALITY_MISSING_ANCHOR = "missing_accepted_anchor_census"
"""Quality degradation: no accepted census precedes the opening."""

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class AcceptedCensus:
    """One accepted census extraction run and its exact official measurement."""

    run: IngestionRun
    measurement: OccupancyMeasurement


@dataclass(frozen=True)
class DailyStatisticsWindow:
    """Deterministic boundaries of one statistical day (Bahia local date).

    A day is complete when both mandatory boundaries were selected; it may
    still carry quality warnings when the anchor photograph is absent.
    """

    local_date: date
    opening: AcceptedCensus | None
    closing: AcceptedCensus | None
    anchor: AcceptedCensus | None
    incomplete_reasons: tuple[str, ...] = ()
    quality_warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """True when opening and closing were both selected."""
        return not self.incomplete_reasons


def select_daily_statistics_window(local_date: date) -> DailyStatisticsWindow:
    """Select opening, closing and anchor census of one Bahia local date.

    Selection is deterministic and read-only: it never creates, updates or
    deletes source records and never invents movements.

    Args:
        local_date: Local ``America/Bahia`` calendar date to evaluate.

    Returns:
        A :class:`DailyStatisticsWindow` with the selected boundaries, the
        structured reasons of an incomplete day and any quality warnings.
    """
    opening = _first_accepted(_opening_candidates(local_date))
    closing = _first_accepted(_closing_candidates(local_date))

    incomplete_reasons: list[str] = []
    if opening is None:
        incomplete_reasons.append(INCOMPLETE_MISSING_OPENING)
    if closing is None:
        incomplete_reasons.append(INCOMPLETE_MISSING_CLOSING)
    elif opening is not None and closing.run.pk == opening.run.pk:
        # Opening and closing must be distinct photographs; the day stays
        # incomplete instead of presenting one photograph twice.
        closing = None
        incomplete_reasons.append(INCOMPLETE_OPENING_EQUALS_CLOSING)

    anchor: AcceptedCensus | None = None
    quality_warnings: list[str] = []
    if opening is not None:
        # The anchor only exists relative to the opening photograph.
        anchor = _first_accepted(_anchor_candidates(opening.run))
        if anchor is None:
            quality_warnings.append(QUALITY_MISSING_ANCHOR)

    return DailyStatisticsWindow(
        local_date=local_date,
        opening=opening,
        closing=closing,
        anchor=anchor,
        incomplete_reasons=tuple(incomplete_reasons),
        quality_warnings=tuple(quality_warnings),
    )


def _bahia_instant(local_date: date, local_time: time) -> datetime:
    """Explicit ``America/Bahia`` instant for ``local_date`` at ``local_time``."""
    return datetime.combine(local_date, local_time, tzinfo=BAHIA_TZ)


def _succeeded_census_runs() -> QuerySet[IngestionRun]:
    """Completed successful census extraction runs of any local date."""
    return IngestionRun.objects.filter(
        intent=CENSUS_RUN_INTENT,
        status="succeeded",
        finished_at__isnull=False,
    )


def _opening_candidates(local_date: date) -> QuerySet[IngestionRun]:
    """Runs completed inside ``[D 00:00, D 03:00)``, earliest first.

    The start instant is unconstrained: an opening census may have started on
    the previous civil day.
    """
    return _succeeded_census_runs().filter(
        finished_at__gte=_bahia_instant(local_date, OPENING_WINDOW_START),
        finished_at__lt=_bahia_instant(local_date, OPENING_WINDOW_END),
    ).order_by("finished_at", "pk")


def _closing_candidates(local_date: date) -> QuerySet[IngestionRun]:
    """Runs started at/after ``D 20:00`` and completed before ``D+1 00:00``.

    Preference is the latest started photograph, so the queryset is ordered
    against the opening preference order.
    """
    return _succeeded_census_runs().filter(
        started_at__gte=_bahia_instant(local_date, CLOSING_WINDOW_START),
        finished_at__lt=_bahia_instant(local_date + _ONE_DAY, time(0, 0)),
    ).order_by("-started_at", "-finished_at", "-pk")


def _anchor_candidates(opening_run: IngestionRun) -> QuerySet[IngestionRun]:
    """Runs completed before the opening run started, latest first."""
    return _succeeded_census_runs().filter(
        finished_at__lt=opening_run.started_at,
    ).order_by("-finished_at", "-pk")


def _first_accepted(
    candidates: QuerySet[IngestionRun],
) -> AcceptedCensus | None:
    """Return the first accepted census in the candidate preference order."""
    for run in candidates:
        accepted = _accepted_census(run)
        if accepted is not None:
            return accepted
    return None


def _accepted_census(run: IngestionRun) -> AcceptedCensus | None:
    """Accept ``run`` as a census photograph, or return ``None``.

    Acceptance requires one complete snapshot photograph whose rows all belong
    to this exact execution and the exact official occupancy measurement of the
    same run. A measurement of another census is never reused.
    """
    captured_at = _unique_capture_instant(run)
    if captured_at is None:
        return None

    photograph = CensusSnapshot.objects.filter(captured_at=captured_at)
    coverage = validate_snapshot_completeness(photograph)
    if not coverage["accepted"]:
        return None
    if resolve_single_census_run(photograph) != run.pk:
        return None

    measurement = OccupancyMeasurement.objects.filter(
        census_run_id=run.pk
    ).first()
    if measurement is None:
        return None

    return AcceptedCensus(run=run, measurement=measurement)


def _unique_capture_instant(run: IngestionRun) -> datetime | None:
    """Return the single snapshot instant of ``run``, or ``None``.

    ``None`` means the run persisted no snapshot or persisted more than one
    photograph, either of which makes its provenance ambiguous.
    """
    instants = set(
        CensusSnapshot.objects.filter(ingestion_run_id=run.pk)
        .order_by()
        .values_list("captured_at", flat=True)
        .distinct()
    )
    if len(instants) != 1:
        return None
    return instants.pop()
