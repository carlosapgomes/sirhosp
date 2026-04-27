"""Summary views — HTTP surface for on-demand progressive summaries.

APS-S2: create_summary_run (POST enqueue) + run_status (GET status page).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.summaries import services
from apps.summaries.models import SummaryRun


@login_required
def create_summary_run(
    request: HttpRequest,
    admission_id: int,
) -> HttpResponse:
    """Enqueue a summary run for an admission (POST only).

    Validates:
      - admission exists (404 if not)
      - mode is required and must be one of generate|update|regenerate
    On success: creates SummaryRun(status=queued) and redirects to run status.
    """
    # Validate admission exists
    from apps.patients.models import Admission

    admission = get_object_or_404(Admission, pk=admission_id)

    # Only POST is supported
    if request.method != "POST":
        return HttpResponseBadRequest("Method not allowed")

    # Validate mode
    mode = request.POST.get("mode", "").strip()
    if not mode or mode not in services.VALID_MODES:
        return HttpResponseBadRequest(
            f"Invalid mode: '{mode}'. "
            f"Must be one of: {', '.join(sorted(services.VALID_MODES))}."
        )

    # Create the run
    run = services.queue_summary_run(
        admission=admission,
        mode=mode,
        requested_by=request.user,
    )

    return redirect(reverse("summaries:run_status", args=[run.pk]))


@login_required
def run_status(
    request: HttpRequest,
    run_id: int,
) -> HttpResponse:
    """Display basic status of a summary run."""
    run = get_object_or_404(
        SummaryRun.objects.select_related(
            "admission__patient",
            "requested_by",
        ),
        pk=run_id,
    )

    context = {
        "run": run,
        "page_title": f"Resumo — Status #{run.pk}",
    }
    return render(request, "summaries/run_status.html", context)
