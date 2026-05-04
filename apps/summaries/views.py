"""Summary views — HTTP surface for on-demand progressive summaries.

APS-S2: create_summary_run (POST enqueue) + run_status (GET status page).
APS-S7: run_progress (HTMX fragment for chunk-level polling).
APS-S8: summary_read (Markdown render + copy button + disclaimer).
STP-S5: prompt_list, prompt_create, prompt_edit, prompt_delete (CRUD).
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
    UserPromptTemplate,
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


# ---------------------------------------------------------------------------
# Prompt library CRUD (STP-S5)
# ---------------------------------------------------------------------------


@login_required
def prompt_list(request: HttpRequest) -> HttpResponse:
    """List own prompts and public prompts from other users."""
    own = UserPromptTemplate.objects.filter(owner=request.user)  # type: ignore[misc]
    public_others = UserPromptTemplate.objects.filter(
        is_public=True,
    ).exclude(owner=request.user).select_related("owner")  # type: ignore[misc]

    context = {
        "own_prompts": own,
        "public_others": public_others,
        "page_title": "Biblioteca de Prompts",
    }
    return render(request, "summaries/prompt_list.html", context)


@login_required
def prompt_create(request: HttpRequest) -> HttpResponse:
    """Create a new prompt template."""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content", "").strip()
        is_public = request.POST.get("is_public") == "on"

        errors = {}
        if not title:
            errors["title"] = "Título é obrigatório."
        if not content:
            errors["content"] = "Conteúdo é obrigatório."

        if errors:
            return render(request, "summaries/prompt_form.html", {
                "page_title": "Novo Prompt",
                "is_create": True,
                "errors": errors,
                "title": title,
                "content": content,
                "is_public": is_public,
            }, status=200)

        UserPromptTemplate.objects.create(
            owner=request.user,  # type: ignore[misc]
            title=title,
            content=content,
            is_public=is_public,
        )
        return redirect("summaries:prompt_list")

    return render(request, "summaries/prompt_form.html", {
        "page_title": "Novo Prompt",
        "is_create": True,
        "errors": {},
        "title": "",
        "content": "",
        "is_public": False,
    })


@login_required
def prompt_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit own prompt template only."""
    prompt = get_object_or_404(UserPromptTemplate, pk=pk)

    if prompt.owner_id != request.user.pk:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Você não pode editar este prompt.")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content", "").strip()
        is_public = request.POST.get("is_public") == "on"

        errors = {}
        if not title:
            errors["title"] = "Título é obrigatório."
        if not content:
            errors["content"] = "Conteúdo é obrigatório."

        if errors:
            return render(request, "summaries/prompt_form.html", {
                "page_title": f"Editar: {prompt.title}",
                "is_create": False,
                "prompt": prompt,
                "errors": errors,
                "title": title,
                "content": content,
                "is_public": is_public,
            }, status=200)

        prompt.title = title
        prompt.content = content
        prompt.is_public = is_public
        prompt.save()
        return redirect("summaries:prompt_list")

    return render(request, "summaries/prompt_form.html", {
        "page_title": f"Editar: {prompt.title}",
        "is_create": False,
        "prompt": prompt,
        "errors": {},
        "title": prompt.title,
        "content": prompt.content,
        "is_public": prompt.is_public,
    })


@login_required
def prompt_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete own prompt template only (POST only)."""
    prompt = get_object_or_404(UserPromptTemplate, pk=pk)

    if prompt.owner_id != request.user.pk:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Você não pode apagar este prompt.")

    if request.method == "POST":
        prompt.delete()
        return redirect("summaries:prompt_list")

    return render(request, "summaries/prompt_confirm_delete.html", {
        "page_title": f"Apagar: {prompt.title}",
        "prompt": prompt,
    })
