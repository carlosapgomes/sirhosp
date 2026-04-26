"""S2: Censo Hospitalar page with real data from CensusSnapshot."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestCensoRealData:
    """S2: Censo page shows real data from CensusSnapshot (occupied only)."""

    def test_censo_empty_db_shows_message(self, admin_client):
        """Without CensusSnapshot, shows empty state."""
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Censo Hospitalar" in content

    def test_censo_shows_occupied_patients(self, admin_client):
        """Only occupied beds appear on censo page."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE BETA", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        # Empty bed — should NOT appear
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="03",
            prontuario="", nome="VAZIO", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE ALFA" in content
        assert "PACIENTE BETA" in content
        assert "VAZIO" not in content

    def test_censo_shows_timestamp_when_available(self, admin_client):
        """Censo page shows capture timestamp."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should contain date somewhere
        date_str = now.strftime("%d/%m/%Y")
        assert date_str in content

    def test_censo_filters_by_setor(self, admin_client):
        """Filter by sector shows only that sector's patients."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC UTI", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="CLINICA", leito="01",
            prontuario="222", nome="PAC CLINICA", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?setor=UTI+A"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PAC UTI" in content
        assert "PAC CLINICA" not in content

    def test_censo_search_by_name(self, admin_client):
        """Free-text search filters by patient name."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=JOAO"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_search_by_prontuario(self, admin_client):
        """Free-text search filters by patient record number."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="99999", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="88888", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=99999"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_dropdown_has_real_setores(self, admin_client):
        """Sector dropdown is populated from actual sectors in the snapshot."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI GERAL", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA B", leito="01",
            prontuario="222", nome="PAC2", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI GERAL" in content
        assert "ENFERMARIA B" in content
        assert "Todos os setores" in content  # the "all" option remains

    def test_censo_uses_only_latest_snapshot(self, admin_client):
        """Only the most recent CensusSnapshot is used."""
        from datetime import timedelta
        old = timezone.now() - timedelta(hours=4)
        new = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old, setor="OLD SETOR", leito="01",
            prontuario="AAA", nome="OLD PATIENT", especialidade="X",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW SETOR", leito="01",
            prontuario="BBB", nome="NEW PATIENT", especialidade="Y",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "NEW PATIENT" in content
        assert "OLD PATIENT" not in content

    def test_censo_row_links_to_patient_search(self, admin_client):
        """Clicking a censo row links to patient search by prontuario."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="12345", nome="PAC LINK", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "q=12345" in content
