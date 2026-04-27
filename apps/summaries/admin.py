"""Admin registration for summary domain models."""

from django.contrib import admin

from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryRun,
    SummaryRunChunk,
)


@admin.register(AdmissionSummaryState)
class AdmissionSummaryStateAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "status",
        "coverage_start",
        "coverage_end",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("admission__patient__name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AdmissionSummaryVersion)
class AdmissionSummaryVersionAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "chunk_index",
        "coverage_start",
        "coverage_end",
        "llm_provider",
        "llm_model",
        "created_at",
    )
    list_filter = ("llm_provider", "llm_model")
    search_fields = ("admission__patient__name",)
    readonly_fields = ("created_at",)


@admin.register(SummaryRun)
class SummaryRunAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "mode",
        "status",
        "current_chunk_index",
        "total_chunks",
        "created_at",
    )
    list_filter = ("status", "mode")
    search_fields = ("admission__patient__name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(SummaryRunChunk)
class SummaryRunChunkAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "chunk_index",
        "status",
        "attempt_count",
        "window_start",
        "window_end",
        "input_event_count",
    )
    list_filter = ("status",)
    readonly_fields = ("created_at", "updated_at")
