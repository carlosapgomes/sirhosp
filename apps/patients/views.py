"""Patient navigation views (Slice S4)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.patients import services
from apps.patients.models import Admission, Patient


@login_required
def patient_list_view(request: HttpRequest) -> HttpResponse:
    """Hub page: list patients with optional search filter.

    Supports query param `q` for filtering by name or patient_source_key.
    Paginates results for manageable page size.
    """
    query = request.GET.get("q", "").strip() or None
    page_number = request.GET.get("page", 1)

    patients_qs = services.search_patients(query)
    paginator = Paginator(patients_qs, 20)
    page = paginator.get_page(page_number)

    context = {
        "page_obj": page,
        "query": query or "",
        "patients": page.object_list,
    }
    return render(request, "patients/patient_list.html", context)


@login_required
def admission_list_view(
    request: HttpRequest,
    patient_id: int,
) -> HttpResponse:
    """List all admissions for a patient.

    Shows a mobile-friendly card list with admission dates, ward,
    and event count. Links to timeline view for each admission.
    """
    try:
        patient = services.get_patient_or_404(patient_id)
    except Patient.DoesNotExist:
        return render(request, "patients/404.html", status=404)

    admissions = services.list_admissions_for_patient(patient_id)

    context = {
        "patient": patient,
        "admissions": admissions,
    }
    return render(request, "patients/admission_list.html", context)


@login_required
def timeline_view(
    request: HttpRequest,
    admission_id: int,
) -> HttpResponse:
    """Show timeline of clinical events for an admission.

    Supports filtering by profession_type query parameter.
    Displays events as mobile-friendly cards ordered by most recent.
    """
    try:
        admission = services.get_admission_or_404(admission_id)
    except Admission.DoesNotExist:
        return render(request, "patients/404.html", status=404)

    profession_filter = request.GET.get("profession_type", "").strip() or None
    events = services.list_events_for_admission(
        admission_id, profession_type=profession_filter
    )
    profession_types = services.get_profession_types_for_admission(admission_id)

    context = {
        "admission": admission,
        "patient": admission.patient,
        "events": events,
        "profession_types": profession_types,
        "active_filter": profession_filter or "",
    }
    return render(request, "patients/timeline.html", context)
