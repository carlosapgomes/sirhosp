"""SMT-S1 integration: upsert -> isolated PostgreSQL -> readback.

Runs the real ``upsert_patient_movements`` service against the test
PostgreSQL database: the column exists as a nullable ``timestamptz``, all
four D2 policy cases survive a fresh query, and the ledger identity and
historical (non-backfilled) behavior stay intact. Synthetic rows only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.census.services import upsert_patient_movements
from apps.patients.models import Patient

LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)
PRONTUARIO = "SYN-SMT-PG-0001"
SECTOR = "PS"
MOVEMENT_DATE_TEXT = "02/02/2026"
MOVEMENT_DATE = date(2026, 2, 2)
FIRST_TIME = datetime(2026, 2, 2, 9, 45, tzinfo=LOCAL_TZ)
LATEST_TIME = datetime(2026, 2, 2, 23, 5, tzinfo=LOCAL_TZ)


def _snapshot(
    *,
    captured_at: datetime,
    source_movement_at: datetime | None,
    movement_date: str = MOVEMENT_DATE_TEXT,
    sector: str = SECTOR,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        setor=sector,
        leito="LEITO-SMT-01",
        prontuario=PRONTUARIO,
        nome="PACIENTE SINTETICO SMT",
        especialidade="CLI",
        data_internacao="01/02/2026",
        data_movimentacao=movement_date,
        source_movement_at=source_movement_at,
        bed_status=BedStatus.OCCUPIED,
    )


def _base_captured_at() -> datetime:
    return timezone.now() - timedelta(days=1)


def _movement_id(
    movement_date: date = MOVEMENT_DATE,
    sector: str = SECTOR,
) -> int:
    return PatientMovement.objects.get(
        patient__patient_source_key=PRONTUARIO,
        movement_date=movement_date,
        sector=sector,
    ).pk


def _read_back(pk: int):
    """Read the stored value with a fresh query, not the caller's object."""
    return PatientMovement.objects.filter(pk=pk).values_list(
        "source_movement_at", flat=True
    ).get()


@pytest.mark.django_db
class TestMovementSourceTimePostgres:
    def test_column_is_nullable_timestamp_with_time_zone(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                [PatientMovement._meta.db_table, "source_movement_at"],
            )
            column = cursor.fetchone()

        assert column == ("timestamp with time zone", "YES")

    def test_create_with_time_is_read_back_from_postgres(self):
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=LATEST_TIME,
        )

        upsert_patient_movements()

        stored = _read_back(_movement_id())
        assert stored == LATEST_TIME
        assert timezone.is_aware(stored)
        local = timezone.localtime(stored, LOCAL_TZ)
        assert (local.date(), local.hour, local.minute) == (
            date(2026, 2, 2),
            23,
            5,
        )
        assert local.utcoffset() == timedelta(hours=-3)

    def test_datetime_readback_round_trips_in_configured_timezone(self):
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=FIRST_TIME,
        )

        upsert_patient_movements()

        assert _read_back(_movement_id()) == FIRST_TIME

    def test_repeated_observation_refreshes_stored_time(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=FIRST_TIME)
        upsert_patient_movements()
        pk = _movement_id()
        assert _read_back(pk) == FIRST_TIME

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=LATEST_TIME,
        )
        upsert_patient_movements()

        assert _read_back(pk) == LATEST_TIME

    def test_later_time_fills_previously_null_value(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=None)
        upsert_patient_movements()
        pk = _movement_id()
        assert _read_back(pk) is None

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=FIRST_TIME,
        )
        upsert_patient_movements()

        assert _read_back(pk) == FIRST_TIME

    def test_later_snapshot_without_time_never_erases_stored_time(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=FIRST_TIME)
        upsert_patient_movements()
        pk = _movement_id()
        before = PatientMovement.objects.get(pk=pk)

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=None,
        )
        upsert_patient_movements()

        after = PatientMovement.objects.get(pk=pk)
        assert _read_back(pk) == FIRST_TIME
        assert after.first_seen_at == before.first_seen_at
        assert after.last_seen_at >= before.last_seen_at

    def test_other_date_upsert_does_not_backfill_historical_movement(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key=PRONTUARIO,
            name="PACIENTE SINTETICO SMT",
        )
        now = timezone.now()
        historical = PatientMovement.objects.create(
            patient=patient,
            movement_date=date(2026, 1, 10),
            sector=SECTOR,
            first_seen_at=now,
            last_seen_at=now,
        )

        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=FIRST_TIME,
        )
        upsert_patient_movements()

        historical_pk = historical.pk
        historical.refresh_from_db()
        assert PatientMovement.objects.filter(
            patient=patient
        ).count() == 2
        assert _read_back(historical_pk) is None
        assert historical.first_seen_at == now
        assert historical.last_seen_at == now

    def test_unique_identity_is_preserved(self):
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=FIRST_TIME,
        )
        upsert_patient_movements()
        upsert_patient_movements()

        assert PatientMovement.objects.count() == 1
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PatientMovement.objects.create(
                    patient=Patient.objects.get(
                        patient_source_key=PRONTUARIO
                    ),
                    movement_date=MOVEMENT_DATE,
                    sector=SECTOR,
                    first_seen_at=timezone.now(),
                    last_seen_at=timezone.now(),
                )
