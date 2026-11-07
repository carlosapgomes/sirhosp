"""Admin for the pending-item catalog (PEND-S1/S1).

Only the catalog is administered: categories and types. Pending items
and revisions have no admin CRUD. Slug immutability, the contract of a
type already used by an item or a revision, and the fixed ``Outro``
contract are enforced by the model, so every admin write surfaces them
as a form error instead of a silent change.
"""

from __future__ import annotations

from django.contrib import admin

from apps.pending_items.models import (
    OUTRO_SLUG,
    PendingItemCategory,
    PendingItemType,
)


@admin.register(PendingItemCategory)
class PendingItemCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at", "updated_at"]
    search_fields = ["name", "slug"]


@admin.register(PendingItemType)
class PendingItemTypeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "category",
        "profile",
        "has_rnm_complements",
        "requires_description",
    ]
    list_select_related = ["category"]
    list_filter = ["category", "profile"]
    search_fields = ["name", "slug", "category__name"]
    fields = [
        "name",
        "slug",
        "category",
        "profile",
        "has_rnm_complements",
        "requires_description",
    ]

    def has_delete_permission(self, request, obj=None) -> bool:
        if obj is not None and obj.slug == OUTRO_SLUG:
            return False
        return super().has_delete_permission(request, obj)
