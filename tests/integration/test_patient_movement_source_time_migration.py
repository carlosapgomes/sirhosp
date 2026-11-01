"""SMT-S1 migration evidence: additive optional movement time, no backfill.

Runs forward from the pre-change census migration state with an existing
movement row and proves the new column is nullable, additive, unbackfilled,
and leaves the ledger identity and indexes untouched.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OLD_STATE = ("census", "0025_censussnapshot_source_timestamps")
NEW_STATE = ("census", "0026_patientmovement_source_movement_at")
LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)


def _index_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {
        name for name, details in constraints.items() if details["index"]
    }


def _unique_constraint_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {
        name
        for name, details in constraints.items()
        if details.get("unique")
    }


@pytest.mark.django_db(transaction=True)
def test_migration_adds_nullable_movement_time_without_backfill():
    executor = MigrationExecutor(connection)
    executor.migrate([OLD_STATE])
    old_apps = executor.loader.project_state([OLD_STATE]).apps

    old_patient_model = old_apps.get_model("patients", "Patient")
    old_movement_model = old_apps.get_model("census", "PatientMovement")
    table = old_movement_model._meta.db_table
    old_indexes = _index_names(table)
    old_unique = _unique_constraint_names(table)

    patient = old_patient_model.objects.create(
        source_system="tasy",
        patient_source_key="SYN-SMT-MIG-0001",
        name="PACIENTE SINTETICO MIG",
    )
    first_seen = datetime(2026, 1, 10, 8, 0, tzinfo=LOCAL_TZ)
    last_seen = datetime(2026, 1, 11, 8, 0, tzinfo=LOCAL_TZ)
    movement = old_movement_model.objects.create(
        patient=patient,
        movement_date=date(2026, 1, 10),
        sector="PS",
        bed="LEITO-MIG-01",
        origin="",
        discharge_type="",
        sequence=0,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
    )

    try:
        executor = MigrationExecutor(connection)
        executor.migrate([NEW_STATE])
        new_apps = executor.loader.project_state([NEW_STATE]).apps
        new_movement_model = new_apps.get_model("census", "PatientMovement")

        migrated = new_movement_model.objects.get(pk=movement.pk)

        assert migrated.source_movement_at is None
        assert migrated.patient_id == patient.pk
        assert migrated.movement_date == date(2026, 1, 10)
        assert migrated.sector == "PS"
        assert migrated.bed == "LEITO-MIG-01"
        assert migrated.first_seen_at == first_seen
        assert migrated.last_seen_at == last_seen
        assert _index_names(table) == old_indexes
        assert _unique_constraint_names(table) == old_unique
        assert "uq_patient_movement_date_sector" in old_unique
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
