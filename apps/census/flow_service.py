"""Domain service for hospital flow aggregation.

Provides ``compute_hospital_flow`` — a pure aggregation function that
confronts daily inpatient stock (ADC from census snapshots) with flow
(admissions vs. discharges + deaths), calculating net flow, delta stock,
and residual (quality-control indicator).

See ``design.md`` D3 for the conservative identity rationale.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate

from apps.admissions.models import DailyAdmissionCount
from apps.census.models import BedStatus, CensusSnapshot
from apps.deaths.models import DailyDeathCount
from apps.discharges.models import DailyDischargeCount


def list_sectors(start: date, end: date) -> list[str]:
    """Return distinct, ordered sector names present in CensusSnapshot for the period.

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        Sorted list of distinct sector names.
    """
    if end < start:
        raise ValueError("end must be >= start")

    return list(
        CensusSnapshot.objects.filter(
            captured_at__date__gte=start,
            captured_at__date__lte=end,
        )
        .values_list("setor", flat=True)
        .distinct()
        .order_by("setor")
    )


def compute_hospital_flow(
    start: date,
    end: date,
    sector: str | None = None,
) -> list[dict]:
    """Aggregate daily stock (ADC) and flow (admissions/discharges/deaths).

    Args:
        start: Start date (inclusive).
        end: End date (inclusive). Must be >= start.
        sector: If set, filters **stock** (CensusSnapshot.setor) to this
            sector. Flow remains hospital-total (dedicated sources have
            no sector field).

    Returns:
        List of dicts ordered by date, one per day in ``[start, end]``.
        Each dict has keys:
            date (date), adc (float|None), n_snapshots (int),
            admissions (int), discharges (int), deaths (int),
            net_flow (int), delta_adc (float|None), residual (float|None).

    Raises:
        ValueError: If ``end < start``.
    """
    if end < start:
        raise ValueError("end must be >= start")

    # ------------------------------------------------------------------
    # 1. Build the complete date range (fill dict with defaults)
    # ------------------------------------------------------------------
    result: OrderedDict[date, dict] = OrderedDict()
    cursor = start
    while cursor <= end:
        result[cursor] = {
            "date": cursor,
            "adc": None,
            "n_snapshots": 0,
            "admissions": 0,
            "discharges": 0,
            "deaths": 0,
            "net_flow": 0,
            "delta_adc": None,
            "residual": None,
        }
        cursor += timedelta(days=1)

    # ------------------------------------------------------------------
    # 2. ADC — average occupied beds per snapshot, per day
    # ------------------------------------------------------------------
    snap_qs = CensusSnapshot.objects.filter(
        captured_at__date__gte=start,
        captured_at__date__lte=end,
        bed_status=BedStatus.OCCUPIED,
    )
    if sector:
        snap_qs = snap_qs.filter(setor=sector)

    # Per snapshot-run (distinct captured_at): count of occupied beds
    per_snapshot = (
        snap_qs.annotate(snap_date=TruncDate("captured_at"))
        .values("snap_date", "captured_at")
        .annotate(occupied_count=Count("id"))
        .order_by("snap_date", "captured_at")
    )

    # Aggregate across snapshots within each day
    day_total_occupied: dict[date, int] = {}
    day_snapshot_count: dict[date, int] = {}
    for row in per_snapshot:
        d: date = row["snap_date"]
        day_total_occupied[d] = day_total_occupied.get(d, 0) + row["occupied_count"]
        day_snapshot_count[d] = day_snapshot_count.get(d, 0) + 1

    for d, total_occ in day_total_occupied.items():
        n_snaps = day_snapshot_count[d]
        if d in result:
            result[d]["adc"] = total_occ / n_snaps
            result[d]["n_snapshots"] = n_snaps

    # ------------------------------------------------------------------
    # 3. Flow — dedicated extraction sources
    # ------------------------------------------------------------------
    # Note: field is named ``count`` (SQL reserved word); using
    # ``.values("date", "count")`` avoids ORM collision with Count().
    for adm_row in DailyAdmissionCount.objects.filter(
        date__gte=start, date__lte=end
    ).values("date", "count"):
        d = adm_row["date"]
        if d in result:
            result[d]["admissions"] = adm_row["count"]

    for dis_row in DailyDischargeCount.objects.filter(
        date__gte=start, date__lte=end
    ).values("date", "count"):
        d = dis_row["date"]
        if d in result:
            result[d]["discharges"] = dis_row["count"]

    for dea_row in DailyDeathCount.objects.filter(
        date__gte=start, date__lte=end
    ).values("date", "count"):
        d = dea_row["date"]
        if d in result:
            result[d]["deaths"] = dea_row["count"]

    # ------------------------------------------------------------------
    # 4. Derived fields: net_flow, delta_adc, residual
    # ------------------------------------------------------------------
    days = list(result.values())
    prev_adc: float | None = None

    for row in days:
        row["net_flow"] = row["admissions"] - row["discharges"] - row["deaths"]

        adc = row["adc"]
        if prev_adc is not None and adc is not None:
            row["delta_adc"] = adc - prev_adc
            row["residual"] = row["delta_adc"] - row["net_flow"]
        # otherwise delta_adc / residual remain None

        prev_adc = adc

    return days
