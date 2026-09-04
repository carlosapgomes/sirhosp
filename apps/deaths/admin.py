"""Death evidence admin (RPSA-S6, read-only).

Admin is staff-only; identity columns (prontuário, nome) are authorized
here. Rows carry reconciliation linkage and status — evidence state is
owned by the canonical reconciliation services, so the admin offers no
add, change or delete actions.
"""

from __future__ import annotations

from django.contrib import admin

from apps.deaths.models import DeathRecord


@admin.register(DeathRecord)
class DeathRecordAdmin(admin.ModelAdmin):
    """Read-only exposure of death evidence with linkage/status."""

    list_display = [
        "pk",
        "prontuario",
        "nome",
        "date",
        "obito_em",
        "admission",
        "reconciliation_status",
        "reconciled_at",
    ]
    list_filter = ["reconciliation_status"]
    search_fields = ["prontuario", "nome"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
