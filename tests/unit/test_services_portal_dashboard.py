"""Slice DRD-S1: Dashboard with real DB queries.
Slice IRMD-S6: Ingestion metric cards on dashboard.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun
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


@pytest.mark.django_db
class TestDashboardIngestionMetrics:
    """S6: Dashboard shows ingestion operation metric cards (24h window)."""

    def _create_run(self, **kwargs):
        """Helper to create an IngestionRun with defaults for 24h window."""
        now = timezone.now()
        defaults = {
            "status": "succeeded",
            "intent": "full_sync",
            "queued_at": now - timedelta(hours=2),
            "processing_started_at": now - timedelta(hours=1, minutes=55),
            "finished_at": now - timedelta(hours=1),
            "timed_out": False,
            "failure_reason": "",
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def test_dashboard_shows_ingestion_metrics_with_data(self, admin_client):
        """With runs in the last 24h, cards show correct aggregated values."""
        # 4 succeeded, 1 failed (timeout)
        for _ in range(4):
            self._create_run(status="succeeded", timed_out=False)
        self._create_run(
            status="failed", timed_out=True, failure_reason="timeout",
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200

        ingestion = response.context["ingestion_stats"]
        assert ingestion["total_finished"] == 5
        assert ingestion["success_rate"] == 80.0   # 4/5
        assert ingestion["timeout_rate"] == 20.0   # 1/5
        assert ingestion["avg_duration_seconds"] > 0

    def test_ingestion_metrics_cards_with_no_runs(self, admin_client):
        """When no runs exist in the 24h window, all values are zero."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200

        ingestion = response.context["ingestion_stats"]
        assert ingestion["total_finished"] == 0
        assert ingestion["success_rate"] == 0.0
        assert ingestion["timeout_rate"] == 0.0
        assert ingestion["avg_duration_seconds"] == 0

    def test_ingestion_metrics_only_counts_last_24h(self, admin_client):
        """Runs older than 24h are excluded from dashboard aggregation."""
        now = timezone.now()
        # Old run (25 hours ago)
        IngestionRun.objects.create(
            status="succeeded",
            finished_at=now - timedelta(hours=25),
            processing_started_at=now - timedelta(hours=26),
        )
        # Recent run
        self._create_run(status="succeeded")

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200

        ingestion = response.context["ingestion_stats"]
        assert ingestion["total_finished"] == 1

    def test_dashboard_has_ingestion_metrics_cta(self, admin_client):
        """Dashboard includes a CTA linking to ingestion metrics page."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Verify the URL for ingestion_metrics is present
        metrics_url = reverse("services_portal:ingestion_metrics")
        assert metrics_url in content
