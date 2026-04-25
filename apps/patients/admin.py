"""Patient admin configuration (Slice S6)."""

from __future__ import annotations

from django.contrib import admin, messages

from apps.patients.models import Patient
from apps.patients.services import merge_patients


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["name", "patient_source_key", "date_of_birth", "gender"]
    search_fields = ["name", "patient_source_key"]
    ordering = ["name"]
    actions = ["merge_selected_patients"]

    @admin.action(description="Merge selected patients (keep lowest ID)")
    def merge_selected_patients(self, request, queryset):
        if queryset.count() < 2:
            self.message_user(
                request,
                "Select at least 2 patients to merge.",
                level=messages.WARNING,
            )
            return

        # Sort by ID ascending — keep the lowest
        sorted_patients = list(queryset.order_by("pk"))
        keep = sorted_patients[0]
        to_merge = sorted_patients[1:]

        merged_count = 0
        for merge_patient in to_merge:
            try:
                merge_patients(keep=keep, merge=merge_patient)
                merged_count += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Error merging {merge_patient}: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"Merged {merged_count} patient(s) into {keep} (ID={keep.pk}).",
            level=messages.SUCCESS,
        )
