"""Summary views — HTTP surface for on-demand progressive summaries.

APS-S2: create_summary_run (POST enqueue) + run_status (GET status page).
APS-S7: run_progress (HTMX fragment for chunk-level polling).
APS-S8: summary_read (Markdown render + copy button + disclaimer).
STP-S5: prompt_list, prompt_create, prompt_edit, prompt_delete (CRUD).
STP-S7: summary_config (GET/POST config page for phase2 LLM + prompt).
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
# Summary config page (STP-S7)
# ---------------------------------------------------------------------------


def _config_form_with_error(
    request: HttpRequest,
    admission,
    phase2_options,
    own_prompts,
    public_others,
    field: str,
    message: str,
) -> HttpResponse:
    """Re-render the config form with a field-level error message."""
    context = {
        "page_title": "Configurar Resumo",
        "admission": admission,
        "mode": request.POST.get("mode", "generate"),
        "phase2_options": phase2_options,
        "own_prompts": own_prompts,
        "public_others": public_others,
        "errors": {field: message},
    }
    return render(request, "summaries/summary_config.html", context)


@login_required
def summary_config(
    request: HttpRequest,
    admission_id: int,
) -> HttpResponse:
    """GET/POST configuration page for phase-2 LLM and prompt.

    GET: renders form with enabled phase-2 options, saved prompts, and
         a custom-prompt textarea with optional save checkbox.
    POST: validates inputs, optionally persists a prompt template,
          enqueues a SummaryRun, and redirects to run status.
    """
    from apps.patients.models import Admission

    admission = get_object_or_404(Admission, pk=admission_id)

    # Load phase-2 LLM options
    from apps.summaries.llm_config import load_phase2_options

    phase2_options = load_phase2_options()

    # Load available saved prompts for this user
    own_prompts = UserPromptTemplate.objects.filter(
        owner=request.user  # type: ignore[misc]
    )
    public_others = UserPromptTemplate.objects.filter(
        is_public=True,
    ).exclude(owner=request.user).select_related("owner")  # type: ignore[misc]

    if request.method == "GET":
        mode = request.GET.get("mode", "generate").strip()
        if mode not in services.VALID_MODES:
            mode = "generate"

        context = {
            "page_title": "Configurar Resumo",
            "admission": admission,
            "mode": mode,
            "phase2_options": phase2_options,
            "own_prompts": own_prompts,
            "public_others": public_others,
            "errors": {},
        }
        return render(
            request,
            "summaries/summary_config.html",
            context,
        )

    # ---- POST ----
    mode = request.POST.get("mode", "").strip()
    if not mode or mode not in services.VALID_MODES:
        return _config_form_with_error(
            request,
            admission,
            phase2_options,
            own_prompts,
            public_others,
            "mode",
            f"Modo inválido: '{mode}'. "
            f"Deve ser um de: {', '.join(sorted(services.VALID_MODES))}.",
        )

    # ---- Validate phase2_option_index (strict) ----
    phase2_option_index: int | None = None
    chosen_opt = None
    if phase2_options:
        raw_index = request.POST.get("phase2_option_index", "").strip()
        if not raw_index:
            return _config_form_with_error(
                request,
                admission,
                phase2_options,
                own_prompts,
                public_others,
                "phase2_option_index",
                "Selecione um LLM para a fase 2.",
            )
        try:
            idx = int(raw_index)
        except ValueError:
            return _config_form_with_error(
                request,
                admission,
                phase2_options,
                own_prompts,
                public_others,
                "phase2_option_index",
                f"Opção inválida: '{raw_index}'.",
            )
        if idx < 1 or idx > len(phase2_options):
            return _config_form_with_error(
                request,
                admission,
                phase2_options,
                own_prompts,
                public_others,
                "phase2_option_index",
                f"Opção {idx} não está disponível. "
                f"Escolha entre 1 e {len(phase2_options)}.",
            )
        phase2_option_index = idx
        chosen_opt = phase2_options[idx - 1]
        phase2_provider = chosen_opt.provider
        phase2_model = chosen_opt.model
        phase2_base_url = chosen_opt.base_url
    else:
        # No phase2 options configured — fall back to empty strings
        phase2_provider = ""
        phase2_model = ""
        phase2_base_url = ""

    prompt_mode = request.POST.get("prompt_mode", "").strip()
    if prompt_mode not in ("padrao", "custom"):
        return _config_form_with_error(
            request,
            admission,
            phase2_options,
            own_prompts,
            public_others,
            "prompt_mode",
            "Selecione o modo do prompt (padrão ou customizado).",
        )

    # Resolve custom prompt text if applicable
    prompt_text: str | None = None
    if prompt_mode == "custom":
        saved_prompt_id = request.POST.get("saved_prompt_id", "").strip()
        if saved_prompt_id:
            # Strict: must exist and be accessible
            try:
                saved_pk = int(saved_prompt_id)
            except ValueError:
                return _config_form_with_error(
                    request,
                    admission,
                    phase2_options,
                    own_prompts,
                    public_others,
                    "saved_prompt_id",
                    f"ID de prompt inválido: '{saved_prompt_id}'.",
                )
            try:
                saved = UserPromptTemplate.objects.get(pk=saved_pk)
            except UserPromptTemplate.DoesNotExist:
                return _config_form_with_error(
                    request,
                    admission,
                    phase2_options,
                    own_prompts,
                    public_others,
                    "saved_prompt_id",
                    f"Prompt #{saved_pk} não encontrado.",
                )
            if (
                saved.owner_id != request.user.pk
                and not saved.is_public
            ):
                return _config_form_with_error(
                    request,
                    admission,
                    phase2_options,
                    own_prompts,
                    public_others,
                    "saved_prompt_id",
                    "Você não tem acesso a este prompt.",
                )
            prompt_text = saved.content
        else:
            prompt_text = (
                request.POST.get("custom_prompt_text", "").strip()
                or None
            )

    # Handle salvar_prompt
    salvar_prompt = request.POST.get("salvar_prompt") == "on"
    if salvar_prompt:
        prompt_title = request.POST.get("prompt_title", "").strip()
        if not prompt_title:
            return _config_form_with_error(
                request,
                admission,
                phase2_options,
                own_prompts,
                public_others,
                "prompt_title",
                "Título é obrigatório para salvar o prompt.",
            )
        prompt_is_public = request.POST.get("prompt_is_public") == "on"
        prompt_text_to_save = prompt_text or ""
        UserPromptTemplate.objects.create(
            owner=request.user,  # type: ignore[misc]
            title=prompt_title,
            content=prompt_text_to_save,
            is_public=prompt_is_public,
        )

    # Build phase2 config for the worker
    # NOTE: NEVER persist API keys — the worker resolves them at runtime
    # from environment config via load_phase2_options().
    phase2_config = {
        "prompt_mode": prompt_mode,
        "phase2_option_index": phase2_option_index,
        "phase2_provider": phase2_provider,
        "phase2_model": phase2_model,
        "phase2_base_url": phase2_base_url,
        "prompt_text": prompt_text,
    }

    # Enqueue SummaryRun with phase2 config
    run = services.queue_summary_run(
        admission=admission,
        mode=mode,
        requested_by=request.user,  # type: ignore[arg-type]
        phase2_config_json=phase2_config,
    )

    return redirect(reverse("summaries:run_status", args=[run.pk]))


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
