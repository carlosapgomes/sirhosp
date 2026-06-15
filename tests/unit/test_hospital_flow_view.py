"""Tests for hospital_flow_view (Slice S2)."""

from __future__ import annotations

import json
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


@pytest.mark.django_db
class TestHospitalFlowViewChartData:
    """chart_data context tests for Chart.js (Slice S3)."""

    def test_context_has_chart_data(self, admin_client):
        """Context always has chart_data dict with expected keys."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert "chart_data" in response.context
        cd = response.context["chart_data"]
        assert "labels" in cd
        assert "admissions" in cd
        assert "discharges_deaths" in cd
        assert "adc" in cd

    def test_chart_data_arrays_have_same_length(self, admin_client):
        """All chart_data arrays have the same length."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        cd = response.context["chart_data"]
        n = len(cd["labels"])
        assert len(cd["admissions"]) == n
        assert len(cd["discharges_deaths"]) == n
        assert len(cd["adc"]) == n

    def test_chart_data_is_json_serializable(self, admin_client):
        """chart_data is serializable via json.dumps (no exception)."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        cd = response.context["chart_data"]
        dumped = json.dumps(cd, default=str)
        assert isinstance(dumped, str)

    def test_chart_data_without_snapshot_adc_is_none(self, admin_client):
        """Days without census snapshot have adc=None in chart_data."""
        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        cd = response.context["chart_data"]
        for val in cd["adc"]:
            assert val is None

    def test_chart_data_with_snapshot_reflects_data(
        self, admin_client, make_snapshot
    ):
        """When data exists, chart_data reflects the computed values."""
        tz = timezone.get_current_timezone()
        target = date.today()

        t = datetime(target.year, target.month, target.day, 8, 0, tzinfo=tz)
        for i in range(2):
            make_snapshot(captured_at=t, leito=f"L-{i:02d}")

        DailyAdmissionCount.objects.create(date=target, count=5)
        DailyDischargeCount.objects.create(date=target, count=1)
        DailyDeathCount.objects.create(date=target, count=0)

        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        cd = response.context["chart_data"]

        idx = cd["labels"].index(target.isoformat())
        assert cd["admissions"][idx] == 5
        assert cd["discharges_deaths"][idx] == 1  # 1 discharge + 0 deaths
        assert cd["adc"][idx] == 2.0


@pytest.mark.django_db
class TestHospitalFlowViewSector:
    """Sector drill-down tests (Slice S4)."""

    def test_sector_not_provided_default_empty(self, admin_client):
        """Without ?sector= param, selected_sector is empty string."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert response.context["selected_sector"] == ""

    def test_sector_provided_in_context(self, admin_client):
        """With ?sector=X, selected_sector is 'X'."""
        url = reverse("census:hospital_flow") + "?sector=UTI+GERAL"
        response = admin_client.get(url)
        assert response.context["selected_sector"] == "UTI GERAL"

    def test_sectors_list_in_context(self, admin_client):
        """Context has 'sectors' list."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert "sectors" in response.context
        assert isinstance(response.context["sectors"], list)

    def test_sectors_contains_distinct_sectors(self, admin_client, make_snapshot):
        """sectors list contains distinct sector names when snapshots exist."""
        tz = timezone.get_current_timezone()
        t = datetime(date.today().year, date.today().month, date.today().day, 8, 0, tzinfo=tz)

        make_snapshot(captured_at=t, leito="L-01", setor="UTI GERAL")
        make_snapshot(captured_at=t, leito="L-02", setor="ENFERMARIA")

        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        sectors = response.context["sectors"]
        assert "UTI GERAL" in sectors
        assert "ENFERMARIA" in sectors
        assert sectors == sorted(sectors)  # must be ordered

    def test_sectors_has_no_duplicates(self, admin_client, make_snapshot):
        """sectors list has no duplicate names."""
        tz = timezone.get_current_timezone()
        t = datetime(date.today().year, date.today().month, date.today().day, 8, 0, tzinfo=tz)

        make_snapshot(captured_at=t, leito="L-01", setor="UTI GERAL")
        make_snapshot(captured_at=t, leito="L-02", setor="UTI GERAL")

        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        sectors = response.context["sectors"]
        assert len(sectors) == 1
        assert sectors == ["UTI GERAL"]

    def test_flow_with_sector_filter_stock_only(self, admin_client, make_snapshot):
        """Sector filter affects ADC (stock) but flow remains hospital-total."""
        tz = timezone.get_current_timezone()
        target = date.today()
        t = datetime(target.year, target.month, target.day, 8, 0, tzinfo=tz)

        # 1 occupied in UTI GERAL, 2 in ENFERMARIA
        make_snapshot(captured_at=t, leito="L-01", setor="UTI GERAL")
        make_snapshot(captured_at=t, leito="L-02", setor="ENFERMARIA")
        make_snapshot(captured_at=t, leito="L-03", setor="ENFERMARIA")

        DailyAdmissionCount.objects.create(date=target, count=5)
        DailyDischargeCount.objects.create(date=target, count=1)
        DailyDeathCount.objects.create(date=target, count=0)

        # Total (no sector): ADC = 3.0 (all occupied)
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        series_all = response.context["flow_series"]
        row_all = [r for r in series_all if r["date"] == target][0]
        assert row_all["adc"] == 3.0
        assert row_all["admissions"] == 5

        # Filtered (sector=UTI GERAL): ADC = 1.0, flow still 5/1/0
        url = reverse("census:hospital_flow") + "?sector=UTI+GERAL"
        response = admin_client.get(url)
        series_uti = response.context["flow_series"]
        row_uti = [r for r in series_uti if r["date"] == target][0]
        assert row_uti["adc"] == 1.0
        assert row_uti["admissions"] == 5  # flow unchanged
        assert row_uti["discharges"] == 1  # flow unchanged
        assert row_uti["deaths"] == 0  # flow unchanged

    def test_window_preserved_with_sector(self, admin_client):
        """Sector selector preserves window parameter."""
        url = reverse("census:hospital_flow") + "?window=30&sector=UTI+GERAL"
        response = admin_client.get(url)
        assert response.context["window"] == 30
        assert response.context["selected_sector"] == "UTI GERAL"


@pytest.mark.django_db
class TestHospitalFlowViewResidualQC:
    """Residual quality-control panel tests (Slice S5)."""

    def test_admin_has_residual_series_in_context(self, admin_client):
        """Admin sees residual_series in context."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert "residual_series" in response.context

    def test_admin_has_residual_quality_in_context(self, admin_client):
        """Admin sees residual_quality in context."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        assert "residual_quality" in response.context

    def test_non_admin_has_no_residual_series(self, client, django_user_model):
        """Non-admin context does NOT have residual_series."""
        user = django_user_model.objects.create_user(
            username="regular", password="pass", is_staff=False
        )
        client.force_login(user)
        url = reverse("census:hospital_flow")
        response = client.get(url)
        assert "residual_series" not in response.context

    def test_non_admin_has_no_residual_quality(self, client, django_user_model):
        """Non-admin context does NOT have residual_quality."""
        user = django_user_model.objects.create_user(
            username="regular2", password="pass", is_staff=False
        )
        client.force_login(user)
        url = reverse("census:hospital_flow")
        response = client.get(url)
        assert "residual_quality" not in response.context

    def test_admin_template_renders_qc_section(self, admin_client):
        """Admin sees the QC section title in rendered HTML."""
        url = reverse("census:hospital_flow")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Indicador de qualidade" in content

    def test_non_admin_template_not_render_qc_section(self, client, django_user_model):
        """Non-admin does NOT see QC section in rendered HTML."""
        user = django_user_model.objects.create_user(
            username="regular3", password="pass", is_staff=False
        )
        client.force_login(user)
        url = reverse("census:hospital_flow")
        response = client.get(url)
        content = response.content.decode()
        assert "Indicador de qualidade" not in content

    def test_residual_pct_calculation(self, admin_client, make_snapshot):
        """residual_series has correct residual_pct for synthetic data.

        Two consecutive days:
          Day 1: ADC=6.0 (6 occupied), adm=10, dis=0, deaths=0
                 → net_flow=10, residual=None
          Day 2: ADC=6.0 (6 occupied), adm=0,  dis=3, deaths=3
                 → net_flow=-6, delta_adc=0, residual=6
                 → residual_pct = abs(6)/6.0*100 = 100.0
        """
        tz = timezone.get_current_timezone()
        today = date.today()
        day1 = today - __import__("datetime").timedelta(days=1)

        t1 = datetime(day1.year, day1.month, day1.day, 8, 0, tzinfo=tz)
        t2 = datetime(today.year, today.month, today.day, 8, 0, tzinfo=tz)

        # Day 1: 6 occupied, 10 admissions
        for i in range(6):
            make_snapshot(captured_at=t1, leito=f"L-D1-{i:03d}")
        DailyAdmissionCount.objects.create(date=day1, count=10)

        # Day 2: 6 occupied, 0 admissions, 3 discharges, 3 deaths
        for i in range(6):
            make_snapshot(captured_at=t2, leito=f"L-D2-{i:03d}")
        DailyAdmissionCount.objects.create(date=today, count=0)
        DailyDischargeCount.objects.create(date=today, count=3)
        DailyDeathCount.objects.create(date=today, count=3)

        url = reverse("census:hospital_flow") + "?window=5"
        response = admin_client.get(url)
        series = response.context["residual_series"]

        # Find day2 entry
        day2_entry = [r for r in series if r["date"] == today]
        assert len(day2_entry) == 1
        row = day2_entry[0]
        assert row["residual"] == 6
        assert row["residual_pct"] == 100.0

    def test_residual_pct_none_when_no_data(self, admin_client):
        """Days without data (adc=None, residual=None) yield residual_pct=None."""
        url = reverse("census:hospital_flow") + "?window=30"
        response = admin_client.get(url)
        series = response.context["residual_series"]
        assert len(series) == 30
        for row in series:
            assert row["residual_pct"] is None
