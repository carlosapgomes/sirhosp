"""Aggregate pending-items panel: hospital list, indicators, quick edit.

PEND-S3 (D7/D8): two responsive views over the shared conservative
cut, combinable filters applied before grouping, per-episode first
unit, filter-independent hospital indicators, on-demand history and
modal quick edit reusing the contextual service/form. Every response
carries ``Cache-Control: private, no-store``; GETs never mutate.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.patients.models import Admission
from apps.pending_items import policy
from apps.pending_items.eligibility import (
    IneligibleAdmissionError,
    check_write_eligibility,
    reason_message,
    require_write_eligibility,
)
from apps.pending_items.forms import (
    PendingItemEditForm,
    PendingItemFinalizeForm,
)
from apps.pending_items.models import (
    STATUS_ACTIVE,
    PendingItem,
    PendingItemRevision,
)
from apps.pending_items.queries import (
    AGGREGATE_PER_PAGE,
    FIRST_UNIT_UNKNOWN,
    VIEW_ITEMS,
    VIEW_PATIENTS,
    CurrentCut,
    PatientGroup,
    aggregate_options,
    apply_aggregate_filters,
    apply_time_bounds,
    base_current_items,
    group_by_patient,
    hospital_indicators,
    open_duration,
    parse_aggregate_filters,
    resolve_current_cut,
    resolve_first_units,
    resolve_specialty,
    sort_aggregate_items,
    sort_patient_groups,
    specialty_labels,
)
from apps.pending_items.services import (
    CONFLICT_MESSAGE,
    InvalidStatusTransitionError,
    VersionConflictError,
    finalize_pending_item,
    update_pending_item,
)
from apps.pending_items.views import private_no_store


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request", "") == "true"


def _safe_next(value: str | None) -> str:
    """Allow only same-origin aggregate return URLs."""
    if (
        value
        and value.startswith("/pendencias/")
        and "://" not in value
        and "\\" not in value
        and "\n" not in value
        and "\r" not in value
    ):
        return value
    return reverse("pending_items:aggregate")


def _first_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        found = getattr(exc, "messages", None) or [str(exc)]
        return str(found[0])
    return str(exc)


def _item_row(
    item: PendingItem,
    cut: CurrentCut,
    first_units: dict[int, str],
    code_to_name: dict[str, str],
    name_to_code: dict[str, str],
    member: bool,
    now: datetime,
) -> dict:
    occ = cut.occupations[item.admission_id]
    sigla, nome = resolve_specialty(
        occ.especialidade, code_to_name, name_to_code
    )
    return {
        "item": item,
        "admission_id": occ.admission_id,
        "patient_name": occ.patient_name,
        "prontuario": occ.prontuario,
        "setor": occ.setor,
        "leito": occ.leito,
        "esp_sigla": sigla,
        "esp_nome": nome,
        "first_unit": first_units.get(occ.admission_id, FIRST_UNIT_UNKNOWN),
        "open_days": open_duration(item, now).total_seconds() / 86400,
        "can_edit": member and item.status == STATUS_ACTIVE,
        "admission_url": reverse(
            "pending_items:admission_items", args=[occ.admission_id]
        ),
        "history_url": reverse(
            "pending_items:aggregate_history", args=[item.pk]
        ),
        "edit_url": reverse("pending_items:aggregate_edit", args=[item.pk]),
        "finalize_url": reverse(
            "pending_items:aggregate_finalize", args=[item.pk]
        ),
    }


def _group_card(
    group: PatientGroup,
    cut: CurrentCut,
    first_units: dict[int, str],
    code_to_name: dict[str, str],
    name_to_code: dict[str, str],
    member: bool,
    now: datetime,
) -> dict:
    occ = group.occupation
    sigla, nome = resolve_specialty(
        occ.especialidade, code_to_name, name_to_code
    )
    rows = [
        _item_row(
            item, cut, first_units, code_to_name, name_to_code, member, now
        )
        for item in group.items
    ]
    return {
        "admission_id": occ.admission_id,
        "patient_name": occ.patient_name,
        "prontuario": occ.prontuario,
        "setor": occ.setor,
        "leito": occ.leito,
        "esp_sigla": sigla,
        "esp_nome": nome,
        "first_unit": first_units.get(occ.admission_id, FIRST_UNIT_UNKNOWN),
        "entry": group.items[0].admission.admission_date,
        "admission_url": reverse(
            "pending_items:admission_items", args=[occ.admission_id]
        ),
        "rows": rows,
    }


@login_required
@private_no_store
@require_GET
def aggregate(request: HttpRequest) -> HttpResponse:
    """Hospital-wide panel: indicators plus two views over one cut."""
    now = timezone.now()
    cut = resolve_current_cut()
    filters, filter_error = parse_aggregate_filters(request.GET)
    if filter_error is None:
        items = apply_time_bounds(
            list(
                apply_aggregate_filters(
                    base_current_items(cut), cut, filters
                )
            ),
            filters,
            now,
        )
    else:
        items = []
    indicators = hospital_indicators(cut, now)
    code_to_name, name_to_code = specialty_labels()
    options = aggregate_options(cut, code_to_name)
    member = policy.can_write_pending_items(request.user)
    params = request.GET.copy()
    if "page" in params:
        del params["page"]
    base_qs = params.urlencode()
    if base_qs:
        pagination_base = f"{request.path}?{base_qs}&"
    else:
        pagination_base = f"{request.path}?"
    patients_params = params.copy()
    patients_params["view"] = VIEW_PATIENTS
    items_params = params.copy()
    items_params["view"] = VIEW_ITEMS
    context: dict = {
        "page_title": "Pendências",
        "indicators": indicators,
        "options": options,
        "filter_error": filter_error,
        "can_write": member,
        "current_path": request.get_full_path(),
        "pagination_base": pagination_base,
        "view_urls": {
            VIEW_PATIENTS: f"{request.path}?{patients_params.urlencode()}",
            VIEW_ITEMS: f"{request.path}?{items_params.urlencode()}",
        },
        "has_census": cut.captured_at is not None,
        "captured_at": cut.captured_at,
    }
    if filters.view == VIEW_ITEMS:
        ordered = sort_aggregate_items(items, cut, filters, now)
        page_obj = Paginator(ordered, AGGREGATE_PER_PAGE).get_page(
            request.GET.get("page")
        )
        first_units = resolve_first_units(
            [item.admission_id for item in page_obj]
        )
        context["view"] = VIEW_ITEMS
        context["page_obj"] = page_obj
        context["rows"] = [
            _item_row(
                item, cut, first_units, code_to_name, name_to_code,
                member, now,
            )
            for item in page_obj
        ]
    else:
        groups = sort_patient_groups(
            group_by_patient(items, cut), filters, now
        )
        groups_page = Paginator(groups, AGGREGATE_PER_PAGE).get_page(
            request.GET.get("page")
        )
        first_units = resolve_first_units(
            [group.admission_id for group in groups_page]
        )
        context["view"] = VIEW_PATIENTS
        context["page_obj"] = groups_page
        context["groups"] = [
            _group_card(
                group, cut, first_units, code_to_name, name_to_code,
                member, now,
            )
            for group in groups_page
        ]
    return render(request, "pending_items/aggregate.html", context)


@login_required
@private_no_store
@require_GET
def aggregate_history(request: HttpRequest, item_id: int) -> HttpResponse:
    """Read-only version history; HTMX receives the collapsible fragment."""
    item = get_object_or_404(
        PendingItem.objects.select_related(
            "item_type", "admission__patient"
        ),
        pk=item_id,
    )
    revisions = list(
        PendingItemRevision.objects.filter(item=item)
        .select_related("item_type")
        .order_by("version")
    )
    context = {
        "admission": item.admission,
        "patient": item.admission.patient,
        "item": item,
        "revisions": revisions,
        "page_title": "Histórico da pendência",
    }
    if _is_htmx(request):
        return render(
            request, "pending_items/_aggregate_history_table.html", context
        )
    return render(request, "pending_items/aggregate_history.html", context)


def _edit_response(
    request: HttpRequest,
    admission: Admission,
    item: PendingItem,
    form,
    error: str | None,
    next_url: str,
    modal: bool,
    attempted: str | None,
    status: int,
) -> HttpResponse:
    context = {
        "admission": admission,
        "patient": admission.patient,
        "item": item,
        "form": form,
        "error": error,
        "attempted": attempted or "",
        "show_attempted": bool(attempted),
        "next_url": next_url,
        "modal": modal,
        "post_url": reverse("pending_items:aggregate_edit", args=[item.pk]),
        "page_title": "Editar pendência",
    }
    if modal:
        template = "pending_items/_aggregate_edit_form.html"
    else:
        template = "pending_items/aggregate_edit.html"
    return render(request, template, context, status=status)


@login_required
@private_no_store
def aggregate_edit(request: HttpRequest, item_id: int) -> HttpResponse:
    """Quick-edit one item reusing the contextual service and form.

    HTMX requests receive the modal fragment; plain requests receive the
    full page. Writes happen only on POST; version conflicts, exits and
    lost membership re-render with an explicit message and the typed
    text preserved, never a false success.
    """
    item = get_object_or_404(
        PendingItem.objects.select_related(
            "item_type", "admission__patient"
        ),
        pk=item_id,
    )
    admission = item.admission
    modal = _is_htmx(request)

    if request.method == "POST":
        next_url = _safe_next(request.POST.get("next"))
        if not policy.can_write_pending_items(request.user):
            return _edit_response(
                request, admission, item, None,
                policy.WRITE_DENIED_MESSAGE, next_url, modal,
                attempted=request.POST.get("description") or "", status=403,
            )
        try:
            require_write_eligibility(admission)
        except IneligibleAdmissionError as exc:
            return _edit_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=request.POST.get("description") or "", status=403,
            )
        form = PendingItemEditForm(request.POST)
        if not form.is_valid():
            return _edit_response(
                request, admission, item, form, None, next_url, modal,
                attempted=None, status=200,
            )
        try:
            update_pending_item(
                item=item,
                item_type=form.cleaned_data["item_type"],
                description=form.cleaned_data["description"],
                author=request.user,  # type: ignore[arg-type]
                expected_version=form.cleaned_data["expected_version"],
            )
        except VersionConflictError:
            item.refresh_from_db()
            return _edit_response(
                request,
                admission,
                item,
                PendingItemEditForm(
                    initial={
                        "item_type": item.item_type_id,
                        "description": item.description,
                        "expected_version": item.version,
                    }
                ),
                CONFLICT_MESSAGE,
                next_url,
                modal,
                attempted=form.cleaned_data["description"],
                status=409,
            )
        except InvalidStatusTransitionError as exc:
            return _edit_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=form.cleaned_data["description"], status=400,
            )
        except (ValidationError, IneligibleAdmissionError) as exc:
            return _edit_response(
                request, admission, item, form, _first_message(exc),
                next_url, modal, attempted=None, status=200,
            )
        except PermissionDenied as exc:
            return _edit_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=form.cleaned_data["description"], status=403,
            )
        messages.success(request, "Pendência atualizada com sucesso.")
        if modal:
            return HttpResponse("", headers={"HX-Redirect": next_url})
        return redirect(next_url)

    next_url = _safe_next(request.GET.get("next"))
    if not policy.can_write_pending_items(request.user):
        return _edit_response(
            request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
            next_url, modal, attempted=None, status=403,
        )
    eligibility = check_write_eligibility(admission)
    if not eligibility.eligible:
        return _edit_response(
            request, admission, item, None,
            reason_message(eligibility.reason), next_url, modal,
            attempted=None, status=403,
        )
    if item.status != STATUS_ACTIVE:
        return _edit_response(
            request, admission, item, None,
            "Pendências finalizadas não podem ser editadas.",
            next_url, modal, attempted=None, status=200,
        )
    return _edit_response(
        request,
        admission,
        item,
        PendingItemEditForm(
            initial={
                "item_type": item.item_type_id,
                "description": item.description,
                "expected_version": item.version,
            }
        ),
        None,
        next_url,
        modal,
        attempted=None,
        status=200,
    )


def _finalize_response(
    request: HttpRequest,
    admission: Admission,
    item: PendingItem,
    form,
    error: str | None,
    next_url: str,
    modal: bool,
    attempted: str | None,
    status: int,
) -> HttpResponse:
    context = {
        "admission": admission,
        "patient": admission.patient,
        "item": item,
        "form": form,
        "error": error,
        "attempted": attempted or "",
        "show_attempted": bool(attempted),
        "next_url": next_url,
        "modal": modal,
        "post_url": reverse(
            "pending_items:aggregate_finalize", args=[item.pk]
        ),
        "page_title": "Finalizar pendência",
    }
    if modal:
        template = "pending_items/_aggregate_finalize_form.html"
    else:
        template = "pending_items/aggregate_finalize.html"
    return render(request, template, context, status=status)


@login_required
@private_no_store
def aggregate_finalize(request: HttpRequest, item_id: int) -> HttpResponse:
    """Quick-finalize one item reusing the contextual service and form."""
    item = get_object_or_404(
        PendingItem.objects.select_related(
            "item_type", "admission__patient"
        ),
        pk=item_id,
    )
    admission = item.admission
    modal = _is_htmx(request)

    if request.method == "POST":
        next_url = _safe_next(request.POST.get("next"))
        if not policy.can_write_pending_items(request.user):
            return _finalize_response(
                request, admission, item, None,
                policy.WRITE_DENIED_MESSAGE, next_url, modal,
                attempted=request.POST.get("note") or "", status=403,
            )
        try:
            require_write_eligibility(admission)
        except IneligibleAdmissionError as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=request.POST.get("note") or "", status=403,
            )
        form = PendingItemFinalizeForm(request.POST)
        if not form.is_valid():
            return _finalize_response(
                request, admission, item, form, None, next_url, modal,
                attempted=None, status=200,
            )
        try:
            finalize_pending_item(
                item=item,
                target_status=form.cleaned_data["target_status"],
                note=form.cleaned_data["note"],
                author=request.user,  # type: ignore[arg-type]
                expected_version=form.cleaned_data["expected_version"],
            )
        except VersionConflictError:
            item.refresh_from_db()
            return _finalize_response(
                request,
                admission,
                item,
                PendingItemFinalizeForm(
                    initial={"expected_version": item.version}
                ),
                CONFLICT_MESSAGE,
                next_url,
                modal,
                attempted=form.cleaned_data["note"],
                status=409,
            )
        except InvalidStatusTransitionError as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=form.cleaned_data["note"], status=400,
            )
        except (ValidationError, IneligibleAdmissionError) as exc:
            return _finalize_response(
                request, admission, item, form, _first_message(exc),
                next_url, modal, attempted=None, status=200,
            )
        except PermissionDenied as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), next_url, modal,
                attempted=form.cleaned_data["note"], status=403,
            )
        messages.success(request, "Pendência finalizada com sucesso.")
        if modal:
            return HttpResponse("", headers={"HX-Redirect": next_url})
        return redirect(next_url)

    next_url = _safe_next(request.GET.get("next"))
    if not policy.can_write_pending_items(request.user):
        return _finalize_response(
            request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
            next_url, modal, attempted=None, status=403,
        )
    eligibility = check_write_eligibility(admission)
    if not eligibility.eligible:
        return _finalize_response(
            request, admission, item, None,
            reason_message(eligibility.reason), next_url, modal,
            attempted=None, status=403,
        )
    if item.status != STATUS_ACTIVE:
        return _finalize_response(
            request, admission, item, None,
            "Pendências finalizadas não podem ser alteradas.",
            next_url, modal, attempted=None, status=200,
        )
    return _finalize_response(
        request,
        admission,
        item,
        PendingItemFinalizeForm(
            initial={"expected_version": item.version}
        ),
        None,
        next_url,
        modal,
        attempted=None,
        status=200,
    )
