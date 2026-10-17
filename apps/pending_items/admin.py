"""Admin for the pending-item type catalog (PEND-S1).

Only the catalog is administered. Pending items and revisions have no
admin CRUD at all; ``Outro`` is additionally protected against rename
and delete even when unreferenced.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from apps.pending_items.models import (
    OUTRO_PROTECTED_MESSAGE,
    OUTRO_SLUG,
    PendingItemType,
)


class PendingItemTypeAdminForm(forms.ModelForm):
    """Block renaming the protected ``Outro`` entry."""

    class Meta:
        model = PendingItemType
        fields = ["name", "slug"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is not None:
            try:
                old = PendingItemType.objects.get(pk=self.instance.pk)
            except PendingItemType.DoesNotExist:
                return cleaned
            if old.slug == OUTRO_SLUG and (
                cleaned.get("name") != old.name
                or cleaned.get("slug") != old.slug
            ):
                raise ValidationError(OUTRO_PROTECTED_MESSAGE)
        return cleaned


@admin.register(PendingItemType)
class PendingItemTypeAdmin(admin.ModelAdmin):
    form = PendingItemTypeAdminForm
    list_display = ["name", "slug", "created_at", "updated_at"]
    search_fields = ["name", "slug"]

    def has_delete_permission(self, request, obj=None) -> bool:
        if obj is not None and obj.slug == OUTRO_SLUG:
            return False
        return super().has_delete_permission(request, obj)
