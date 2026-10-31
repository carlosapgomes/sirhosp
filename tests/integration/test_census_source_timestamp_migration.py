"""ECD-S1 migration evidence: additive optional precision, no backfill.

Runs forward from the pre-change migration state with an existing snapshot
row and proves the two new columns are nullable, additive and unbackfilled.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OLD_STATE = ("census", "0024_occupancy_quality_warning_v4_v5")
NEW_STATE = ("census", "0025_censussnapshot_source_timestamps")
LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)


def _index_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {
        name for name, details in constraints.items() if details["index"]
    }


@pytest.mark.django_db(transaction=True)
def test_migration_adds_nullable_source_timestamps_without_backfill():
    executor = MigrationExecutor(connection)
    executor.migrate([OLD_STATE])
    old_apps = executor.loader.project_state([OLD_STATE]).apps

    old_snapshot_model = old_apps.get_model("census", "CensusSnapshot")
    old_run_model = old_apps.get_model("ingestion", "IngestionRun")
    old_indexes = _index_names(old_snapshot_model._meta.db_table)

    run = old_run_model.objects.create(
        intent="census_extraction",
        status="succeeded",
    )
    snapshot = old_snapshot_model.objects.create(
        captured_at=datetime(2026, 2, 1, 12, 0, tzinfo=LOCAL_TZ),
        ingestion_run=run,
        setor="SETOR 001",
        leito="LEITO001A",
        prontuario="SYN-0001",
        nome="PACIENTE SINTETICO",
        especialidade="CLI",
        data_internacao="01/02/2026",
        data_movimentacao="02/02/2026",
        bed_status="occupied",
        age_band="unknown",
    )

    try:
        executor = MigrationExecutor(connection)
        executor.migrate([NEW_STATE])
        new_apps = executor.loader.project_state([NEW_STATE]).apps
        new_snapshot_model = new_apps.get_model("census", "CensusSnapshot")

        migrated = new_snapshot_model.objects.get(pk=snapshot.pk)

        assert migrated.source_admission_at is None
        assert migrated.source_movement_at is None
        assert migrated.data_internacao == "01/02/2026"
        assert migrated.data_movimentacao == "02/02/2026"
        assert migrated.ingestion_run_id == run.pk
        assert _index_names(new_snapshot_model._meta.db_table) == old_indexes
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
