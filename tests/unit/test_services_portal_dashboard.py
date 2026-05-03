"""Slice DRD-S1: Dashboard with real DB queries.
Slice IRMD-S6: Ingestion metric cards on dashboard.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.discharges.models import DailyDischargeCount
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
        assert ctx["stats"]["altas_hoje"] == 0
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

    def test_dashboard_shows_discharges_today(self, admin_client):
        """Dashboard counts admissions discharged TODAY only, not last 24h."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A",
        )
        now = timezone.now()
        today = timezone.localdate()

        # Discharged today at 10:00
        today_morning = timezone.make_aware(
            datetime(today.year, today.month, today.day, 10, 0, 0),
        )
        Admission.objects.create(
            patient=patient, source_admission_key="ADM1", source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=today_morning,
        )
        # Discharged yesterday at 23:00 (within last 24h but NOT today)
        yesterday = today - timedelta(days=1)
        yesterday_night = timezone.make_aware(
            datetime(yesterday.year, yesterday.month, yesterday.day, 23, 0, 0),
        )
        Admission.objects.create(
            patient=patient, source_admission_key="ADM2", source_system="tasy",
            admission_date=now - timedelta(days=10),
            discharge_date=yesterday_night,
        )
        # Not discharged yet
        Admission.objects.create(
            patient=patient, source_admission_key="ADM3", source_system="tasy",
            admission_date=now - timedelta(days=2),
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["altas_hoje"] == 1  # only today

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

    def test_dashboard_discharge_card_links_to_chart(self, admin_client):
        """The discharge stat card is clickable and links to /painel/altas/."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        chart_url = reverse("services_portal:discharge_chart")
        assert chart_url in content
        assert '<a href="' in content


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


@pytest.mark.django_db
class TestDischargeChartView:
    """Tests for /painel/altas/ discharge chart page."""

    def _create_counts(self, days: int, start_count: int = 5):
        """Helper: create DailyDischargeCount entries for last N days."""
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            DailyDischargeCount.objects.create(date=day, count=start_count + i)

    def test_chart_requires_authentication(self, client):
        """Anonymous users are redirected to login."""
        url = reverse("services_portal:discharge_chart")
        response = client.get(url)
        assert response.status_code == 302

    def test_chart_accessible_when_authenticated(self, admin_client):
        """Authenticated users can access the chart page."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_chart_default_90_days(self, admin_client):
        """Chart shows data for last 90 days by default."""
        self._create_counts(120)  # more than 90
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 90
        today_str = timezone.localdate().strftime("%d/%m/%Y")
        assert today_str not in chart_data["labels"]

    def test_chart_respects_dias_parameter(self, admin_client):
        """?dias=30 shows only last 30 days."""
        self._create_counts(60)
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 30

    def test_chart_invalid_dias_falls_back_to_90(self, admin_client):
        """Invalid ?dias=abc falls back to default 90."""
        self._create_counts(100)
        url = reverse("services_portal:discharge_chart") + "?dias=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 90

    def test_chart_context_has_all_ma_keys(self, admin_client):
        """Context contains labels, counts, sma7, ema7, sma30."""
        self._create_counts(35)
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "labels" in chart_data
        assert "counts" in chart_data
        assert "sma7" in chart_data
        assert "ema7" in chart_data
        assert "sma30" in chart_data
        n = len(chart_data["labels"])
        assert len(chart_data["counts"]) == n
        assert len(chart_data["sma7"]) == n
        assert len(chart_data["ema7"]) == n
        assert len(chart_data["sma30"]) == n

    def test_sma7_is_none_for_first_six_days(self, admin_client):
        """SMA-7 is None for indices 0-5, value from index 6."""
        self._create_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        assert sma7[0] is None
        assert sma7[5] is None
        assert sma7[6] is not None

    def test_ema7_is_none_for_first_six_days(self, admin_client):
        """EMA-7 is None for indices 0-5 (seeded at index 6 with SMA)."""
        self._create_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        ema7 = response.context["chart_data"]["ema7"]
        assert ema7[0] is None
        assert ema7[5] is None
        assert ema7[6] is not None

    def test_ema7_matches_sma7_at_seed_position(self, admin_client):
        """At position 6 (index 6), EMA-7 seed equals SMA-7 of first 7 values."""
        self._create_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        ema7 = response.context["chart_data"]["ema7"]
        assert sma7[6] == ema7[6]  # seed position
        # EMA is defined for all positions >= 6 (no additional None gaps)
        for i in range(7, 15):
            assert ema7[i] is not None
            assert isinstance(ema7[i], float)

    def test_ema7_reacts_faster_than_sma7_to_changes(self, admin_client):
        """EMA-7 gives more weight to recent values than SMA-7."""
        # Create constant counts for 10 days then a spike
        today = timezone.localdate()
        for i in range(15):
            day = today - timedelta(days=15 - i)
            count = 5 if i < 12 else 20  # spike at day 12 (index 11)
            DailyDischargeCount.objects.create(date=day, count=count)

        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        ema7 = response.context["chart_data"]["ema7"]
        # After spike, EMA should be higher than SMA
        assert ema7[13] is not None
        assert sma7[13] is not None
        assert ema7[13] > sma7[13]

    def test_sma30_is_none_for_first_29_days(self, admin_client):
        """SMA-30 is None for indices 0-28, value from index 29."""
        self._create_counts(35)
        url = reverse("services_portal:discharge_chart") + "?dias=35"
        response = admin_client.get(url)
        sma30 = response.context["chart_data"]["sma30"]
        assert sma30[0] is None
        assert sma30[28] is None
        assert sma30[29] is not None

    def test_chart_handles_empty_data(self, admin_client):
        """Page renders without error when no DailyDischargeCount exists."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == []
        assert chart_data["counts"] == []

    # ── DWI-S1: Weekend highlight tests ──────────────────────────────

    def test_chart_context_has_weekend_flags(self, admin_client):
        """Context contains weekend_flags aligned with labels and counts."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "weekend_flags" in chart_data
        n = len(chart_data["labels"])
        assert len(chart_data["weekend_flags"]) == n
        assert len(chart_data["weekend_flags"]) == len(chart_data["counts"])
        # All values should be booleans
        assert all(isinstance(f, bool) for f in chart_data["weekend_flags"])

    def test_weekend_flags_correct_for_known_dates(self, admin_client):
        """Weekend flags are True for Saturday/Sunday, False for Mon-Fri."""
        today = timezone.localdate()
        # Create entries for 8 days before today (oldest first after reverse):
        # today=Sunday => sat,sun,mon,tue,wed,thu,fri,sat
        for i in range(8, 0, -1):
            day = today - timedelta(days=i)
            DailyDischargeCount.objects.create(date=day, count=5)

        url = reverse("services_portal:discharge_chart") + "?dias=8"
        response = admin_client.get(url)
        labels = response.context["chart_data"]["labels"]
        flags = response.context["chart_data"]["weekend_flags"]

        for label, flag in zip(labels, flags, strict=True):
            d = datetime.strptime(label, "%d/%m/%Y").date()
            is_weekend = d.weekday() >= 5  # 5=Saturday, 6=Sunday
            assert flag == is_weekend, (
                f"{label} weekday={d.weekday()} flag={flag}"
            )

    def test_page_html_uses_weekend_flags_for_coloring(self, admin_client):
        """HTML/JS uses weekend_flags for per-bar coloring."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        content = response.content.decode()
        # JSON data emitted by json_script includes weekend_flags
        assert '"weekend_flags"' in content
        # JS code must reference rawData.weekend_flags for per-bar colors
        assert "weekend_flags" in content
        # Updated legend references weekend colors
        assert any(
            term in content
            for term in ["Sábado", "Domingo", "sábado", "domingo",
                         "fim de semana", "dia útil"]
        )

    # ── DWI-S2: Weekday average chart tests ─────────────────────────

    def test_chart_context_has_weekday_avg(self, admin_client):
        """Context contains weekday_avg with labels, values, counts."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert "labels" in wa
        assert "values" in wa
        assert "counts" in wa

    def test_weekday_avg_labels_are_fixed_order(self, admin_client):
        """Weekday avg labels are in fixed Seg..Dom order regardless of data."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        assert wa["labels"] == [
            "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"
        ]

    def test_weekday_avg_values_and_counts_are_length_7(self, admin_client):
        """Weekday avg values and counts are length 7."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        assert len(wa["values"]) == 7
        assert len(wa["counts"]) == 7
        assert all(isinstance(v, float) for v in wa["values"])
        assert all(v >= 0 for v in wa["values"])

    def test_weekday_avg_correct_for_deterministic_fixture(self, admin_client):
        """Weekday averages are correctly computed for known data.

        Uses fixed 2024-01-01 (Mon) through 2024-01-14 dates with
        known counts. Test runs with ?dias=365 so all entries are
        included.
        """
        # 2024-01-01 is Monday
        mon1 = date(2024, 1, 1)  # Mon
        mon2 = date(2024, 1, 8)  # Mon
        tue1 = date(2024, 1, 2)  # Tue
        tue2 = date(2024, 1, 9)  # Tue
        wed1 = date(2024, 1, 3)  # Wed
        thu1 = date(2024, 1, 4)  # Thu
        fri1 = date(2024, 1, 5)  # Fri
        sat1 = date(2024, 1, 6)  # Sat
        # No Sunday entry (test zero/empty bucket)

        DailyDischargeCount.objects.create(date=mon1, count=10)
        DailyDischargeCount.objects.create(date=mon2, count=20)  # avg=15
        DailyDischargeCount.objects.create(date=tue1, count=5)
        DailyDischargeCount.objects.create(date=tue2, count=15)  # avg=10
        DailyDischargeCount.objects.create(date=wed1, count=8)   # avg=8
        DailyDischargeCount.objects.create(date=thu1, count=12)  # avg=12
        DailyDischargeCount.objects.create(date=fri1, count=2)   # avg=2
        DailyDischargeCount.objects.create(date=sat1, count=4)   # avg=4

        url = reverse("services_portal:discharge_chart") + "?dias=365"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]

        # Seg  Ter  Qua  Qui  Sex  Sáb  Dom
        assert wa["values"][0] == 15.0
        assert wa["values"][1] == 10.0
        assert wa["values"][2] == 8.0
        assert wa["values"][3] == 12.0
        assert wa["values"][4] == 2.0
        assert wa["values"][5] == 4.0
        assert wa["values"][6] == 0.0  # no Sunday data

        assert wa["counts"] == [2, 2, 1, 1, 1, 1, 0]

    def test_page_html_has_weekday_average_chart_canvas(self, admin_client):
        """HTML contains canvas#weekdayAverageChart for the second chart."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        content = response.content.decode()
        assert "weekdayAverageChart" in content

    def test_weekday_avg_zero_when_no_data(self, admin_client):
        """Weekday avg all zero when there are no discharge entries."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert wa["values"] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        assert wa["counts"] == [0, 0, 0, 0, 0, 0, 0]
        assert wa["has_data"] is False

    # ── DWI-S3: Hardening de estados vazios / esparsos ─────────────

    def test_empty_data_hides_weekday_chart_card(self, admin_client):
        """When no DailyDischargeCount exists, weekday chart card is hidden."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # The second canvas should NOT be present when has_data=False
        assert '<canvas id="weekdayAverageChart"' not in content
        # But the json_script with weekday-avg-data still exists
        assert "weekday-avg-data" in content

    def test_short_period_missing_weekdays_no_break(self, admin_client):
        """Short period (5 days Mon-Fri) without weekend entries still renders."""
        # Create only Monday-Friday entries (no weekend)
        mon = date(2024, 2, 5)  # Monday
        for i in range(5):
            day = mon + timedelta(days=i)
            DailyDischargeCount.objects.create(date=day, count=3 + i)

        url = reverse("services_portal:discharge_chart") + "?dias=5"
        response = admin_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()

        # Weekday chart canvas IS present (has_data=True: Mon-Fri have counts)
        assert "weekdayAverageChart" in content

        # Weekend buckets (Sáb=5, Dom=6) should have zero avg and zero counts
        wa = response.context["weekday_avg"]
        assert wa["values"][5] == 0.0  # Sáb
        assert wa["values"][6] == 0.0  # Dom
        assert wa["counts"][5] == 0
        assert wa["counts"][6] == 0
        assert wa["has_data"] is True  # at least one weekday has data

    def test_weekday_avg_counts_coherent_with_period(self, admin_client):
        """Weekday avg counts reflect the actual number of observations in period."""
        # 2024-03-04 is Monday
        mon = date(2024, 3, 4)
        # Create 14 days: 2 full weeks Mon-Sun
        for i in range(14):
            day = mon + timedelta(days=i)
            DailyDischargeCount.objects.create(date=day, count=5)

        url = reverse("services_portal:discharge_chart") + "?dias=14"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        # Each weekday appears exactly twice in 14 days
        assert wa["counts"] == [2, 2, 2, 2, 2, 2, 2]
        # Each avg should be 5.0 (all entries have count=5)
        assert all(v == 5.0 for v in wa["values"])
