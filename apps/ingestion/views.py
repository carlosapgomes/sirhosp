"""Views for on-demand ingestion: create run and check status (Slice S4)."""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.ingestion.models import IngestionRun
from apps.ingestion.services import (
    find_active_full_admission_sync_run,
    queue_admissions_only_run,
    queue_demographics_only_run,
    queue_ingestion_run,
)
from apps.patients.models import Admission


@login_required
def create_run(request: HttpRequest) -> HttpResponse:
    """Render form and process on-demand ingestion run creation.

    S4: This is now a contextual secondary route.
    - GET without valid patient_record+admission_id redirects to /patients/.
    - GET with valid context prefills patient_record, start_date, end_date
      from the admission boundaries.
    - POST preserves the run creation logic; validation errors re-render form
      with POST data (not GET params).
    """
    errors: list[str] = []

    if request.method == "POST":
        patient_record = request.POST.get("patient_record", "").strip()
        start_date = request.POST.get("start_date", "").strip()
        end_date = request.POST.get("end_date", "").strip()
        intent = request.POST.get("intent", "").strip()
        admission_id = request.POST.get("admission_id", "").strip()
        admission_source_key = request.POST.get(
            "admission_source_key", ""
        ).strip()

        # Validation
        if not patient_record:
            errors.append("Registro do paciente é obrigatório.")
        if not start_date:
            errors.append("Data inicial é obrigatória.")
        if not end_date:
            errors.append("Data final é obrigatória.")

        # Date format validation (YYYY-MM-DD)
        parsed_start: date | None = None
        parsed_end: date | None = None

        if start_date:
            try:
                parsed_start = date.fromisoformat(start_date)
            except ValueError:
                errors.append("Data inicial inválida. Use o formato AAAA-MM-DD.")

        if end_date:
            try:
                parsed_end = date.fromisoformat(end_date)
            except ValueError:
                errors.append("Data final inválida. Use o formato AAAA-MM-DD.")

        if parsed_start and parsed_end and parsed_end < parsed_start:
            errors.append("Data final não pode ser anterior à data inicial.")

        # S4: contextual period must stay within selected admission bounds.
        if admission_id and parsed_start and parsed_end:
            try:
                admission_obj = Admission.objects.select_related("patient").get(
                    pk=int(admission_id)
                )
            except (Admission.DoesNotExist, ValueError, TypeError):
                errors.append(
                    "Contexto da internação inválido. Reabra pela lista de internações."
                )
            else:
                if admission_obj.patient.patient_source_key != patient_record:
                    errors.append(
                        "A internação informada não pertence ao registro selecionado."
                    )
                elif (
                    admission_source_key
                    and admission_obj.source_admission_key != admission_source_key
                ):
                    errors.append(
                        "A chave da internação não confere com o contexto selecionado."
                    )
                elif admission_obj.admission_date is None:
                    errors.append(
                        "Internação sem data de entrada válida para extrair período."
                    )
                else:
                    admission_start = admission_obj.admission_date.date()
                    admission_end = (
                        admission_obj.discharge_date.date()
                        if admission_obj.discharge_date
                        else date.today()
                    )
                    if (
                        parsed_start < admission_start
                        or parsed_end > admission_end
                    ):
                        errors.append(
                            "Período fora dos limites da internação selecionada "
                            f"({admission_start.isoformat()} a {admission_end.isoformat()})."
                        )

        if not errors:
            if intent == "full_admission_sync" and admission_id:
                existing_run = find_active_full_admission_sync_run(
                    patient_record=patient_record,
                    admission_id=admission_id,
                )
                if existing_run is not None:
                    return redirect(
                        "ingestion:run_status", run_id=existing_run.pk
                    )

            run = queue_ingestion_run(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
                intent=intent,
                admission_id=admission_id,
                admission_source_key=admission_source_key,
            )
            return redirect("ingestion:run_status", run_id=run.pk)

        # POST with errors: re-render with POST data
        return render(
            request,
            "ingestion/create_run.html",
            {
                "errors": errors,
                "initial_patient_record": patient_record,
                "initial_start_date": start_date,
                "initial_end_date": end_date,
                "initial_admission_id": admission_id,
                "initial_admission_source_key": admission_source_key,
                "page_title": "Extração",
            },
        )

    # --- GET: Contextual access logic ---
    initial_patient_record = request.GET.get("patient_record", "").strip()
    admission_id_param = request.GET.get("admission_id", "").strip()

    # Without both patient_record and admission_id, redirect to /patients/
    if not initial_patient_record or not admission_id_param:
        return redirect("/patients/")

    # Validate admission exists and belongs to the patient
    initial_start_date = ""
    initial_end_date = ""

    try:
        admission_obj = Admission.objects.select_related("patient").get(
            pk=int(admission_id_param)
        )
    except (Admission.DoesNotExist, ValueError, TypeError):
        return redirect("/patients/")

    # Verify patient_source_key matches
    if admission_obj.patient.patient_source_key != initial_patient_record:
        return redirect("/patients/")

    # Prefill dates from admission boundaries
    if admission_obj.admission_date:
        initial_start_date = admission_obj.admission_date.strftime("%Y-%m-%d")
    if admission_obj.discharge_date:
        initial_end_date = admission_obj.discharge_date.strftime("%Y-%m-%d")
    else:
        initial_end_date = date.today().isoformat()

    initial_admission_source_key = admission_obj.source_admission_key

    return render(
        request,
        "ingestion/create_run.html",
        {
            "errors": errors,
            "initial_patient_record": initial_patient_record,
            "initial_start_date": initial_start_date,
            "initial_end_date": initial_end_date,
            "initial_admission_id": admission_id_param,
            "initial_admission_source_key": initial_admission_source_key,
            "page_title": "Extração",
        },
    )


@login_required
def create_admissions_only(request: HttpRequest) -> HttpResponse:
    """Render form and process admissions-only run creation.

    GET: renders the form with optional patient_record prefill.
    POST: validates and creates a queued IngestionRun with
         intent='admissions_only', then redirects to status.
    """
    errors: list[str] = []

    if request.method == "POST":
        patient_record = request.POST.get("patient_record", "").strip()

        if not patient_record:
            errors.append("Registro do paciente é obrigatório.")

        if not errors:
            run = queue_admissions_only_run(patient_record=patient_record)
            return redirect("ingestion:run_status", run_id=run.pk)

    initial_patient_record = request.GET.get("patient_record", "")

    return render(
        request,
        "ingestion/create_admissions_only.html",
        {
            "errors": errors,
            "initial_patient_record": initial_patient_record,
            "page_title": "Sincronizar",
        },
    )


@login_required
def run_status(request: HttpRequest, run_id: int) -> HttpResponse:
    """Display operational status for an ingestion run.

    Shows state, counters, timestamps and error messages.
    """
    try:
        run = IngestionRun.objects.get(pk=run_id)
    except IngestionRun.DoesNotExist as err:
        raise Http404 from err

    params = run.parameters_json or {}
    intent = params.get("intent", "") or run.intent

    # Build status label and CSS class
    status_labels = {
        "queued": "Na fila",
        "running": "Em execução",
        "succeeded": "Concluído com sucesso",
        "failed": "Falhou",
    }
    status_classes = {
        "queued": "bg-info",
        "running": "bg-warning",
        "succeeded": "bg-success",
        "failed": "bg-danger",
    }

    # Determine run type label
    if intent == "demographics_only":
        run_type_label = "Dados demográficos"
    elif intent == "admissions_only":
        run_type_label = "Sincronização de internações"
    elif intent == "full_admission_sync":
        run_type_label = "Sincronização completa de internação"
    else:
        run_type_label = "Extração de evoluções"

    stage_metrics = run.stage_metrics.all()

    # Determine if no admissions were found
    no_admissions = (
        intent == "admissions_only"
        and run.status == "succeeded"
        and run.admissions_seen == 0
    )

    # Demographics fields count
    demographics_fields = params.get("demographics_fields_extracted", 0)

    admission_id = params.get("admission_id", "")
    admission_source_key = params.get("admission_source_key", "")

    # Resolve admission for human-readable display
    admission_display: dict[str, str] = {
        "name": "",
        "bed": "",
        "period": "",
    }
    if admission_id:
        try:
            admission_obj = (
                Admission.objects.select_related("patient")
                .only(
                    "admission_date",
                    "discharge_date",
                    "bed",
                    "patient__name",
                )
                .get(pk=int(admission_id))
            )
            admission_display["name"] = admission_obj.patient.name
            admission_display["bed"] = admission_obj.bed or ""
            if admission_obj.admission_date:
                adt_str = admission_obj.admission_date.strftime("%d/%m/%Y")
                if admission_obj.discharge_date:
                    ddt_str = admission_obj.discharge_date.strftime(
                        "%d/%m/%Y"
                    )
                    admission_display["period"] = (
                        f"{adt_str} → {ddt_str}"
                    )
                else:
                    admission_display["period"] = (
                        f"{adt_str} → atual"
                    )
        except (Admission.DoesNotExist, ValueError, TypeError):
            pass

    # S3: Build patient admissions URL for successful admissions-only sync
    patient_admissions_url = ""
    if (
        intent == "admissions_only"
        and run.status == "succeeded"
        and run.admissions_seen > 0
    ):
        patient_record = params.get("patient_record", "")
        if patient_record:
            from apps.patients.models import Patient

            patient = (
                Patient.objects.filter(
                    patient_source_key=patient_record
                )
                .order_by("pk")
                .first()
            )
            if patient:
                from django.urls import reverse

                patient_admissions_url = reverse(
                    "patients:admission_list", args=[patient.pk]
                )

    context = {
        "run": run,
        "status_label": status_labels.get(run.status, run.status),
        "status_class": status_classes.get(run.status, "bg-secondary"),
        "page_title": f"Status #{run.pk}",
        "patient_record": params.get("patient_record", "—"),
        "start_date": params.get("start_date", "—"),
        "end_date": params.get("end_date", "—"),
        "intent": intent,
        "run_type_label": run_type_label,
        "admission_id": admission_id,
        "admission_source_key": admission_source_key,
        "admission_display": admission_display,
        "no_admissions": no_admissions,
        "patient_admissions_url": patient_admissions_url,
        "stage_metrics": stage_metrics,
        "demographics_fields": demographics_fields,
    }

    return render(request, "ingestion/run_status.html", context)


@login_required
def run_status_fragment(request: HttpRequest, run_id: int) -> HttpResponse:
    """Return HTML fragment with stage progress for HTMX polling.

    Returns only the progress section (_run_progress.html partial)
    so HTMX can swap it without reloading the full page.
    """
    try:
        run = IngestionRun.objects.get(pk=run_id)
    except IngestionRun.DoesNotExist as err:
        raise Http404 from err

    stage_metrics = run.stage_metrics.all()

    return render(request, "ingestion/_run_progress.html", {
        "run": run,
        "stage_metrics": stage_metrics,
    })


@login_required
def create_demographics_only(request: HttpRequest) -> HttpResponse:
    """Enqueue a demographics-only run for a patient.

    GET: reads patient_record from query param, creates run,
         redirects to status.
    POST: reads patient_record from form body, creates run,
          redirects to status.
    """
    patient_record = (
        request.POST.get("patient_record", "").strip()
        or request.GET.get("patient_record", "").strip()
    )

    if not patient_record:
        return redirect("patients:patient_list")

    run = queue_demographics_only_run(patient_record=patient_record)
    return redirect("ingestion:run_status", run_id=run.pk)
