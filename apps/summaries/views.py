"""Summary views — HTTP surface for on-demand progressive summaries.

APS-S2: create_summary_run (POST enqueue) + run_status (GET status page).
APS-S7: run_progress (HTMX fragment for chunk-level polling).
APS-S8: summary_read (Markdown render + copy button + disclaimer).
"""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe

from apps.summaries import services
from apps.summaries.models import (
    AdmissionSummaryState,
    SummaryRun,
)


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
    # request.user is guaranteed authenticated by @login_required
    run = services.queue_summary_run(
        admission=admission,
        mode=mode,
        requested_by=request.user,  # type: ignore[arg-type]
    )

    return redirect(reverse("summaries:run_status", args=[run.pk]))


@login_required
def run_status(
    request: HttpRequest,
    run_id: int,
) -> HttpResponse:
    """Display chunk-level status of a summary run with HTMX polling.

    Non-terminal runs (queued/running) use HTMX polling to refresh
    chunk progress.  Terminal runs (succeeded/partial/failed) display
    final state without polling.
    """
    run = get_object_or_404(
        SummaryRun.objects.select_related(
            "admission__patient",
            "requested_by",
        ).prefetch_related("chunks"),
        pk=run_id,
    )

    terminal = run.status in {
        SummaryRun.Status.SUCCEEDED,
        SummaryRun.Status.PARTIAL,
        SummaryRun.Status.FAILED,
    }

    context = {
        "run": run,
        "chunks": run.chunks.all(),
        "terminal": terminal,
        "page_title": f"Resumo — Status #{run.pk}",
    }
    return render(request, "summaries/run_status.html", context)


@login_required
def run_progress(
    request: HttpRequest,
    run_id: int,
) -> HttpResponse:
    """HTMX fragment endpoint — returns chunk-level progress partial.

    Used for polling by the status page for non-terminal runs.
    Returns 404 for nonexistent runs.
    """
    run = get_object_or_404(
        SummaryRun.objects.prefetch_related("chunks"),
        pk=run_id,
    )

    terminal = run.status in {
        SummaryRun.Status.SUCCEEDED,
        SummaryRun.Status.PARTIAL,
        SummaryRun.Status.FAILED,
    }

    context = {
        "run": run,
        "chunks": run.chunks.all(),
        "terminal": terminal,
    }
    return render(
        request,
        "summaries/_summary_run_progress.html",
        context,
    )


@login_required
def summary_read(
    request: HttpRequest,
    run_id: int,
) -> HttpResponse:
    """Render the final Markdown summary for reading.

    Loads the AdmissionSummaryState for the admission linked to the
    run, converts narrative_markdown to HTML, and renders the read
    page with AI disclaimer and client-side copy button.
    """
    run = get_object_or_404(
        SummaryRun.objects.select_related(
            "admission__patient",
            "requested_by",
        ),
        pk=run_id,
    )

    try:
        state = AdmissionSummaryState.objects.get(
            admission=run.admission
        )
    except AdmissionSummaryState.DoesNotExist:
        state = None

    narrative_md = state.narrative_markdown if state else ""

    # Convert Markdown to HTML
    import markdown as md_lib  # type: ignore[import-untyped]

    html_content = md_lib.markdown(
        narrative_md or "_(Resumo ainda não gerado)_",
        extensions=["extra", "sane_lists", "smarty"],
    )

    incomplete = (
        state is not None
        and state.status == AdmissionSummaryState.Status.INCOMPLETE
    )

    context = {
        "run": run,
        "state": state,
        "html_content": mark_safe(html_content),
        "raw_markdown": narrative_md,
        "raw_markdown_json": json.dumps(narrative_md),
        "incomplete": incomplete,
        "page_title": f"Resumo #{run.pk} — {run.admission.patient.name}",
    }
    return render(request, "summaries/summary_read.html", context)
