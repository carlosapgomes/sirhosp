"""Integration checks for the RPSA-S4 merge gate.

Verifies the schema-level guarantees that span models, managers, admin and
the ingestion upsert path: the transfer registry equals the fresh runtime
derivation of ``Admission._meta.related_objects`` (superset of the S1
inventory including the discharge and death evidence FKs), the admissions
snapshot upsert resolves a merged row's key to the canonical winner without
creating a second row, the persistent-session target lookup stays
None-guarded, the Django admin exposes canonical and merged rows plus the
append-only operation, and normal clinical listings hide merged rows.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.contrib import admin as django_admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.ingestion.management.commands import (
    process_ingestion_runs_persistent_session as psw_command,
)
from apps.ingestion.services import upsert_admission_snapshot
from apps.patients.admin import AdmissionAdmin, AdmissionMergeOperationAdmin
from apps.patients.admission_merge import (
    AdmissionSourceConfirmation,
    SourceEpisode,
    build_relation_registry,
    merge_admissions,
    source_confirmation_fingerprint,
)
from apps.patients.models import (
    Admission,
    AdmissionMergeOperation,
    AdmissionSourceAlias,
    Patient,
)
from apps.patients.services import list_admissions_for_patient

TZ_LOCAL = ZoneInfo("America/Bahia")

# RPSA-S1 inventory (relation-inventory evidence, pre-evidence-FK baseline):
# the runtime registry must remain a superset of these accessors.
S1_INVENTORY_ACCESSORS = frozenset(
    {
        "events",
        "summary_state",
        "summary_versions",
        "summary_runs",
        "pipeline_runs",
        "movements",
        "evolution_extraction_coverage",
        "merged_from",
        "source_aliases",
    }
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ_LOCAL)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None,
    end: str | None,
) -> Admission:
    # Non-empty synthetic record number: the merge must never move or
    # audit identity, and these fixtures must not pass vacuously.
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start) if start else None,
        discharge_date=_dt(end) if end else None,
        source_patient_reference=f"PRONT-{key}",
    )


def _confirmation(local_date: str = "2026-05-01") -> AdmissionSourceConfirmation:
    return AdmissionSourceConfirmation(
        patient_record="P_INT_1",
        local_admission_date=date.fromisoformat(local_date),
        captured_at=_dt("2026-05-04T09:00:00"),
        failed=False,
        episodes=(
            SourceEpisode(
                source_admission_key="ADM_CLOSED",
                admission_start=_dt("2026-05-01T08:00:00"),
                admission_end=_dt("2026-05-03T10:00:00"),
            ),
        ),
    )


def _merged_pair() -> tuple[Patient, Admission, Admission, AdmissionMergeOperation]:
    patient = _make_patient("P_INT_1")
    canonical = _make_admission(patient, "ADM_OPEN", "2026-05-01T08:00:00", None)
    duplicate = _make_admission(
        patient, "ADM_CLOSED", "2026-05-01T09:00:00", "2026-05-03T10:00:00"
    )
    confirmation = _confirmation()
    result = merge_admissions(
        first=duplicate,
        second=canonical,
        confirmation=confirmation,
        expected_fingerprint=source_confirmation_fingerprint(confirmation),
    )
    operation = AdmissionMergeOperation.objects.get(
        operation_uuid=result.operation_uuid
    )
    return patient, canonical, duplicate, operation


# ---------------------------------------------------------------------------
# Registry x runtime inventory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegistryMatchesRuntimeInventory:
    def test_registry_equals_fresh_runtime_derivation(self, db: object) -> None:
        admission_model = apps.get_model("patients", "Admission")
        runtime_accessors = {
            relation.get_accessor_name()
            for relation in admission_model._meta.related_objects
        }
        registry = build_relation_registry()
        assert set(registry) == runtime_accessors

    def test_registry_is_superset_of_s1_including_evidence_fks(
        self, db: object
    ) -> None:
        registry = build_relation_registry()
        assert S1_INVENTORY_ACCESSORS <= set(registry)
        for evidence_accessor in (
            "discharge_evidence",
            "death_evidence",
            "reconciliation_events",
        ):
            assert evidence_accessor in registry
            assert registry[evidence_accessor].reason


# ---------------------------------------------------------------------------
# Snapshot upsert never recreates a merged duplicate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpsertWithMergedRowKey:
    def test_merged_row_key_resolves_winner_without_second_row(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()

        result = upsert_admission_snapshot(
            patient,
            [
                {
                    "admission_key": "ADM_CLOSED",
                    "admission_start": "2026-05-01 08:00:00",
                    "admission_end": "2026-05-03 10:00:00",
                    "ward": "",
                    "bed": "",
                }
            ],
        )

        assert result["created"] == 0
        assert result["ambiguous"] == 0
        assert Admission.all_objects.filter(patient=patient).count() == 2
        canonical.refresh_from_db()
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == canonical.pk

    def test_merged_alias_key_resolves_winner_without_second_row(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        AdmissionSourceAlias.objects.create(
            admission=duplicate, source_system="tasy", alias_key="ADM_DUP_ALIAS"
        )
        # Re-point the merged row's alias to the canonical winner (merge
        # semantics) so the alias resolves the winner like the merge does.
        AdmissionSourceAlias.objects.filter(admission=duplicate).update(
            admission=canonical
        )

        result = upsert_admission_snapshot(
            patient,
            [
                {
                    "admission_key": "ADM_DUP_ALIAS",
                    "admission_start": "2026-05-01 08:00:00",
                    "admission_end": None,
                    "ward": "",
                    "bed": "",
                }
            ],
        )

        assert result["created"] == 0
        assert Admission.all_objects.filter(patient=patient).count() == 2


# ---------------------------------------------------------------------------
# Persistent-session target lookup stays None-guarded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPersistentSessionTargetLookupGuard:
    def test_merged_target_pk_is_none_guarded_and_fails_loud(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()

        with pytest.raises(ValidationError):
            psw_command.Command._resolve_target_admission_context(
                patient=patient,
                params={"admission_id": str(duplicate.pk)},
            )


# ---------------------------------------------------------------------------
# Admin exposure (maintenance access) and clinical hiding
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminAndClinicalExposure:
    def test_admin_queryset_exposes_canonical_and_merged_rows(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        request = RequestFactory().get("/")
        model_admin = AdmissionAdmin(Admission, django_admin.site)

        qs = model_admin.get_queryset(request)

        assert set(qs.values_list("pk", flat=True)) == {canonical.pk, duplicate.pk}

    def test_admin_exposes_operation_readonly(self, db: object) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        request = RequestFactory().get("/")
        model_admin = AdmissionMergeOperationAdmin(
            AdmissionMergeOperation, django_admin.site
        )

        assert operation in model_admin.get_queryset(request)
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False

    def test_clinical_listing_shows_canonical_once(self, db: object) -> None:
        patient, canonical, duplicate, _ = _merged_pair()

        listing = list_admissions_for_patient(patient.pk)

        assert [row.pk for row in listing] == [canonical.pk]
        assert Admission.objects.filter(patient=patient).count() == 1
