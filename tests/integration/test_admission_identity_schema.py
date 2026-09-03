"""Integration schema checks for layered admission identity (RPSA-S1).

Verifies the migrated database schema (alias table, merge marker, database
constraints) and compares the runtime Admission reverse relations against the
accessor set recorded in the relation-inventory evidence. The expected
accessor set is inlined here so the suite is self-contained on a clean
checkout: the evidence markdown is gitignored documentation and must never be
loaded by tests.
"""

import pytest
from django.apps import apps
from django.db import IntegrityError, connection

# Mirrors the "Machine-readable accessor list" fenced block in
# openspec/changes/reconcile-patient-exits-and-stale-admissions/evidence/
# admission-relation-inventory.md (kept in sync manually; that file stays
# documentation only and is never read by this suite).
EXPECTED_REVERSE_RELATION_ACCESSORS = frozenset(
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


def _table_columns(table: str) -> set[str]:
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, table)
    return {column.name for column in columns}


def _table_constraints(table: str) -> dict[str, dict[str, object]]:
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table)


@pytest.mark.django_db
class TestAdmissionIdentitySchema:
    """The identity migration creates columns, tables and constraints."""

    def test_merge_marker_column_exists(self, db: object) -> None:
        columns = _table_columns("patients_admission")
        assert "merged_into_id" in columns

    def test_alias_table_exists_with_unique_constraint(self, db: object) -> None:
        tables = connection.introspection.table_names()
        assert "patients_admissionsourcealias" in tables

        constraints = _table_constraints("patients_admissionsourcealias")
        unique_names = {
            name
            for name, definition in constraints.items()
            if definition.get("unique")
        }
        assert unique_names, "alias table must have a unique constraint"

    def test_no_self_merge_check_constraint_exists(self, db: object) -> None:
        constraints = _table_constraints("patients_admission")
        check_names = {
            name
            for name, definition in constraints.items()
            if definition.get("check") and not definition.get("unique")
        }
        assert check_names, "admission table must have the no-self-merge check"

    def test_alias_unique_constraint_rejects_duplicate_key(
        self, db: object
    ) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        admission_model = apps.get_model("patients", "Admission")
        patient_model = apps.get_model("patients", "Patient")

        patient = patient_model.objects.create(
            patient_source_key="P_SCHEMA1",
            source_system="tasy",
            name="PACIENTE SCHEMA1",
        )
        first = admission_model.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_SCH_A",
        )
        second = admission_model.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_SCH_B",
        )
        alias_model.objects.create(
            admission=first, source_system="tasy", alias_key="ADM_SCH_OLD"
        )

        with pytest.raises(IntegrityError):
            alias_model.objects.create(
                admission=second, source_system="tasy", alias_key="ADM_SCH_OLD"
            )

    def test_self_merge_is_rejected(self, db: object) -> None:
        admission_model = apps.get_model("patients", "Admission")
        patient_model = apps.get_model("patients", "Patient")

        patient = patient_model.objects.create(
            patient_source_key="P_SCHEMA2",
            source_system="tasy",
            name="PACIENTE SCHEMA2",
        )
        admission = admission_model.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_SCH_SELF",
        )
        admission.merged_into_id = admission.pk

        with pytest.raises(IntegrityError):
            admission.save()


@pytest.mark.django_db
class TestRelationInventoryMatchesRuntime:
    """The evidence inventory must equal the runtime reverse relations."""

    def test_inventory_lists_every_runtime_reverse_relation(
        self, db: object
    ) -> None:
        admission_model = apps.get_model("patients", "Admission")
        runtime_accessors = {
            relation.get_accessor_name()
            for relation in admission_model._meta.related_objects
        }

        assert runtime_accessors == EXPECTED_REVERSE_RELATION_ACCESSORS
