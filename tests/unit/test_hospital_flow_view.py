"""Tests for hospital_flow_view (Slice S2)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.admissions.models import DailyAdmissionCount
from apps.census.models import BedStatus, CensusSnapshot
from apps.deaths.models import DailyDeathCount
from apps.discharges.models import DailyDischargeCount


@pytest.fixture
def make_snapshot():
    """Fixture to create CensusSnapshot rows easily."""

    def _make(
        captured_at: datetime,
        setor: str = "UTI GERAL",
        leito: str = "LEITO-01",
        prontuario: str = "PRONT-001",
        nome: str = "PACIENTE TESTE",
        bed_status: str = BedStatus.OCCUPIED,
    ) -> CensusSnapshot:
        return CensusSnapshot.objects.create(
            captured_at=captured_at,
            setor=setor,
            leito=leito,
            prontuario=prontuario,
            nome=nome,
            especialidade="NEF",
            bed_status=bed_status,
        )

    return _make


@pytest.mark.django_db
class TestHospitalFlowViewAuth:
    """Authentication and basic response tests."""

    def test_anonymous_redirected_to_login(self, client):
        """Anonymous user gets 302 redirect to login."""
        url = reverse("census:hospital_flow")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_authenticated_can_access(self, admin_client):
        """Authenticated user gets 200."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_uses_correct_template(self, admin_client):
        """Response uses the hospital_flow template."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "census/hospital_flow.html" in [
            t.name for t in response.templates
        ]


@pytest.mark.django_db
class TestHospitalFlowViewWindow:
    """Window parameter handling tests."""

    def test_default_window_is_90(self, admin_client):
        """Default window is 90 when no ?window= param."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.context["window"] == 90
        assert response.context["window_options"] == [30, 90, 180]

    def test_window_30(self, admin_client):
        """?window=30 sets context window to 30."""
        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        assert response.context["window"] == 30

    def test_window_180(self, admin_client):
        """?window=180 sets context window to 180."""
        url = reverse("census:hospital_flow") + "?window=180"
        response = admin_client.get(url)
        assert response.context["window"] == 180

    def test_window_invalid_fallback_90(self, admin_client):
        """Invalid ?window= value falls back to 90 (no 500)."""
        url = reverse("census:hospital_flow") + "?window=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["window"] == 90

    def test_window_zero_fallback_90(self, admin_client):
        """?window=0 (not in {30,90,180}) falls back to 90."""
        url = reverse("census:hospital_flow") + "?window=0"
        response = admin_client.get(url)
        assert response.context["window"] == 90

    def test_window_999_fallback_90(self, admin_client):
        """?window=999 (not in {30,90,180}) falls back to 90."""
        url = reverse("census:hospital_flow") + "?window=999"
        response = admin_client.get(url)
        assert response.context["window"] == 90


@pytest.mark.django_db
class TestHospitalFlowViewContext:
    """Context structure and data flow tests."""

    def test_context_has_flow_series(self, admin_client):
        """Context always has flow_series (list, possibly empty)."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert "flow_series" in response.context
        assert isinstance(response.context["flow_series"], list)

    def test_context_has_page_title(self, admin_client):
        """Context has page_title."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.context["page_title"] == "Fluxo Hospitalar"

    def test_context_has_active_menu(self, admin_client):
        """Context has active_menu == 'fluxo'."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.context["active_menu"] == "fluxo"

    def test_flow_series_includes_data(
        self, admin_client, make_snapshot
    ):
        """When data exists, flow_series reflects the service output."""
        tz = timezone.get_current_timezone()
        target = date.today()

        # 2 occupied beds today
        t = datetime(target.year, target.month, target.day, 8, 0, tzinfo=tz)
        for i in range(2):
            make_snapshot(captured_at=t, leito=f"L-{i:02d}")

        DailyAdmissionCount.objects.create(date=target, count=5)
        DailyDischargeCount.objects.create(date=target, count=1)
        DailyDeathCount.objects.create(date=target, count=0)

        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        series = response.context["flow_series"]

        # Find today's entry
        today_row = [r for r in series if r["date"] == target]
        assert len(today_row) == 1
        row = today_row[0]
        assert row["adc"] == 2.0
        assert row["admissions"] == 5
        assert row["discharges"] == 1
        assert row["deaths"] == 0
        assert row["net_flow"] == 4  # 5 - 1 - 0

    def test_empty_window_days_give_zero_flow(
        self, admin_client
    ):
        """Window without data has flow_series with zeros and adc=None."""
        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        series = response.context["flow_series"]
        # Should have 30 entries, all with admissions=0, discharges=0, deaths=0
        assert len(series) == 30
        for row in series:
            assert row["admissions"] == 0
            assert row["discharges"] == 0
            assert row["deaths"] == 0
            assert row["net_flow"] == 0
            # ADC is None because no snapshot exists
            assert row["adc"] is None


@pytest.mark.django_db
class TestHospitalFlowSidebar:
    """Sidebar entry for Fluxo Hospitalar."""

    def test_sidebar_includes_fluxo_link(self, admin_client):
        """Page renders with 'Fluxo Hospitalar' in the sidebar."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Fluxo Hospitalar" in content
        assert "/census/fluxo/" in content or "fluxo" in content
