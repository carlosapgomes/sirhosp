"""Patient admin configuration (Slice S6) and merge audit (RPSA-S4).

RPSA-S6 adds read-only exposure of the append-only reconciliation audit
(``ReconciliationEvent``) and the conservative stale-admission cases
(``StaleAdmissionCase``): no add, change or delete actions (design
decision 10 — audit is retained indefinitely and never mutated).
"""

from __future__ import annotations

from django.contrib import admin, messages

from apps.patients.models import (
    Admission,
    AdmissionMergeOperation,
    Patient,
    ReconciliationEvent,
    StaleAdmissionCase,
)
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


@admin.register(ReconciliationEvent)
class ReconciliationEventAdmin(admin.ModelAdmin):
    """Read-only exposure of the append-only reconciliation audit (RPSA-S6).

    Audit rows are retained indefinitely; the admin offers no add,
    change or delete actions (design decision 10). Payloads carry
    structural state only — never patient identity or clinical text.
    """

    list_display = [
        "operation_uuid",
        "source_kind",
        "source_id",
        "admission",
        "status",
        "exit_type",
        "reason_code",
        "prior_discharge_date",
        "new_discharge_date",
        "created_at",
    ]
    list_filter = ["status", "exit_type", "source_kind"]
    search_fields = ["operation_uuid", "source_id"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(StaleAdmissionCase)
class StaleAdmissionCaseAdmin(admin.ModelAdmin):
    """Read-only exposure of conservative stale-admission cases (RPSA-S6).

    Cases are operational audit state driven by the census observation
    module; the admin offers no add, change or delete actions. Identity
    columns (patient name/record) are authorized in the staff-only admin.
    """

    list_display = [
        "pk",
        "admission",
        "first_absence_at",
        "last_absence_at",
        "resolved_at",
        "resolution_reason",
        "last_enqueued_at",
        "last_enqueue_outcome",
    ]
    list_filter = ["resolution_reason", "last_enqueue_outcome"]
    search_fields = [
        "admission__patient__name",
        "admission__patient__patient_source_key",
    ]

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
