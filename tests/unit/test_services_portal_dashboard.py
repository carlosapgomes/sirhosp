"""Slice DRD-S1: Dashboard with real DB queries."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestDashboardRealStats:
    """S1: Dashboard shows real data from CensusSnapshot, Patient, Admission."""

    def test_dashboard_empty_db_shows_zeros(self, admin_client):
        """When DB is empty, all counts are zero and page renders."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["stats"]["internados"] == 0
        assert ctx["stats"]["cadastrados"] == 0
        assert ctx["stats"]["altas_24h"] == 0
        assert ctx["coleta"]["setores"] == 0
        assert ctx["coleta"]["ultima_varredura"] == "Nenhum dado disponível"

    def test_dashboard_shows_occupied_count(self, admin_client):
        """Dashboard shows count of occupied beds from latest snapshot."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC A", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PAC B", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="03",
            prontuario="", nome="VAZIO", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["stats"]["internados"] == 2
        assert ctx["coleta"]["setores"] == 1

    def test_dashboard_shows_patient_count(self, admin_client):
        """Dashboard shows total Patient count."""
        Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A",
        )
        Patient.objects.create(
            patient_source_key="P2", source_system="tasy", name="B",
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["cadastrados"] == 2

    def test_dashboard_shows_discharges_24h(self, admin_client):
        """Dashboard counts admissions discharged in last 24h."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A",
        )
        now = timezone.now()
        # Discharged 1 hour ago
        Admission.objects.create(
            patient=patient, source_admission_key="ADM1", source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=now - timedelta(hours=1),
        )
        # Discharged 48 hours ago (should NOT be counted)
        Admission.objects.create(
            patient=patient, source_admission_key="ADM2", source_system="tasy",
            admission_date=now - timedelta(days=10),
            discharge_date=now - timedelta(hours=48),
        )
        # Not discharged yet
        Admission.objects.create(
            patient=patient, source_admission_key="ADM3", source_system="tasy",
            admission_date=now - timedelta(days=2),
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["altas_24h"] == 1

    def test_dashboard_shows_sectors_and_timestamp(self, admin_client):
        """Dashboard shows sector count and last capture time."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="CLINICA", leito="01",
            prontuario="222", nome="PAC2", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["coleta"]["setores"] == 2
        assert ctx["coleta"]["ultima_varredura"] == now.strftime("%d/%m/%Y %H:%M")

    def test_dashboard_no_census_shows_fallback(self, admin_client):
        """Without CensusSnapshot, shows informative message."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["coleta"]["ultima_varredura"] == "Nenhum dado disponível"

    def test_dashboard_uses_only_latest_snapshot(self, admin_client):
        """Dashboard uses only the most recent CensusSnapshot."""
        old = timezone.now() - timedelta(hours=4)
        new = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old, setor="OLD", leito="01",
            prontuario="A", nome="OLD", especialidade="X",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW", leito="01",
            prontuario="B", nome="NEW", especialidade="Y",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW", leito="02",
            prontuario="C", nome="NEW2", especialidade="Z",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["stats"]["internados"] == 2  # from "new", not 1 from "old"
        assert ctx["coleta"]["setores"] == 1  # only "NEW" sector

    def test_dashboard_has_leitos_card(self, admin_client):
        """Dashboard quick actions include Leitos card linking to /beds/."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert 'census:bed_status' in content or '/beds/' in content
