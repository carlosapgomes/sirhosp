"""Bed status views (Slice S6)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import render

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Patient


@login_required
def bed_status_view(request):
    """Display bed occupancy status from the most recent census snapshot."""
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    if latest_captured is None:
        return render(request, "census/bed_status.html", {
            "sectors": [],
            "captured_at": None,
        })

    snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    # Global totals across all sectors
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

    # Aggregate by sector and status
    sectors_raw = (
        snapshots.values("setor", "bed_status")
        .annotate(count=Count("id"))
        .order_by("setor", "bed_status")
    )

    # Build structured data for template
    sectors: dict[str, dict] = {}
    for row in sectors_raw:
        setor = row["setor"]
        status = row["bed_status"]
        count = row["count"]

        if setor not in sectors:
            sectors[setor] = {
                "name": setor,
                "occupied": 0,
                "empty": 0,
                "maintenance": 0,
                "reserved": 0,
                "isolation": 0,
                "total": 0,
                "beds": [],
            }

        sectors[setor][status] = count
        sectors[setor]["total"] += count

    # Add individual bed details
    bed_details = snapshots.order_by("leito")

    # Look up internal Patient IDs for direct linking to admission_list
    prontuarios = [b.prontuario for b in bed_details if b.prontuario]
    patient_map: dict[str, int] = {}
    if prontuarios:
        patient_map = {
            p.patient_source_key: p.pk
            for p in Patient.objects.filter(patient_source_key__in=prontuarios)
        }

    for bed in bed_details:
        if bed.setor in sectors:
            sectors[bed.setor]["beds"].append({
                "leito": bed.leito,
                "status": bed.bed_status,
                "status_label": BedStatus(bed.bed_status).label,
                "nome": bed.nome
                if bed.bed_status == BedStatus.OCCUPIED
                else "",
                "prontuario": bed.prontuario,
                "patient_id": patient_map.get(bed.prontuario),
            })

    # Sort sectors by name
    sorted_sectors = sorted(sectors.values(), key=lambda s: s["name"])

    return render(request, "census/bed_status.html", {
        "sectors": sorted_sectors,
        "captured_at": latest_captured,
        "totals": totals,
    })
