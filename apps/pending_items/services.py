"""Pending-item writers: FSM, locks, version tokens, atomic revisions.

Every write runs in a transaction with lock order Admission before
PendingItem, revalidates policy/eligibility/status under the lock, and
persists the state change plus its revision atomically. Human writers
always record ``is_system=False``; the caller can never impersonate the
system author because no author-kind input exists.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.patients.models import Admission
from apps.pending_items import policy
from apps.pending_items.eligibility import (
    IneligibleAdmissionError,
    require_write_eligibility,
)
from apps.pending_items.models import (
    ACTION_CREATED,
    ACTION_FINALIZED,
    ACTION_UPDATED,
    FINAL_STATUSES,
    STATUS_ACTIVE,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)

CONFLICT_MESSAGE = (
    "Esta pendência foi alterada por outra pessoa. "
    "Consulte a versão atual e tente novamente."
)

FINALIZED_MESSAGE = "Pendências finalizadas não podem ser alteradas."


class PendingItemsError(Exception):
    """Base class of the pending-items domain errors."""


class VersionConflictError(PendingItemsError):
    """The submitted version token no longer matches the current version."""


class InvalidStatusTransitionError(PendingItemsError):
    """The requested FSM transition is not allowed from the current state."""


def _require_type(item_type: PendingItemType) -> PendingItemType:
    try:
        return PendingItemType.objects.get(pk=item_type.pk)
    except PendingItemType.DoesNotExist:
        raise ValidationError("Tipo inválido.") from None


def _require_text(description: str | None) -> str:
    text = (description or "").strip()
    if not text:
        raise ValidationError({"description": "Descrição é obrigatória."})
    return text


def _locked_admission(admission_id: int) -> Admission:
    try:
        return Admission.all_objects.select_for_update().get(pk=admission_id)
    except Admission.DoesNotExist:
        raise IneligibleAdmissionError(
            "Internação não encontrada."
        ) from None


def create_pending_item(
    *,
    admission: Admission,
    item_type: PendingItemType,
    description: str,
    author: User,
) -> PendingItem:
    """Create an active item plus its v1 revision, atomically."""
    policy.require_can_write(author)
    text = _require_text(description)
    fresh_type = _require_type(item_type)
    label = author.get_username()
    with transaction.atomic():
        locked = _locked_admission(admission.pk)
        require_write_eligibility(locked)
        item = PendingItem.objects.create(
            admission=locked,
            item_type=fresh_type,
            description=text,
            status=STATUS_ACTIVE,
            version=1,
            created_by=author,
            created_by_name=label,
            updated_by=author,
            updated_by_name=label,
            is_system_updated=False,
        )
        PendingItemRevision.objects.create(
            item=item,
            version=1,
            action=ACTION_CREATED,
            item_type=fresh_type,
            type_name=fresh_type.name,
            description=text,
            status=STATUS_ACTIVE,
            note="",
            author=author,
            author_name=label,
            is_system=False,
        )
    return item


def update_pending_item(
    *,
    item: PendingItem,
    item_type: PendingItemType,
    description: str,
    author: User,
    expected_version: int,
) -> tuple[PendingItem, bool]:
    """Edit an active item; no effective change writes no new version."""
    policy.require_can_write(author)
    text = _require_text(description)
    fresh_type = _require_type(item_type)
    label = author.get_username()
    with transaction.atomic():
        locked_admission = _locked_admission(item.admission_id)
        require_write_eligibility(locked_admission)
        locked = PendingItem.objects.select_for_update().get(pk=item.pk)
        if locked.admission_id != locked_admission.pk:
            raise IneligibleAdmissionError(
                "A pendência não pertence a esta internação."
            )
        if locked.status != STATUS_ACTIVE:
            raise InvalidStatusTransitionError(FINALIZED_MESSAGE)
        if locked.version != expected_version:
            raise VersionConflictError(CONFLICT_MESSAGE)
        if locked.item_type_id == fresh_type.pk and locked.description == text:
            return locked, False
        locked.item_type = fresh_type
        locked.description = text
        locked.version += 1
        locked.updated_by = author
        locked.updated_by_name = label
        locked.is_system_updated = False
        locked.save(
            update_fields=[
                "item_type",
                "description",
                "version",
                "updated_by",
                "updated_by_name",
                "is_system_updated",
                "updated_at",
            ]
        )
        PendingItemRevision.objects.create(
            item=locked,
            version=locked.version,
            action=ACTION_UPDATED,
            item_type=fresh_type,
            type_name=fresh_type.name,
            description=text,
            status=STATUS_ACTIVE,
            note="",
            author=author,
            author_name=label,
            is_system=False,
        )
    return locked, True


def finalize_pending_item(
    *,
    item: PendingItem,
    target_status: str,
    note: str | None,
    author: User,
    expected_version: int,
) -> PendingItem:
    """Move an active item to a final status with an optional note."""
    policy.require_can_write(author)
    if target_status not in FINAL_STATUSES:
        raise InvalidStatusTransitionError(
            "Destino de finalização inválido."
        )
    clean_note = (note or "").strip()
    label = author.get_username()
    with transaction.atomic():
        locked_admission = _locked_admission(item.admission_id)
        require_write_eligibility(locked_admission)
        locked = PendingItem.objects.select_for_update().get(pk=item.pk)
        if locked.admission_id != locked_admission.pk:
            raise IneligibleAdmissionError(
                "A pendência não pertence a esta internação."
            )
        if locked.status != STATUS_ACTIVE:
            raise InvalidStatusTransitionError(FINALIZED_MESSAGE)
        if locked.version != expected_version:
            raise VersionConflictError(CONFLICT_MESSAGE)
        locked.status = target_status
        locked.finalized_at = timezone.now()
        locked.version += 1
        locked.updated_by = author
        locked.updated_by_name = label
        locked.is_system_updated = False
        locked.save(
            update_fields=[
                "status",
                "finalized_at",
                "version",
                "updated_by",
                "updated_by_name",
                "is_system_updated",
                "updated_at",
            ]
        )
        PendingItemRevision.objects.create(
            item=locked,
            version=locked.version,
            action=ACTION_FINALIZED,
            item_type=locked.item_type,
            type_name=locked.item_type.name,
            description=locked.description,
            status=target_status,
            note=clean_note,
            author=author,
            author_name=label,
            is_system=False,
        )
    return locked
