"""Tests for bed_status_view (Slice S6)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestBedStatusView:
    def test_anonymous_redirected(self, client):
        url = reverse("census:bed_status")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_authenticated_can_access(self, admin_client):
        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Nenhum dado de censo disponível" in response.content.decode()

    def test_shows_sector_data(self, admin_client):
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="01",
            prontuario="111",
            nome="PACIENTE UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="02",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI A" in content
        assert "PACIENTE UM" in content

    def test_uses_only_latest_snapshot(self, admin_client):
        old_time = timezone.now() - timezone.timedelta(hours=4)
        new_time = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old_time,
            setor="OLD SETOR",
            leito="01",
            prontuario="AAA",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new_time,
            setor="NEW SETOR",
            leito="01",
            prontuario="BBB",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()

        assert "NEW SETOR" in content
        assert "OLD SETOR" not in content
