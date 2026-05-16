"""Tests for DailyDischargeCount model (Slice S1)."""

from datetime import date

import pytest
from django.db.utils import IntegrityError

from apps.discharges.models import DailyDischargeCount, DischargeRecord


@pytest.mark.django_db
class TestDailyDischargeCountModel:
    """Basic model creation and constraints."""

    def test_create_daily_count(self):
        entry = DailyDischargeCount.objects.create(
            date=date(2026, 4, 28),
            count=5,
        )
        assert entry.date == date(2026, 4, 28)
        assert entry.count == 5
        assert entry.created_at is not None
        assert entry.updated_at is not None

    def test_date_is_unique(self):
        DailyDischargeCount.objects.create(date=date(2026, 4, 28), count=5)
        with pytest.raises(IntegrityError):
            DailyDischargeCount.objects.create(date=date(2026, 4, 28), count=10)

    def test_default_count_is_zero(self):
        entry = DailyDischargeCount.objects.create(date=date(2026, 4, 28))
        assert entry.count == 0

    def test_str_representation(self):
        entry = DailyDischargeCount.objects.create(
            date=date(2026, 4, 28), count=7,
        )
        assert "2026-04-28" in str(entry)
        assert "7" in str(entry)


@pytest.mark.django_db
class TestDischargeRecordModel:
    """Tests for DischargeRecord model with leito and especialidade."""

    def test_create_with_leito_especialidade(self):
        daily = DailyDischargeCount.objects.create(
            date=date(2026, 5, 15), count=3,
        )
        record = DischargeRecord.objects.create(
            daily_count=daily,
            date=date(2026, 5, 15),
            prontuario="1234567",
            nome="PACIENTE TESTE",
            data_internacao="10/05/2026",
            leito="UG01A",
            especialidade="NEF",
        )
        assert record.leito == "UG01A"
        assert record.especialidade == "NEF"
        assert record.prontuario == "1234567"

    def test_str_includes_fields(self):
        daily = DailyDischargeCount.objects.create(
            date=date(2026, 5, 15), count=2,
        )
        record = DischargeRecord.objects.create(
            daily_count=daily,
            date=date(2026, 5, 15),
            prontuario="7654321",
            nome="OUTRO PACIENTE",
            leito="A01",
            especialidade="CLM",
        )
        assert "7654321" in str(record)
        assert "OUTRO PACIENTE" in str(record)
