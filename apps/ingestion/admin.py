"""Ingestion admin configuration (Slice S5).

Registers IngestionRun and IngestionRunStageMetric in Django Admin
with operational columns, diagnostic filters, search fields, and
read-only stage metric inlines.
"""

from __future__ import annotations

from django.contrib import admin

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


class IngestionRunStageMetricInline(admin.TabularInline):
    """Read-only inline for per-stage execution metrics."""

    model = IngestionRunStageMetric
    extra = 0
    can_delete = False
    max_num = 0
    fields = [
        "stage_name",
        "status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "details_json",
    ]
    readonly_fields = [
        "stage_name",
        "status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "details_json",
    ]
    show_change_link = False

    @admin.display(description="Duration (s)")
    def duration_seconds(self, obj):
        if obj.started_at is None or obj.finished_at is None:
            return None
        return (obj.finished_at - obj.started_at).total_seconds()

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    """Admin configuration for IngestionRun with operational focus."""

    list_display = [
        "id",
        "status",
        "intent",
        "queued_at",
        "processing_started_at",
        "finished_at",
        "queue_latency_seconds_display",
        "processing_duration_seconds_display",
        "total_duration_seconds_display",
        "timed_out",
        "failure_reason",
    ]

    list_filter = [
        "status",
        "intent",
        "timed_out",
        "failure_reason",
        "queued_at",
    ]

    search_fields = [
        "id",
        "parameters_json",
    ]

    ordering = ["-started_at"]

    readonly_fields = [
        "status",
        "intent",
        "queued_at",
        "processing_started_at",
        "finished_at",
        "queue_latency_seconds_display",
        "processing_duration_seconds_display",
        "total_duration_seconds_display",
        "timed_out",
        "failure_reason",
        "error_message",
        "worker_label",
        "events_processed",
        "events_created",
        "events_skipped",
        "events_revised",
        "admissions_seen",
        "admissions_created",
        "admissions_updated",
        "parameters_json",
        "gaps_json",
    ]

    inlines = [IngestionRunStageMetricInline]

    @admin.display(description="Queue latency (s)")
    def queue_latency_seconds_display(self, obj):
        return obj.queue_latency_seconds

    @admin.display(description="Processing duration (s)")
    def processing_duration_seconds_display(self, obj):
        return obj.processing_duration_seconds

    @admin.display(description="Total duration (s)")
    def total_duration_seconds_display(self, obj):
        return obj.total_duration_seconds
