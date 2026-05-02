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

    patients_qs = services.search_patients_with_coverage(query)
    paginator = Paginator(patients_qs, 20)
    page = paginator.get_page(page_number)

    context = {
        "page_obj": page,
        "query": query or "",
        "patients": page.object_list,
        "page_title": "Pacientes",
    }
    return render(request, "patients/patient_list.html", context)


@login_required
def admission_list_view(
    request: HttpRequest,
    patient_id: int,
) -> HttpResponse:
    """Patient detail page with admission selector and timeline.

    Unified view: banner with patient identity, dropdown to select
    admission period, and timeline rendered for the selected admission.
    Falls back to first admission if none selected.
    """
    try:
        patient = services.get_patient_or_404(patient_id)
    except Patient.DoesNotExist:
        return render(request, "patients/404.html", status=404)

    admissions = services.list_admissions_for_patient(patient_id)

    # Compute age from date_of_birth
    idade: str | None = None
    from datetime import date as date_mod

    if patient.date_of_birth:
        today = date_mod.today()
        age_years = (
            today.year
            - patient.date_of_birth.year
            - (
                (today.month, today.day)
                < (patient.date_of_birth.month, patient.date_of_birth.day)
            )
        )
        idade = str(age_years)

    # Determine which admission to show (default: first)
    admission_id_param = request.GET.get("admission_id", "").strip()
    selected_admission = None

    if admission_id_param and admissions:
        for adm in admissions:
            if str(adm.pk) == admission_id_param:
                selected_admission = adm
                break

    if selected_admission is None and admissions:
        selected_admission = admissions[0]

    # Load events for selected admission
    events = []
    profession_types = []
    profession_filter = request.GET.get("profession_type", "").strip() or None

    if selected_admission:
        events = list(
            services.list_events_for_admission(
                selected_admission.pk, profession_type=profession_filter
            )
        )
        profession_types = services.get_profession_types_for_admission(
            selected_admission.pk
        )

    # Determine ward/bed for banner
    ward = selected_admission.ward if selected_admission else None
    bed = selected_admission.bed if selected_admission else None

    # --- APS-S6: Summary CTA context ---
    summary_context: dict = {}
    sync_context: dict = {}
    if selected_admission:
        from apps.ingestion.services import get_admission_sync_context
        from apps.summaries.services import get_admission_summary_context

        summary_context = get_admission_summary_context(selected_admission)
        sync_context = get_admission_sync_context(selected_admission)

    context = {
        "patient": patient,
        "idade": idade,
        "admissions": admissions,
        "selected_admission": selected_admission,
        "ward": ward,
        "bed": bed,
        "events": events,
        "profession_types": profession_types,
        "active_filter": profession_filter or "",
        "page_title": patient.name,
        "today": date_mod.today().isoformat(),
        "summary": summary_context,
        "sync": sync_context,
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
        "page_title": f"Timeline — {admission.patient.name}",
    }
    return render(request, "patients/timeline.html", context)
