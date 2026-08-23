"""Bed status views (Slice S6)."""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import render

from apps.census.flow_service import compute_hospital_flow, list_sectors
from apps.census.models import CensusSnapshot
from apps.census.occupancy import (
    ALGORITHM_VERSION_V4,
    build_official_group_rows,
    build_units_presentation,
    resolve_exact_measurement,
)
from apps.patients.models import Patient


@login_required
def hospital_flow_view(request):
    """Display hospital flow (stock vs. admissions/discharges/deaths) as a table."""
    raw_window = request.GET.get("window", "90")
    valid_windows = {30, 90, 180}
    try:
        window = int(raw_window)
    except (ValueError, TypeError):
        window = 90
    if window not in valid_windows:
        window = 90

    today = date.today()
    start = today - timedelta(days=window - 1)

    sector = request.GET.get("sector", "") or None
    if sector is not None:
        sector = sector.strip()
        if not sector:
            sector = None

    flow_series = compute_hospital_flow(start, today, sector=sector)

    # Chart.js serializable data
    chart_data = {
        "labels": [row["date"].isoformat() for row in flow_series],
        "admissions": [row["admissions"] for row in flow_series],
        "discharges_deaths": [
            row["discharges"] + row["deaths"] for row in flow_series
        ],
        "adc": [row["adc"] for row in flow_series],
    }

    sectors = list_sectors(start, today)

    context = {
        "page_title": "Fluxo Hospitalar",
        "active_menu": "fluxo",
        "flow_series": flow_series,
        "chart_data": chart_data,
        "window": window,
        "window_options": [30, 90, 180],
        "selected_sector": sector or "",
        "sectors": sectors,
    }

    # ---- QC residual panel (admin only) ----
    if request.user.is_staff:
        residual_series = []
        residual_pcts: list[float] = []
        for row in flow_series:
            residual = row.get("residual")
            adc = row.get("adc")
            if residual is not None and adc is not None and adc != 0:
                residual_pct = abs(residual) / adc * 100.0
                residual_pcts.append(residual_pct)
            else:
                residual_pct = None
            residual_series.append({
                "date": row["date"],
                "residual": residual,
                "residual_pct": residual_pct,
            })

        if residual_pcts:
            max_pct = max(residual_pcts)
            if max_pct > 5.0:
                residual_quality = "alert"
            elif max_pct > 3.0:
                residual_quality = "warn"
            else:
                residual_quality = "ok"
        else:
            residual_quality = "ok"

        context["residual_series"] = residual_series
        context["residual_quality"] = residual_quality

    return render(request, "census/hospital_flow.html", context)


@login_required
def bed_status_view(request):
    """Display bed occupancy status from the most recent census snapshot.

    Two aggregate realities are always presented side by side: the official
    capacity and occupancy section (persisted exact-run measurement only)
    and the physical snapshot registered in the system of origin. Exactly one
    detailed list ``Setores e posições`` follows, built from connected
    components of the group<->code graph of the exact catalog; every physical
    position appears once and v4 quality cases stay visible to every
    authenticated user. No official value is recalculated here and no older
    measurement is ever reused as current.
    """
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    if latest_captured is None:
        return render(request, "census/bed_status.html", {
            "page_title": "Leitos",
            "captured_at": None,
        })

    snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)
    bed_details = snapshots.order_by("leito")

    # Global raw totals across all sectors (kept for the legacy totals
    # context contract; the template renders the normalized physical view).
    global_totals_raw = (
        snapshots.values("bed_status")
        .annotate(count=Count("id"))
    )
    totals = {
        "occupied": 0,
        "empty": 0,
        "maintenance": 0,
        "reserved": 0,
        "isolation": 0,
        "total": snapshots.count(),
    }
    for row in global_totals_raw:
        status = row["bed_status"]
        if status in totals:
            totals[status] = row["count"]

    # Official occupancy statistics: the latest census is selected exactly as
    # before, and statistics are only presented when every row of that set
    # identifies one non-null ingestion run and that exact run owns one
    # persisted measurement. Older measurements, current-catalog calculations
    # and raw percentage inference are never used here.
    measurement = resolve_exact_measurement(snapshots)

    # Look up internal Patient IDs for direct linking to admission_list.
    prontuarios = [b.prontuario for b in bed_details if b.prontuario]
    patient_map: dict[str, int] = {}
    if prontuarios:
        patient_map = {
            p.patient_source_key: p.pk
            for p in Patient.objects.filter(patient_source_key__in=prontuarios)
        }

    presentation = build_units_presentation(
        measurement=measurement,
        snapshots=bed_details,
        patient_map=patient_map,
    )

    context = {
        "page_title": "Leitos",
        "captured_at": latest_captured,
        "totals": totals,
        "measurement": measurement,
        "physical": presentation.physical,
        "units": presentation.units,
        "measured_groups": [],
    }
    if (
        measurement is not None
        and measurement.algorithm_version != ALGORITHM_VERSION_V4
    ):
        # v1-v3 keep the historical official group rows in the context;
        # the template renders only the unified unit list and never the raw
        # ``beds`` of the official cards.
        context["measured_groups"] = build_official_group_rows(
            measurement=measurement,
            snapshots=bed_details,
            patient_map=patient_map,
        )
    return render(request, "census/bed_status.html", context)
