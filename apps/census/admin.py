from __future__ import annotations

from django.contrib import admin

from apps.census.models import CensusSnapshot


@admin.register(CensusSnapshot)
class CensusSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "captured_at",
        "setor",
        "leito",
        "prontuario",
        "nome",
        "especialidade",
        "bed_status",
    ]
    list_filter = [
        "bed_status",
        "captured_at",
        "setor",
    ]
    search_fields = [
        "prontuario",
        "nome",
        "setor",
        "leito",
    ]
    date_hierarchy = "captured_at"
    ordering = ["-captured_at", "setor", "leito"]
