"""Contextual pending-item surfaces (PEND-S1, D7 subset).

List, create, edit, finalize and read-only history nested under the
selected admission. Every response carries ``Cache-Control: private,
no-store``. Writes require POST+CSRF, effective group membership and a
uniquely identified current open admission; failures re-render with an
explicit status instead of raising through the cache decorator.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.patients.models import Admission
from apps.patients.reconciliation import admission_has_date_only_closure
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
    PendingItemForm,
)
from apps.pending_items.models import (
    STATUS_ACTIVE,
    PendingItem,
    PendingItemRevision,
)
from apps.pending_items.services import (
    CONFLICT_MESSAGE,
    InvalidStatusTransitionError,
    VersionConflictError,
    create_pending_item,
    finalize_pending_item,
    update_pending_item,
)


def private_no_store(view_func):
    """Set Cache-Control private/no-store on every wrapped response."""

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        response = view_func(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    return _wrapped


def _items_for(admission: Admission):
    return (
        PendingItem.objects.filter(admission=admission)
        .select_related("item_type")
        .order_by("status", "created_at", "pk")
    )


@login_required
@private_no_store
def admission_pending_items(
    request: HttpRequest, admission_id: int
) -> HttpResponse:
    """List one episode plus the create form when writing is allowed."""
    admission = get_object_or_404(
        Admission.objects.select_related("patient"), pk=admission_id
    )
    eligibility = check_write_eligibility(admission)
    member = policy.can_write_pending_items(request.user)
    can_write = member and eligibility.eligible
    block_message = (
        None if eligibility.eligible else reason_message(eligibility.reason)
    )
    # Date-only death closures (D2) render the exit date alone — the
    # D 00:00 carrier hour is never displayed.
    discharge_date_only = admission_has_date_only_closure(admission)

    if request.method == "POST":
        if not member:
            return render(
                request,
                "pending_items/admission_items.html",
                {
                    "admission": admission,
                    "patient": admission.patient,
                    "items": _items_for(admission),
                    "form": PendingItemForm(),
                    "can_write": False,
                    "block_message": block_message,
                    "error": policy.WRITE_DENIED_MESSAGE,
                    "page_title": "Pendências",
                    "discharge_date_only": discharge_date_only,
                },
                status=403,
            )
        try:
            require_write_eligibility(admission)
        except IneligibleAdmissionError as exc:
            return render(
                request,
                "pending_items/admission_items.html",
                {
                    "admission": admission,
                    "patient": admission.patient,
                    "items": _items_for(admission),
                    "form": PendingItemForm(),
                    "can_write": False,
                    "block_message": str(exc),
                    "error": str(exc),
                    "page_title": "Pendências",
                    "discharge_date_only": discharge_date_only,
                },
                status=403,
            )
        form = PendingItemForm(request.POST)
        if form.is_valid():
            try:
                create_pending_item(
                    admission=admission,
                    item_type=form.cleaned_data["item_type"],
                    description=form.cleaned_data["description"],
                    author=request.user,  # type: ignore[arg-type]
                )
            except (ValidationError, IneligibleAdmissionError) as exc:
                return render(
                    request,
                    "pending_items/admission_items.html",
                    {
                        "admission": admission,
                        "patient": admission.patient,
                        "items": _items_for(admission),
                        "form": form,
                        "can_write": True,
                        "block_message": None,
                        "error": _first_message(exc),
                        "page_title": "Pendências",
                        "discharge_date_only": discharge_date_only,
                    },
                )
            except PermissionDenied as exc:
                return render(
                    request,
                    "pending_items/admission_items.html",
                    {
                        "admission": admission,
                        "patient": admission.patient,
                        "items": _items_for(admission),
                        "form": form,
                        "can_write": False,
                        "block_message": block_message,
                        "error": str(exc),
                        "page_title": "Pendências",
                        "discharge_date_only": discharge_date_only,
                    },
                    status=403,
                )
            return redirect(
                "pending_items:admission_items", admission_id=admission.pk
            )
        return render(
            request,
            "pending_items/admission_items.html",
            {
                "admission": admission,
                "patient": admission.patient,
                "items": _items_for(admission),
                "form": form,
                "can_write": True,
                "block_message": None,
                "error": None,
                "page_title": "Pendências",
                "discharge_date_only": discharge_date_only,
            },
        )

    return render(
        request,
        "pending_items/admission_items.html",
        {
            "admission": admission,
            "patient": admission.patient,
            "items": _items_for(admission),
            "form": PendingItemForm(),
            "can_write": can_write,
            "block_message": block_message,
            "error": None,
            "page_title": "Pendências",
            "discharge_date_only": discharge_date_only,
        },
    )


@login_required
@private_no_store
def pending_item_edit(
    request: HttpRequest, admission_id: int, item_id: int
) -> HttpResponse:
    """Edit an active item guarded by the observed version token."""
    admission = get_object_or_404(
        Admission.objects.select_related("patient"), pk=admission_id
    )
    item = get_object_or_404(PendingItem, pk=item_id, admission=admission)
    eligibility = check_write_eligibility(admission)
    member = policy.can_write_pending_items(request.user)

    if request.method == "POST":
        if not member:
            return _edit_response(
                request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
                status=403,
            )
        try:
            require_write_eligibility(admission)
        except IneligibleAdmissionError as exc:
            return _edit_response(
                request, admission, item, None, str(exc), status=403
            )
        form = PendingItemEditForm(request.POST)
        if not form.is_valid():
            return _edit_response(
                request, admission, item, form, None, status=200
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
                status=409,
            )
        except InvalidStatusTransitionError as exc:
            return _edit_response(
                request, admission, item, None, str(exc), status=400
            )
        except (ValidationError, IneligibleAdmissionError) as exc:
            return _edit_response(
                request, admission, item, form, _first_message(exc),
                status=200,
            )
        except PermissionDenied as exc:
            return _edit_response(
                request, admission, item, None, str(exc), status=403
            )
        return redirect(
            "pending_items:admission_items", admission_id=admission.pk
        )

    if not member:
        return _edit_response(
            request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
            status=403,
        )
    if not eligibility.eligible:
        return _edit_response(
            request, admission, item, None,
            reason_message(eligibility.reason), status=403,
        )
    if item.status != STATUS_ACTIVE:
        return _edit_response(
            request, admission, item, None,
            "Pendências finalizadas não podem ser editadas.", status=200,
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
        status=200,
    )


def _edit_response(
    request: HttpRequest,
    admission: Admission,
    item: PendingItem,
    form,
    error: str | None,
    status: int,
) -> HttpResponse:
    return render(
        request,
        "pending_items/item_edit.html",
        {
            "admission": admission,
            "patient": admission.patient,
            "item": item,
            "form": form,
            "error": error,
            "page_title": "Editar pendência",
        },
        status=status,
    )


@login_required
@private_no_store
def pending_item_finalize(
    request: HttpRequest, admission_id: int, item_id: int
) -> HttpResponse:
    """Finalize an active item with an optional note."""
    admission = get_object_or_404(
        Admission.objects.select_related("patient"), pk=admission_id
    )
    item = get_object_or_404(PendingItem, pk=item_id, admission=admission)
    eligibility = check_write_eligibility(admission)
    member = policy.can_write_pending_items(request.user)

    if request.method == "POST":
        if not member:
            return _finalize_response(
                request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
                status=403,
            )
        try:
            require_write_eligibility(admission)
        except IneligibleAdmissionError as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), status=403
            )
        form = PendingItemFinalizeForm(request.POST)
        if not form.is_valid():
            return _finalize_response(
                request, admission, item, form, None, status=200
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
                status=409,
            )
        except InvalidStatusTransitionError as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), status=400
            )
        except (ValidationError, IneligibleAdmissionError) as exc:
            return _finalize_response(
                request, admission, item, form, _first_message(exc),
                status=200,
            )
        except PermissionDenied as exc:
            return _finalize_response(
                request, admission, item, None, str(exc), status=403
            )
        return redirect(
            "pending_items:admission_items", admission_id=admission.pk
        )

    if not member:
        return _finalize_response(
            request, admission, item, None, policy.WRITE_DENIED_MESSAGE,
            status=403,
        )
    if not eligibility.eligible:
        return _finalize_response(
            request, admission, item, None,
            reason_message(eligibility.reason), status=403,
        )
    if item.status != STATUS_ACTIVE:
        return _finalize_response(
            request, admission, item, None,
            "Pendências finalizadas não podem ser alteradas.", status=200,
        )
    return _finalize_response(
        request,
        admission,
        item,
        PendingItemFinalizeForm(
            initial={"expected_version": item.version}
        ),
        None,
        status=200,
    )


def _finalize_response(
    request: HttpRequest,
    admission: Admission,
    item: PendingItem,
    form,
    error: str | None,
    status: int,
) -> HttpResponse:
    return render(
        request,
        "pending_items/item_finalize.html",
        {
            "admission": admission,
            "patient": admission.patient,
            "item": item,
            "form": form,
            "error": error,
            "page_title": "Finalizar pendência",
        },
        status=status,
    )


@login_required
@private_no_store
def pending_item_history(
    request: HttpRequest, admission_id: int, item_id: int
) -> HttpResponse:
    """Read-only version history of one episode item."""
    admission = get_object_or_404(
        Admission.objects.select_related("patient"), pk=admission_id
    )
    item = get_object_or_404(PendingItem, pk=item_id, admission=admission)
    revisions = list(
        PendingItemRevision.objects.filter(item=item).order_by("version")
    )
    return render(
        request,
        "pending_items/item_history.html",
        {
            "admission": admission,
            "patient": admission.patient,
            "item": item,
            "revisions": revisions,
            "page_title": "Histórico da pendência",
        },
    )


def _first_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        messages = getattr(exc, "messages", None) or [str(exc)]
        return str(messages[0])
    return str(exc)
