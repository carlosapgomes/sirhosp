"""Patient admin configuration (Slice S6) and merge audit (RPSA-S4)."""

from __future__ import annotations

from django.contrib import admin, messages

from apps.patients.models import Admission, AdmissionMergeOperation, Patient
from apps.patients.services import merge_patients


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    """Maintenance admin for admissions, including merged rows (RPSA-S4).

    The default manager hides merged rows from every clinical surface, so
    the admin queryset deliberately uses the unfiltered ``all_objects``
    access: authorized staff must be able to inspect the canonical row
    and the merged duplicate with its ``merged_into`` target side by
    side.
    """

    list_display = [
        "pk",
        "patient",
        "source_admission_key",
        "admission_date",
        "discharge_date",
        "ward",
        "bed",
        "merged_into",
    ]
    search_fields = [
        "patient__name",
        "patient__patient_source_key",
        "source_admission_key",
    ]
    list_filter = ["source_system"]

    def get_queryset(self, request):
        return Admission.all_objects.get_queryset().select_related(
            "patient", "merged_into"
        )


@admin.register(AdmissionMergeOperation)
class AdmissionMergeOperationAdmin(admin.ModelAdmin):
    """Read-only exposure of the append-only merge audit (RPSA-S4).

    Audit rows are retained indefinitely; the admin offers no add,
    change or delete actions (design decision 10).
    """

    list_display = [
        "operation_uuid",
        "canonical_admission_id",
        "merged_admission_id",
        "confirmed_local_date",
        "source_confirmed_at",
        "rolled_back_at",
        "created_at",
    ]
    search_fields = ["operation_uuid"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


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
