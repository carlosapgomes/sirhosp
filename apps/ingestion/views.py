"""Views for on-demand ingestion: create run and check status (Slice S4)."""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.ingestion.models import IngestionRun
from apps.ingestion.services import queue_ingestion_run


@login_required
def create_run(request: HttpRequest) -> HttpResponse:
    """Render form and process on-demand ingestion run creation.

    GET: renders the form.
    POST: validates and creates a queued IngestionRun, then redirects to status.
    """
    errors: list[str] = []

    if request.method == "POST":
        patient_record = request.POST.get("patient_record", "").strip()
        start_date = request.POST.get("start_date", "").strip()
        end_date = request.POST.get("end_date", "").strip()

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

        if not errors:
            run = queue_ingestion_run(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
            )
            return redirect("ingestion:run_status", run_id=run.pk)

    return render(
        request,
        "ingestion/create_run.html",
        {"errors": errors},
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

    context = {
        "run": run,
        "status_label": status_labels.get(run.status, run.status),
        "status_class": status_classes.get(run.status, "bg-secondary"),
        "patient_record": params.get("patient_record", "—"),
        "start_date": params.get("start_date", "—"),
        "end_date": params.get("end_date", "—"),
    }

    return render(request, "ingestion/run_status.html", context)
