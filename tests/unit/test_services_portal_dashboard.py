"""Slice DRD-S1: Dashboard with real DB queries.
Slice IRMD-S6: Ingestion metric cards on dashboard.
Slice RPSA-S8: separate effective-exit and medical-summary cards.
Slice SCPED-S2: captured-exit day card and per-date evidence list.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.admissions.models import DailyAdmissionCount
from apps.census.models import BedStatus, CensusSnapshot
from apps.deaths.models import DailyDeathCount
from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Patient,
)

BAHIA = ZoneInfo("America/Bahia")


def _bahia(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Pin a wall-clock datetime to ``America/Bahia`` explicitly."""
    return datetime(year, month, day, hour, minute, tzinfo=BAHIA)


def _seed_captured_exit(
    prontuario: str,
    when: datetime,
    status: str = RECONCILIATION_STATUS_PENDING,
) -> DischargeRecord:
    """Create one discharge evidence whose effective exit is ``when``.

    SCPED-S2: the dashboard day card and the per-date list count
    ``DischargeRecord.saida_em`` directly — never admission
    reconciliation or the legacy daily aggregate.
    """
    return DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=f"INT-{prontuario}",
        saida_em=when,
        reconciliation_status=status,
    )


def _seed_summary(prontuario: str, when: datetime) -> None:
    """Create one medical discharge summary registered at ``when``."""
    DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=f"INT-{prontuario}",
        alta_em=when,
    )


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
        assert ctx["stats"]["saidas_hoje"] == 0
        # SCPED-S2: summary and canonical-aggregate keys no longer feed
        # any dashboard card (they moved to the protected quality surface).
        assert "sumarios_hoje" not in ctx["stats"]
        assert "altas" not in ctx["stats"]
        assert "altas_date" not in ctx["stats"]
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

    def test_dashboard_exit_card_counts_today_by_saida_em(
        self, admin_client,
    ):
        """R1: the day card counts saida_em on the current local date.

        Five captured exits today and three yesterday show exactly five on
        the card — no last-24h window and no stale canonical aggregate.
        """
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        DailyDischargeCount.objects.create(date=today, count=43)  # stale
        for i in range(5):
            _seed_captured_exit(
                f"T{i}", _bahia(today.year, today.month, today.day, 8 + i, 0)
            )
        for i in range(3):
            _seed_captured_exit(
                f"Y{i}",
                _bahia(yesterday.year, yesterday.month, yesterday.day, 20 + i, 0),
            )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["stats"]["saidas_hoje"] == 5
        # The legacy aggregate feeds no discharge card anymore.
        assert "altas" not in ctx["stats"]
        assert "altas_date" not in ctx["stats"]

    def test_dashboard_exit_card_includes_unreconciled_evidence(
        self, admin_client,
    ):
        """R1: pending/ambiguous/conflict saida_em rows still count today."""
        today = timezone.localdate()
        statuses = [
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_CONFLICT,
            RECONCILIATION_STATUS_RECONCILED,
        ]
        for i, status in enumerate(statuses):
            _seed_captured_exit(
                f"ST{i}",
                _bahia(today.year, today.month, today.day, 9 + i, 0),
                status=status,
            )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["saidas_hoje"] == 4

    def test_dashboard_exit_card_zero_when_no_exit_was_captured_today(
        self, admin_client,
    ):
        """R2: alta_em-only rows never enter the exit card; empty today → 0."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        _seed_summary(
            "SUM1", _bahia(today.year, today.month, today.day, 9, 0)
        )
        _seed_summary(
            "SUM2", _bahia(today.year, today.month, today.day, 10, 0)
        )
        _seed_captured_exit(
            "Y1",
            _bahia(yesterday.year, yesterday.month, yesterday.day, 20, 0),
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["saidas_hoje"] == 0

    def test_dashboard_shows_no_second_primary_discharge_card(
        self, admin_client,
    ):
        """R3: summaries and canonical comparisons stay off the dashboard."""
        today = timezone.localdate()
        _seed_captured_exit(
            "E1", _bahia(today.year, today.month, today.day, 9, 0)
        )
        _seed_summary(
            "SUM1", _bahia(today.year, today.month, today.day, 9, 30)
        )
        DailyDischargeCount.objects.create(date=today, count=43)  # stale

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        ctx = response.context
        assert ctx["stats"]["saidas_hoje"] == 1
        assert "sumarios_hoje" not in ctx["stats"]
        assert "Sumários de alta registrados" not in content
        chart_url = reverse("services_portal:discharge_chart")
        # Exactly one primary discharge card navigates to the exit chart.
        assert content.count(f'href="{chart_url}"') == 1
        list_href = f'href="{reverse("services_portal:discharge_list")}"'
        assert list_href not in content

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
        assert ctx["coleta"]["ultima_varredura"] == (
            timezone.localtime(now).strftime("%d/%m/%Y %H:%M")
        )

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

    def test_dashboard_discharge_area_links_only_to_captured_exit_chart(
        self, admin_client,
    ):
        """The single exit card is clickable and links to /painel/altas/."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        chart_url = reverse("services_portal:discharge_chart")
        assert f'href="{chart_url}"' in content
        assert '<a href="' in content


@pytest.mark.django_db
class TestDischargeListView:
    """SCPED-S2: /altas/ per-date list follows the captured-exit metric.

    R4/R5: the list queries ``DischargeRecord.saida_em`` on the explicit
    ``America/Bahia`` local date and never reads ``DailyDischargeCount``
    (neither its count, its ``records`` link nor its ``raw_data``).
    """

    @staticmethod
    def _seed_exit_on(
        day: date,
        prontuario: str,
        hour: int = 10,
        status: str = RECONCILIATION_STATUS_PENDING,
    ) -> DischargeRecord:
        return _seed_captured_exit(
            prontuario,
            _bahia(day.year, day.month, day.day, hour, 0),
            status=status,
        )

    def test_list_requires_authentication(self, client):
        """Anonymous users are redirected to login (R6 preserved)."""
        url = reverse("services_portal:discharge_list")
        response = client.get(url)
        assert response.status_code == 302

    def test_list_defaults_to_current_bahia_date(self, admin_client):
        """Without ?date= the list opens the current local date."""
        url = reverse("services_portal:discharge_list")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["date"] == timezone.localdate()

    def test_list_invalid_date_falls_back_to_current_date(self, admin_client):
        """A malformed ?date= falls back to the current local date."""
        url = reverse("services_portal:discharge_list") + "?date=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["date"] == timezone.localdate()

    def test_list_counts_captured_exits_on_selected_date_only(
        self, admin_client,
    ):
        """R4: rows and count come from saida_em on the selected date."""
        d = timezone.localdate() - timedelta(days=1)
        expected: list[str] = []
        statuses = [
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_CONFLICT,
            RECONCILIATION_STATUS_RECONCILED,
        ]
        for i, status in enumerate(statuses):
            key = f"D{i}"
            self._seed_exit_on(d, key, hour=8 + i, status=status)
            expected.append(key)
        # A captured exit on the previous day stays out.
        self._seed_exit_on(d - timedelta(days=1), "PREV", hour=9)
        # A captured exit on the following day stays out.
        self._seed_exit_on(d + timedelta(days=1), "NEXT", hour=9)
        # A medical summary on D without saida_em stays out.
        _seed_summary("SUM1", _bahia(d.year, d.month, d.day, 9, 30))

        url = reverse("services_portal:discharge_list") + (
            f"?date={d.isoformat()}"
        )
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["date"] == d
        assert ctx["count"] == 4
        prontuarios = [r["prontuario"] for r in ctx["records"]]
        assert sorted(prontuarios) == sorted(expected)

    def test_list_ignores_legacy_daily_count_records_and_raw_data(
        self, admin_client,
    ):
        """R5: no dependency on DailyDischargeCount count/records/raw_data."""
        d = timezone.localdate() - timedelta(days=1)
        legacy = DailyDischargeCount.objects.create(
            date=d,
            count=99,
            raw_data=[{"prontuario": "FAKE1", "nome": "Fake row"}],
        )
        # Legacy-linked evidence whose exit happened on another date.
        DischargeRecord.objects.create(
            prontuario="LEG1",
            data_internacao="INT-LEG1",
            daily_count=legacy,
            saida_em=_bahia(
                (d - timedelta(days=1)).year,
                (d - timedelta(days=1)).month,
                (d - timedelta(days=1)).day,
                9,
                0,
            ),
        )
        for key in ("EVID1", "EVID2", "EVID3"):
            self._seed_exit_on(d, key, hour=10)

        url = reverse("services_portal:discharge_list") + (
            f"?date={d.isoformat()}"
        )
        response = admin_client.get(url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx["count"] == 3
        prontuarios = [r["prontuario"] for r in ctx["records"]]
        assert sorted(prontuarios) == ["EVID1", "EVID2", "EVID3"]
        content = response.content.decode()
        assert "FAKE1" not in content
        assert "LEG1" not in content


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
    """Tests for /painel/altas/ discharge chart page.

    SCPED-S1: the single management series counts ``DischargeRecord.saida_em``
    over a consecutive calendar axis ending yesterday; days without captured
    exits stay on the axis as zero and feed the averages.  Tests seed
    synthetic discharge evidence only — the chart no longer reads
    ``DailyDischargeCount`` rows.
    """

    def _seed_discharge(
        self,
        when: datetime,
        especialidade: str = "",
        status: str = RECONCILIATION_STATUS_PENDING,
    ) -> None:
        """Create one synthetic discharge record exiting at ``when`` (Bahia).

        Prontuario and data_internacao stay short synthetic identifiers so
        the unique contract (prontuario, data_internacao) never collides and
        the column width is respected.
        """
        self._seed_seq = getattr(self, "_seed_seq", 0) + 1
        prontuario = f"SCPED{self._seed_seq}"
        DischargeRecord.objects.create(
            prontuario=prontuario,
            data_internacao=f"INT-{prontuario}",
            saida_em=when,
            especialidade=especialidade,
            reconciliation_status=status,
        )

    def _seed_exit_counts(self, days: int, start_count: int = 1) -> None:
        """Seed ``days`` consecutive days (offsets ``days..1``) with exits.

        The oldest day gets ``start_count`` exits and each following day one
        more, so the chronological chart series equals ``[start_count..]``.
        """
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            for _n in range(start_count + i):
                self._seed_discharge(
                    _bahia(day.year, day.month, day.day, 10, 0),
                )

    @staticmethod
    def _axis_labels(days: int) -> list[str]:
        """Expected ``%d/%m/%Y`` labels for the last ``days`` calendar days."""
        today = timezone.localdate()
        return [
            (today - timedelta(days=days - i)).strftime("%d/%m/%Y")
            for i in range(days)
        ]

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

    def test_chart_default_90_calendar_days_through_yesterday(self, admin_client):
        """Default axis has exactly 90 consecutive days ending yesterday."""
        self._seed_exit_counts(120)
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == self._axis_labels(90)
        assert len(chart_data["counts"]) == 90
        assert chart_data["has_data"] is True
        today_str = timezone.localdate().strftime("%d/%m/%Y")
        assert today_str not in chart_data["labels"]

    def test_chart_respects_dias_parameter_exact_window(self, admin_client):
        """?dias=30 shows exactly the 30 consecutive days ending yesterday."""
        self._seed_exit_counts(60)
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == self._axis_labels(30)

    def test_chart_invalid_dias_falls_back_to_90(self, admin_client):
        """Invalid ?dias=abc falls back to the default 90-day axis."""
        self._seed_exit_counts(100)
        url = reverse("services_portal:discharge_chart") + "?dias=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == self._axis_labels(90)

    def test_day_without_exit_stays_on_axis_with_zero(self, admin_client):
        """R3: a calendar day without ``saida_em`` stays as zero on the axis."""
        today = timezone.localdate()
        for offset in range(30, 0, -1):  # oldest -> yesterday
            if offset != 10:  # leave one axis day without exits
                day = today - timedelta(days=offset)
                self._seed_discharge(
                    _bahia(day.year, day.month, day.day, 12, 0),
                )
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) == 30
        assert chart_data["counts"] == [
            0 if offset == 10 else 1 for offset in range(30, 0, -1)
        ]
        # Averages consume the same calendar-complete series.
        assert len(chart_data["sma7"]) == 30
        assert len(chart_data["ema7"]) == 30
        assert len(chart_data["sma30"]) == 30

    def test_single_series_counts_only_captured_exits(self, admin_client):
        """R1: summaries and stale aggregates never enter the exit series."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        two_days = today - timedelta(days=2)
        three_days = today - timedelta(days=3)
        # Captured exit yesterday.
        self._seed_discharge(
            _bahia(yesterday.year, yesterday.month, yesterday.day, 18, 0),
        )
        # Medical summary (alta_em only) on the same day must not count.
        DischargeRecord.objects.create(
            prontuario="S1",
            data_internacao="INT-S1",
            alta_em=_bahia(yesterday.year, yesterday.month, yesterday.day, 14, 0),
        )
        # Stale canonical aggregate that the chart no longer reads.
        DailyDischargeCount.objects.create(date=yesterday, count=42)
        # Exit outside the requested two-day window must not count.
        self._seed_discharge(
            _bahia(three_days.year, three_days.month, three_days.day, 9, 0),
        )

        url = reverse("services_portal:discharge_chart") + "?dias=2"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == [
            two_days.strftime("%d/%m/%Y"),
            yesterday.strftime("%d/%m/%Y"),
        ]
        assert chart_data["counts"] == [0, 1]
        assert chart_data["has_data"] is True
        assert "summary_counts" not in chart_data
        assert "summary_series_label" not in chart_data

    def test_pending_reconciliation_exits_are_counted(self, admin_client):
        """R2: every saida_em counts regardless of reconciliation_status."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        statuses = [
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_CONFLICT,
            RECONCILIATION_STATUS_RECONCILED,
        ]
        for i, status in enumerate(statuses):
            self._seed_discharge(
                _bahia(yesterday.year, yesterday.month, yesterday.day, 10 + i, 0),
                status=status,
            )

        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        idx = chart_data["labels"].index(yesterday.strftime("%d/%m/%Y"))
        assert chart_data["counts"][idx] == 4
        assert chart_data["has_data"] is True

    def test_chart_context_has_all_ma_keys(self, admin_client):
        """Context contains labels, counts, sma7, ema7, sma30."""
        self._seed_exit_counts(35)
        url = reverse("services_portal:discharge_chart") + "?dias=35"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        for key in ("labels", "counts", "sma7", "ema7", "sma30"):
            assert key in chart_data
        n = len(chart_data["labels"])
        assert n == 35
        for key in ("counts", "sma7", "ema7", "sma30"):
            assert len(chart_data[key]) == n
        assert chart_data["counts"] == list(range(1, 36))

    def test_sma7_is_none_for_first_six_days(self, admin_client):
        """SMA-7 is None for indices 0-5, value from index 6."""
        self._seed_exit_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        assert sma7[:6] == [None] * 6
        assert sma7[6] == 4.0  # mean(1..7)

    def test_ema7_is_none_for_first_six_days(self, admin_client):
        """EMA-7 is None for indices 0-5 (seeded at index 6 with SMA)."""
        self._seed_exit_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        ema7 = response.context["chart_data"]["ema7"]
        assert ema7[:6] == [None] * 6
        assert ema7[6] is not None
        assert isinstance(ema7[6], float)

    def test_ema7_matches_sma7_at_seed_position(self, admin_client):
        """At index 6 the EMA-7 seed equals the SMA-7 of the first 7 values."""
        self._seed_exit_counts(15)
        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        ema7 = response.context["chart_data"]["ema7"]
        assert sma7[6] == ema7[6]  # seed position
        for i in range(7, 15):
            assert ema7[i] is not None
            assert isinstance(ema7[i], float)

    def test_ema7_reacts_faster_than_sma7_to_changes(self, admin_client):
        """EMA-7 gives more weight to recent values than SMA-7."""
        today = timezone.localdate()
        for i in range(15):  # constant 5, then a spike in the last 3 days
            day = today - timedelta(days=15 - i)
            count = 5 if i < 12 else 20
            for _n in range(count):
                self._seed_discharge(
                    _bahia(day.year, day.month, day.day, 10, 0),
                )

        url = reverse("services_portal:discharge_chart") + "?dias=15"
        response = admin_client.get(url)
        sma7 = response.context["chart_data"]["sma7"]
        ema7 = response.context["chart_data"]["ema7"]
        assert ema7[13] is not None
        assert sma7[13] is not None
        assert ema7[13] > sma7[13]

    def test_sma30_is_none_for_first_29_days(self, admin_client):
        """SMA-30 is None for indices 0-28, value from index 29."""
        self._seed_exit_counts(35)
        url = reverse("services_portal:discharge_chart") + "?dias=35"
        response = admin_client.get(url)
        sma30 = response.context["chart_data"]["sma30"]
        assert sma30[:29] == [None] * 29
        assert sma30[29] == 15.5  # mean(1..30)

    def test_empty_dataset_keeps_full_zero_axis(self, admin_client):
        """No exits still renders the consecutive calendar axis with zeros."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == self._axis_labels(90)
        assert chart_data["counts"] == [0] * 90
        assert chart_data["has_data"] is False

    def test_chart_context_has_weekend_flags_aligned_with_axis(self, admin_client):
        """Weekend flags align with the calendar axis, including zero days."""
        self._seed_exit_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=14"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "weekend_flags" in chart_data
        n = len(chart_data["labels"])
        assert len(chart_data["weekend_flags"]) == n
        assert len(chart_data["weekend_flags"]) == len(chart_data["counts"])
        assert all(isinstance(f, bool) for f in chart_data["weekend_flags"])
        for label, flag in zip(
            chart_data["labels"], chart_data["weekend_flags"], strict=True
        ):
            d = datetime.strptime(label, "%d/%m/%Y").date()
            assert flag == (d.weekday() >= 5), (
                f"{label} weekday={d.weekday()} flag={flag}"
            )

    def test_page_html_uses_weekend_flags_for_coloring(self, admin_client):
        """HTML/JS uses weekend_flags for per-bar coloring."""
        self._seed_exit_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        content = response.content.decode()
        assert '"weekend_flags"' in content
        assert any(
            term in content
            for term in ["Sábado", "Domingo", "sábado", "domingo", "dia útil"]
        )

    def test_chart_context_has_weekday_avg(self, admin_client):
        """Context contains weekday_avg with labels, values, counts."""
        self._seed_exit_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert "labels" in wa
        assert "values" in wa
        assert "counts" in wa

    def test_weekday_avg_labels_are_fixed_order(self, admin_client):
        """Weekday avg labels are in fixed Seg..Dom order regardless of data."""
        self._seed_exit_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        assert wa["labels"] == [
            "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"
        ]

    def test_weekday_avg_values_and_counts_are_length_7(self, admin_client):
        """Weekday avg values and counts are length 7."""
        self._seed_exit_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=7"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        assert len(wa["values"]) == 7
        assert len(wa["counts"]) == 7
        assert all(isinstance(v, float) for v in wa["values"])
        assert all(v >= 0 for v in wa["values"])

    def test_weekday_avg_two_full_weeks(self, admin_client):
        """Two full weeks with 5 exits/day give 5.0 for every weekday."""
        today = timezone.localdate()
        for _offset in range(14, 0, -1):  # each weekday occurs exactly twice
            day = today - timedelta(days=_offset)
            for _n in range(5):
                self._seed_discharge(
                    _bahia(day.year, day.month, day.day, 10, 0),
                )
        url = reverse("services_portal:discharge_chart") + "?dias=14"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        assert wa["values"] == [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        assert wa["counts"] == [2, 2, 2, 2, 2, 2, 2]
        assert wa["has_data"] is True

    def test_weekday_avg_zero_exit_days_participate(self, admin_client):
        """R4: weekend zero-exit days still count as occurrences (weekday avg)."""
        today = timezone.localdate()
        for _offset in range(14, 0, -1):
            day = today - timedelta(days=_offset)
            if day.weekday() < 5:  # only business days receive exits
                for _n in range(5):
                    self._seed_discharge(
                        _bahia(day.year, day.month, day.day, 10, 0),
                    )
        url = reverse("services_portal:discharge_chart") + "?dias=14"
        response = admin_client.get(url)
        wa = response.context["weekday_avg"]
        # Each weekday still occurs twice in the calendar axis.
        assert wa["counts"] == [2, 2, 2, 2, 2, 2, 2]
        assert wa["values"][5] == 0.0  # Sáb: no exits, average stays zero
        assert wa["values"][6] == 0.0  # Dom
        assert wa["values"][:5] == [5.0, 5.0, 5.0, 5.0, 5.0]
        assert wa["has_data"] is True

    def test_weekday_avg_zero_when_no_data(self, admin_client):
        """Weekday avg is all zero when no exit was captured in the period."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert wa["values"] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        assert sum(wa["counts"]) == 90  # the full calendar axis is observed
        assert wa["has_data"] is False

    def test_short_period_missing_weekdays_no_break(self, admin_client):
        """A short period without every weekday still renders cleanly."""
        self._seed_exit_counts(5)
        url = reverse("services_portal:discharge_chart") + "?dias=5"
        response = admin_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        wa = response.context["weekday_avg"]
        assert len(wa["values"]) == 7
        assert sum(wa["counts"]) == 5
        assert wa["has_data"] is True
        assert "weekdayAverageChart" in content

    def test_empty_data_hides_weekday_chart_card(self, admin_client):
        """With no exits, the weekday chart card is hidden."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert '<canvas id="weekdayAverageChart"' not in content
        assert "weekday-avg-data" in content

@pytest.mark.django_db
class TestAdmissionDeathChartViews:
    """ADC-S1: Tests for /painel/admissoes/ and /painel/obitos/ chart pages."""

    # ── Admission chart tests ────────────────────────────────────────

    def _create_admission_counts(self, days: int, start_count: int = 5):
        """Helper: create DailyAdmissionCount entries for last N days."""
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            DailyAdmissionCount.objects.create(date=day, count=start_count + i)

    def _create_death_counts(self, days: int, start_count: int = 5):
        """Helper: create DailyDeathCount entries for last N days."""
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            DailyDeathCount.objects.create(date=day, count=start_count + i)

    def test_admission_chart_requires_authentication(self, client):
        """Anonymous user is redirected to login for admission chart."""
        url = reverse("services_portal:admission_chart")
        response = client.get(url)
        assert response.status_code == 302

    def test_death_chart_requires_authentication(self, client):
        """Anonymous user is redirected to login for death chart."""
        url = reverse("services_portal:death_chart")
        response = client.get(url)
        assert response.status_code == 302

    def test_admission_chart_returns_200_when_authenticated(self, admin_client):
        """Authenticated user can access the admission chart page."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_death_chart_returns_200_when_authenticated(self, admin_client):
        """Authenticated user can access the death chart page."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_admission_chart_context_uses_daily_admission_count(self, admin_client):
        """Admission chart context contains chart_data from DailyAdmissionCount."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context.get("chart_data")
        assert chart_data is not None
        assert "labels" in chart_data
        assert "counts" in chart_data
        assert len(chart_data["labels"]) > 0

    def test_death_chart_context_uses_daily_death_count(self, admin_client):
        """Death chart context contains chart_data from DailyDeathCount."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context.get("chart_data")
        assert chart_data is not None
        assert "labels" in chart_data
        assert "counts" in chart_data
        assert len(chart_data["labels"]) > 0

    def test_admission_chart_respects_dias_parameter(self, admin_client):
        """?dias=30 limits the admission chart to 30 days."""
        self._create_admission_counts(60)
        url = reverse("services_portal:admission_chart") + "?dias=30"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 30

    def test_death_chart_respects_dias_parameter(self, admin_client):
        """?dias=30 limits the death chart to 30 days."""
        self._create_death_counts(60)
        url = reverse("services_portal:death_chart") + "?dias=30"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 30

    def test_admission_chart_invalid_dias_falls_back_to_90(self, admin_client):
        """Invalid ?dias=abc falls back to default 90 for admissions."""
        self._create_admission_counts(100)
        url = reverse("services_portal:admission_chart") + "?dias=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 90

    def test_death_chart_invalid_dias_falls_back_to_90(self, admin_client):
        """Invalid ?dias=abc falls back to default 90 for deaths."""
        self._create_death_counts(100)
        url = reverse("services_portal:death_chart") + "?dias=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 90

    def test_admission_chart_handles_empty_data(self, admin_client):
        """Admission chart renders without error when no data exists."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == []
        assert chart_data["counts"] == []

    def test_death_chart_handles_empty_data(self, admin_client):
        """Death chart renders without error when no data exists."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == []
        assert chart_data["counts"] == []

    def test_admission_chart_context_has_weekday_avg(self, admin_client):
        """Admission chart context contains weekday_avg."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart") + "?dias=7"
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert "labels" in wa
        assert "values" in wa
        assert "counts" in wa

    def test_death_chart_context_has_weekday_avg(self, admin_client):
        """Death chart context contains weekday_avg."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart") + "?dias=7"
        response = admin_client.get(url)
        assert "weekday_avg" in response.context
        wa = response.context["weekday_avg"]
        assert "labels" in wa
        assert "values" in wa
        assert "counts" in wa

    def test_admission_chart_excludes_today(self, admin_client):
        """Admission chart excludes today (in-progress day)."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        today_str = timezone.localdate().strftime("%d/%m/%Y")
        assert today_str not in chart_data["labels"]

    def test_death_chart_excludes_today(self, admin_client):
        """Death chart excludes today (in-progress day)."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        today_str = timezone.localdate().strftime("%d/%m/%Y")
        assert today_str not in chart_data["labels"]

    def test_admission_chart_period_options_in_context(self, admin_client):
        """Admission chart context contains period_options."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        assert response.context.get("period_options") == [30, 60, 90, 180, 365]

    def test_death_chart_period_options_in_context(self, admin_client):
        """Death chart context contains period_options."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        assert response.context.get("period_options") == [30, 60, 90, 180, 365]

    # ── ADC-S2: Canvas and title tests ──────────────────────────────

    def test_admission_chart_has_daily_canvas(self, admin_client):
        """Admission chart HTML includes canvas#dailyChart for daily bars."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="dailyChart"' in content

    def test_death_chart_has_daily_canvas(self, admin_client):
        """Death chart HTML includes canvas#dailyChart for daily bars."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="dailyChart"' in content

    def test_admission_chart_has_weekday_canvas_when_data_exists(self, admin_client):
        """Admission chart includes canvas#weekdayAverageChart when data exists."""
        self._create_admission_counts(14)  # 2 weeks
        url = reverse("services_portal:admission_chart") + "?dias=14"
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="weekdayAverageChart"' in content

    def test_death_chart_has_weekday_canvas_when_data_exists(self, admin_client):
        """Death chart includes canvas#weekdayAverageChart when data exists."""
        self._create_death_counts(14)  # 2 weeks
        url = reverse("services_portal:death_chart") + "?dias=14"
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="weekdayAverageChart"' in content

    def test_admission_chart_empty_hides_weekday_canvas(self, admin_client):
        """Admission chart hides weekdayAverageChart canvas when no data."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="weekdayAverageChart"' not in content

    def test_death_chart_empty_hides_weekday_canvas(self, admin_client):
        """Death chart hides weekdayAverageChart canvas when no data."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '<canvas id="weekdayAverageChart"' not in content

    def test_admission_chart_has_specific_title(self, admin_client):
        """Admission chart page shows 'Admissões por Dia' title."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Admissões por Dia" in content

    def test_death_chart_has_specific_title(self, admin_client):
        """Death chart page shows 'Óbitos por Dia' title."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Óbitos por Dia" in content

    def test_admission_chart_has_specific_weekday_title(self, admin_client):
        """Admission chart shows 'Média de Admissões por Dia da Semana'."""
        self._create_admission_counts(14)
        url = reverse("services_portal:admission_chart") + "?dias=14"
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Média de Admissões por Dia da Semana" in content

    def test_death_chart_has_specific_weekday_title(self, admin_client):
        """Death chart shows 'Média de Óbitos por Dia da Semana'."""
        self._create_death_counts(14)
        url = reverse("services_portal:death_chart") + "?dias=14"
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Média de Óbitos por Dia da Semana" in content

    def test_admission_chart_empty_shows_empty_message(self, admin_client):
        """Admission chart shows empty-state message when no data."""
        url = reverse("services_portal:admission_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Nenhum dado disponível" in content

    def test_death_chart_empty_shows_empty_message(self, admin_client):
        """Death chart shows empty-state message when no data."""
        url = reverse("services_portal:death_chart")
        response = admin_client.get(url)
        content = response.content.decode()
        assert "Nenhum dado disponível" in content

    # ── ADC-S3: Navigation from list pages ──────────────────────────────

    def test_admission_list_has_chart_link(self, admin_client):
        """Admission list page includes a link to admission chart."""
        url = reverse("services_portal:admission_list")
        response = admin_client.get(url)
        content = response.content.decode()
        chart_url = reverse("services_portal:admission_chart")
        assert chart_url in content
        assert "Ver gráfico de admissões" in content

    def test_death_list_has_chart_link(self, admin_client):
        """Death list page includes a link to death chart."""
        url = reverse("services_portal:death_list")
        response = admin_client.get(url)
        content = response.content.decode()
        chart_url = reverse("services_portal:death_chart")
        assert chart_url in content
        assert "Ver gráfico de óbitos" in content

    def test_admission_list_preserves_date_selector(self, admin_client):
        """Admission list page still has date selector."""
        url = reverse("services_portal:admission_list")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '_date_selector' in content or 'date' in content.lower()
        # Dashboard back link is still present
        dashboard_url = reverse("services_portal:dashboard")
        assert dashboard_url in content

    def test_death_list_preserves_date_selector(self, admin_client):
        """Death list page still has date selector."""
        url = reverse("services_portal:death_list")
        response = admin_client.get(url)
        content = response.content.decode()
        assert '_date_selector' in content or 'date' in content.lower()
        # Dashboard back link is still present
        dashboard_url = reverse("services_portal:dashboard")
        assert dashboard_url in content

    # ── ADC-S3-DWI: Weekend highlighting ──────────────────────────────

    def test_admission_chart_context_has_weekend_flags(self, admin_client):
        """Admission chart context contains weekend_flags aligned with labels."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart") + "?dias=7"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "weekend_flags" in chart_data
        n = len(chart_data["labels"])
        assert len(chart_data["weekend_flags"]) == n
        assert len(chart_data["weekend_flags"]) == len(chart_data["counts"])
        assert all(isinstance(f, bool) for f in chart_data["weekend_flags"])

    def test_death_chart_context_has_weekend_flags(self, admin_client):
        """Death chart context contains weekend_flags aligned with labels."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart") + "?dias=7"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "weekend_flags" in chart_data
        n = len(chart_data["labels"])
        assert len(chart_data["weekend_flags"]) == n
        assert len(chart_data["weekend_flags"]) == len(chart_data["counts"])
        assert all(isinstance(f, bool) for f in chart_data["weekend_flags"])

    def test_admission_weekend_flags_correct_for_known_dates(self, admin_client):
        """Admission weekend_flags correct for Sat/Sun vs Mon-Fri."""
        today = timezone.localdate()
        for i in range(8, 0, -1):
            day = today - timedelta(days=i)
            DailyAdmissionCount.objects.create(date=day, count=5)

        url = reverse("services_portal:admission_chart") + "?dias=8"
        response = admin_client.get(url)
        labels = response.context["chart_data"]["labels"]
        flags = response.context["chart_data"]["weekend_flags"]

        for label, flag in zip(labels, flags, strict=True):
            d = datetime.strptime(label, "%d/%m/%Y").date()
            is_weekend = d.weekday() >= 5
            assert flag == is_weekend, (
                f"{label} weekday={d.weekday()} flag={flag}"
            )

    def test_death_weekend_flags_correct_for_known_dates(self, admin_client):
        """Death weekend_flags correct for Sat/Sun vs Mon-Fri."""
        today = timezone.localdate()
        for i in range(8, 0, -1):
            day = today - timedelta(days=i)
            DailyDeathCount.objects.create(date=day, count=3)

        url = reverse("services_portal:death_chart") + "?dias=8"
        response = admin_client.get(url)
        labels = response.context["chart_data"]["labels"]
        flags = response.context["chart_data"]["weekend_flags"]

        for label, flag in zip(labels, flags, strict=True):
            d = datetime.strptime(label, "%d/%m/%Y").date()
            is_weekend = d.weekday() >= 5
            assert flag == is_weekend, (
                f"{label} weekday={d.weekday()} flag={flag}"
            )

    def test_admission_chart_html_has_weekend_colors(self, admin_client):
        """Admission chart HTML/JS contains weekend_flags for per-bar coloring."""
        self._create_admission_counts(10)
        url = reverse("services_portal:admission_chart") + "?dias=7"
        response = admin_client.get(url)
        content = response.content.decode()
        assert '"weekend_flags"' in content
        assert "weekend_flags" in content
        assert any(
            term in content
            for term in ["Sábado", "Domingo", "sábado", "domingo",
                         "fim de semana", "dia útil"]
        )

    def test_death_chart_html_has_weekend_colors(self, admin_client):
        """Death chart HTML/JS contains weekend_flags for per-bar coloring."""
        self._create_death_counts(10)
        url = reverse("services_portal:death_chart") + "?dias=7"
        response = admin_client.get(url)
        content = response.content.decode()
        assert '"weekend_flags"' in content
        assert "weekend_flags" in content
        assert any(
            term in content
            for term in ["Sábado", "Domingo", "sábado", "domingo",
                         "fim de semana", "dia útil"]
        )
