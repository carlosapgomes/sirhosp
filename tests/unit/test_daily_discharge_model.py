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

    def test_create_with_alta_saida(self):
        daily = DailyDischargeCount.objects.create(
            date=date(2026, 5, 15), count=3,
        )
        from datetime import datetime
        alta = datetime(2026, 5, 15, 10, 8)
        saida = datetime(2026, 5, 15, 11, 5)
        record = DischargeRecord.objects.create(
            daily_count=daily,
            alta_em=alta,
            saida_em=saida,
            prontuario="1234567",
            nome="PACIENTE TESTE",
            data_internacao="10/05/2026",
            leito="UG01A",
            especialidade="NEF",
        )
        assert record.alta_em == alta
        assert record.saida_em == saida
        assert record.leito == "UG01A"
        assert record.especialidade == "NEF"
        assert record.prontuario == "1234567"

    def test_alta_saida_nullable(self):
        daily = DailyDischargeCount.objects.create(
            date=date(2026, 5, 15), count=1,
        )
        record = DischargeRecord.objects.create(
            daily_count=daily,
            prontuario="7654321",
            nome="PACIENTE SEM ALTA",
            data_internacao="10/05/2026",
        )
        assert record.alta_em is None
        assert record.saida_em is None
        assert "7654321" in str(record)

    def test_unique_together_constraint(self):
        daily = DailyDischargeCount.objects.create(
            date=date(2026, 5, 15), count=2,
        )
        DischargeRecord.objects.create(
            daily_count=daily,
            alta_em=None,
            prontuario="9999999",
            nome="TESTE",
            data_internacao="10/05/2026",
        )
        with pytest.raises(IntegrityError):
            DischargeRecord.objects.create(
                daily_count=daily,
                alta_em=None,
                prontuario="9999999",
                nome="TESTE DUPLICADO",
                data_internacao="10/05/2026",
            )
