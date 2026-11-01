"""SMT-S1: source movement time persisted in the PatientMovement ledger.

Behavior tests for the approved propagation policy (D1/D2): the hour comes
verbatim from the census snapshot processed by the real upsert, a snapshot
without an hour never erases a known value, and no hour is ever inferred.
Synthetic rows only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.census.services import upsert_patient_movements
from apps.patients.models import Patient

LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)
PRONTUARIO = "SYN-SMT-0001"
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
    prontuario: str = PRONTUARIO,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        setor=sector,
        leito="LEITO-SMT-01",
        prontuario=prontuario,
        nome="PACIENTE SINTETICO SMT",
        especialidade="CLI",
        data_internacao="01/02/2026",
        data_movimentacao=movement_date,
        source_movement_at=source_movement_at,
        bed_status=BedStatus.OCCUPIED,
    )


def _stored_movement(
    movement_date: date = MOVEMENT_DATE,
    sector: str = SECTOR,
) -> PatientMovement:
    return PatientMovement.objects.get(
        patient__patient_source_key=PRONTUARIO,
        movement_date=movement_date,
        sector=sector,
    )


def _base_captured_at() -> datetime:
    return timezone.now() - timedelta(days=1)


@pytest.mark.django_db
class TestMovementSourceTimePersistence:
    def test_created_movement_persists_snapshot_time_verbatim(self):
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=FIRST_TIME,
        )

        result = upsert_patient_movements()

        assert result["movements_created"] == 1
        movement = _stored_movement()
        assert movement.source_movement_at == FIRST_TIME
        assert timezone.is_aware(movement.source_movement_at)

    def test_created_movement_time_respects_configured_timezone(self):
        late_night = datetime(2026, 2, 2, 23, 5, tzinfo=LOCAL_TZ)
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=late_night,
        )

        upsert_patient_movements()

        stored = _stored_movement().source_movement_at
        local = timezone.localtime(stored, LOCAL_TZ)
        assert (local.date(), local.hour, local.minute) == (
            date(2026, 2, 2),
            23,
            5,
        )
        assert local.utcoffset() == timedelta(hours=-3)

    def test_date_only_snapshot_keeps_movement_without_time(self):
        _snapshot(
            captured_at=_base_captured_at(),
            source_movement_at=None,
            movement_date="03/02/2026",
        )

        result = upsert_patient_movements()

        assert result["movements_created"] == 1
        movement = _stored_movement(date(2026, 2, 3))
        assert movement.source_movement_at is None
        assert movement.movement_date == date(2026, 2, 3)
        assert movement.sector == SECTOR

    def test_repeated_observation_refreshes_time_from_latest_snapshot(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=FIRST_TIME)
        upsert_patient_movements()
        assert _stored_movement().source_movement_at == FIRST_TIME

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=LATEST_TIME,
        )
        upsert_patient_movements()

        assert _stored_movement().source_movement_at == LATEST_TIME

    def test_movement_without_time_gains_time_from_later_snapshot(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=None)
        upsert_patient_movements()
        assert _stored_movement().source_movement_at is None

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=FIRST_TIME,
        )
        upsert_patient_movements()

        assert _stored_movement().source_movement_at == FIRST_TIME

    def test_later_snapshot_without_time_preserves_known_time(self):
        captured = _base_captured_at()
        _snapshot(captured_at=captured, source_movement_at=FIRST_TIME)
        upsert_patient_movements()
        before = _stored_movement()

        _snapshot(
            captured_at=captured + timedelta(hours=1),
            source_movement_at=None,
        )
        result = upsert_patient_movements()

        after = _stored_movement()
        assert result["movements_updated"] == 1
        assert after.source_movement_at == FIRST_TIME
        assert after.first_seen_at == before.first_seen_at
        assert after.last_seen_at >= before.last_seen_at

    def test_historical_movement_stays_null_through_other_date_upsert(self):
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
            movement_date="02/02/2026",
        )
        upsert_patient_movements()

        historical.refresh_from_db()
        assert historical.source_movement_at is None
        assert historical.last_seen_at == now
        assert historical.first_seen_at == now
