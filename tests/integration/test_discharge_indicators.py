"""Integration: single captured-exit indicator on the discharge chart.

SCPED-S1: proves through the real HTTP views that:

- the main chart on ``/painel/altas/`` exposes exactly one daily event
  series — captured patient exits by ``saida_em`` — with no ``alta_em``
  summary series and no canonical/reconciled series;
- every record with ``saida_em`` is counted regardless of
  ``reconciliation_status``;
- the axis is a consecutive calendar window ending yesterday (zero-filled)
  instead of the rows of ``DailyDischargeCount``;
- moving averages, weekday averages and weekend colors are computed from
  that same captured-exit series with explicit ``America/Bahia`` boundaries;
- the hourly and specialty analysis uses the hour of ``saida_em``;
- the empty period renders the empty state.

All fixtures are synthetic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.patients.models import (
    EXIT_DEATH,
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

BAHIA = ZoneInfo("America/Bahia")

EXIT_SERIES_LABEL = "Saídas efetivas (saida_em)"
SUMMARY_SERIES_LABEL = "Sumários de alta (alta_em)"
EMPTY_STATE_MESSAGE = "Nenhuma saída capturada no período."


def _bahia(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Pin a wall-clock datetime to ``America/Bahia`` explicitly."""
    return datetime(year, month, day, hour, minute, tzinfo=BAHIA)


def _seed_exit(
    key: str, when: datetime, exit_type: str = EXIT_HOSPITAL_DISCHARGE
) -> Admission:
    """Create a canonical closed admission with reconciled exit provenance."""
    patient = Patient.objects.create(
        patient_source_key=key, source_system="tasy", name=f"Patient {key}")
    admission = Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-{key}",
        source_system="tasy",
        discharge_date=when,
    )
    ReconciliationEvent.objects.create(
        source_kind="discharge_record",
        source_id=admission.pk,
        admission=admission,
        status=RECONCILIATION_STATUS_RECONCILED,
        exit_type=exit_type,
    )
    return admission


def _seed_summary(prontuario: str, when: datetime) -> None:
    """Create one medical discharge summary registered at ``when``."""
    DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=f"INT-{prontuario}",
        alta_em=when,
    )


def _seed_captured_exit(
    key: str,
    when: datetime,
    especialidade: str = "",
    status: str = RECONCILIATION_STATUS_PENDING,
) -> DischargeRecord:
    """Create one discharge evidence whose effective exit is ``when``."""
    return DischargeRecord.objects.create(
        prontuario=key,
        data_internacao=f"INT-{key}",
        saida_em=when,
        especialidade=especialidade,
        reconciliation_status=status,
    )


@pytest.mark.django_db
class TestDashboardCardsNavigation:
    """Both discharge cards link to the discharge chart page."""

    def test_both_cards_render_and_link_to_chart(self, admin_client):
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()

        assert "Saídas hospitalares no dia" in content
        assert "Sumários de alta registrados" in content

        chart_url = reverse("services_portal:discharge_chart")
        assert chart_url == "/painel/altas/"
        assert content.count(chart_url) >= 2


@pytest.mark.django_db
class TestDischargeChartSeries:
    """The chart carries one labeled daily series of captured exits."""

    def _captured(self, key: str, offset: int, hour: int = 10) -> None:
        day = timezone.localdate() - timedelta(days=offset)
        _seed_captured_exit(
            key, _bahia(day.year, day.month, day.day, hour, 0)
        )

    def test_chart_has_single_captured_exit_series(self, admin_client):
        """The ``saida_em`` series is present and ``alta_em`` is absent."""
        for offset in range(3, 0, -1):
            self._captured(f"EX{offset}", offset)
        summary_day = timezone.localdate() - timedelta(days=1)
        _seed_summary(
            "901", _bahia(summary_day.year, summary_day.month, summary_day.day, 10, 0)
        )
        _seed_summary(
            "902", _bahia(summary_day.year, summary_day.month, summary_day.day, 11, 0)
        )

        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

        chart = response.context["chart_data"]
        assert chart["exit_series_label"] == EXIT_SERIES_LABEL
        # Three captured exits on the three most recent axis days only.
        assert chart["counts"][-3:] == [1, 1, 1]
        assert sum(chart["counts"]) == 3
        assert "summary_counts" not in chart
        assert "summary_series_label" not in chart

        html = response.content.decode()
        assert EXIT_SERIES_LABEL in html
        assert SUMMARY_SERIES_LABEL not in html

    def test_exit_series_counts_regardless_of_reconciliation_status(
        self, admin_client,
    ):
        """R2: pending/ambiguous/conflict exits still enter the series."""
        yesterday = timezone.localdate() - timedelta(days=1)
        statuses = [
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_CONFLICT,
            RECONCILIATION_STATUS_RECONCILED,
        ]
        for i, status in enumerate(statuses):
            _seed_captured_exit(
                f"ST{i}",
                _bahia(yesterday.year, yesterday.month, yesterday.day, 9 + i, 0),
                status=status,
            )

        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart = response.context["chart_data"]
        index = chart["labels"].index(yesterday.strftime("%d/%m/%Y"))
        assert chart["counts"][index] == 4

        html = response.content.decode()
        assert EXIT_SERIES_LABEL in html
        assert SUMMARY_SERIES_LABEL not in html

    def test_cross_midnight_exit_lands_on_local_date_by_saida_em(
        self, admin_client,
    ):
        """``alta_em`` on D stays off the chart; ``saida_em`` on E counts E."""
        d = timezone.localdate() - timedelta(days=2)
        e = timezone.localdate() - timedelta(days=1)
        _seed_summary("CM1", _bahia(d.year, d.month, d.day, 23, 50))
        DischargeRecord.objects.filter(prontuario="CM1").update(
            saida_em=_bahia(e.year, e.month, e.day, 0, 10),
        )
        # Stale canonical aggregate for D: the chart must ignore it.
        DailyDischargeCount.objects.create(date=d, count=99)

        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        chart = response.context["chart_data"]

        d_index = chart["labels"].index(d.strftime("%d/%m/%Y"))
        e_index = chart["labels"].index(e.strftime("%d/%m/%Y"))
        assert chart["counts"][d_index] == 0
        assert chart["counts"][e_index] == 1  # exit by saida_em on E
        assert chart["has_data"] is True

    def test_canonical_rows_do_not_shape_the_calendar_axis(self, admin_client):
        """R3: DailyDischargeCount rows neither build the axis nor count."""
        today = timezone.localdate()
        for i in range(30):
            DailyDischargeCount.objects.create(
                date=today - timedelta(days=30 - i), count=7
            )

        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        chart = response.context["chart_data"]
        # The axis is the requested calendar window ending yesterday.
        expected = [
            (today - timedelta(days=30 - i)).strftime("%d/%m/%Y")
            for i in range(30)
        ]
        assert chart["labels"] == expected
        assert chart["counts"] == [0] * 30
        assert chart["has_data"] is False
        assert "summary_counts" not in chart

        content = response.content.decode()
        assert EMPTY_STATE_MESSAGE in content

    def test_refresh_excludes_death_and_merged_from_aggregate(self, admin_client):
        """Hospital counts: canonical exits only; output stays identity-free."""
        d = date(2026, 3, 10)
        e = date(2026, 3, 11)
        for i in range(3):
            _seed_exit(f"HI{i}", _bahia(2026, 3, 10, 8 + i, 0))
        _seed_exit("HDEATH", _bahia(2026, 3, 10, 12, 0), exit_type=EXIT_DEATH)
        canonical = _seed_exit("HC1", _bahia(2026, 3, 11, 8, 0))
        duplicate = _seed_exit("HDUP", _bahia(2026, 3, 11, 8, 30))
        duplicate.merged_into = canonical
        duplicate.save(update_fields=["merged_into"])

        out = StringIO()
        call_command("refresh_daily_discharge_counts", stdout=out)

        assert DailyDischargeCount.objects.get(date=d).count == 3
        assert DailyDischargeCount.objects.get(date=e).count == 1
        output = out.getvalue()
        assert "Patient HI0" not in output
        assert "ADM-HDUP" not in output


@pytest.mark.django_db
class TestChartWindowAndMovingAverages:
    """Default 90-day window through yesterday; averages exit-only."""

    def _chart(self, admin_client, query: str = ""):
        url = reverse("services_portal:discharge_chart") + query
        response = admin_client.get(url)
        assert response.status_code == 200
        return response

    def _captured_exit_counts(self, days: int) -> None:
        """Seed one captured exit per calendar day over the last ``days``."""
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            _seed_captured_exit(
                f"WIN-{day.isoformat()}",
                _bahia(day.year, day.month, day.day, 10, 0),
            )

    def test_default_window_is_90_calendar_days_through_yesterday(
        self, admin_client,
    ):
        today = timezone.localdate()
        self._captured_exit_counts(120)

        response = self._chart(admin_client)
        chart = response.context["chart_data"]

        assert len(chart["labels"]) == 90
        assert chart["counts"] == [1] * 90
        assert chart["has_data"] is True
        assert today.strftime("%d/%m/%Y") not in chart["labels"]
        assert chart["labels"][-1] == (today - timedelta(days=1)).strftime(
            "%d/%m/%Y"
        )

    def test_dias_parameter_yields_exact_consecutive_days(self, admin_client):
        today = timezone.localdate()
        self._captured_exit_counts(60)

        response = self._chart(admin_client, "?dias=30")
        chart = response.context["chart_data"]
        expected = [
            (today - timedelta(days=30 - i)).strftime("%d/%m/%Y")
            for i in range(30)
        ]
        assert chart["labels"] == expected

    def test_moving_averages_use_the_captured_exit_series(self, admin_client):
        """R4: SMA/EMA run on saida_em counts; summaries never enter them."""
        today = timezone.localdate()
        for i in range(10):  # offsets 10..1 get counts 1..10
            day = today - timedelta(days=10 - i)
            for n in range(i + 1):
                _seed_captured_exit(
                    f"MA-{day.isoformat()}-{n}",
                    _bahia(day.year, day.month, day.day, 10, n % 60),
                )
        summary_day = today - timedelta(days=2)
        _seed_summary(
            "MA1", _bahia(summary_day.year, summary_day.month, summary_day.day, 10, 0)
        )

        response = self._chart(admin_client, "?dias=10")
        chart = response.context["chart_data"]

        assert chart["counts"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert chart["sma7"][6] == 4.0  # mean(1..7)
        assert chart["ema7"][6] == chart["sma7"][6]  # EMA seeds with SMA
        assert chart["sma30"] == [None] * 10  # only 10 exit points
        # The summary record never enters the exit series or its averages.
        assert sum(chart["counts"]) == 55
        assert "summary_counts" not in chart

    def test_hourly_specialty_parameters_unchanged(self, admin_client):
        response = self._chart(admin_client)
        context = response.context
        assert "h_start" in context
        assert "h_end" in context
        assert "hourly_table" in context
        assert "hour_labels" in context

    def test_hourly_uses_saida_em_hour_not_alta_em(self, admin_client):
        """R5: summary signed at 14h but exit at 18h counts at 18h."""
        day = timezone.localdate() - timedelta(days=1)
        record = DischargeRecord.objects.create(
            prontuario="H1",
            data_internacao="INT-H1",
            alta_em=_bahia(day.year, day.month, day.day, 14, 0),
            especialidade="CME",
        )
        record.saida_em = _bahia(day.year, day.month, day.day, 18, 0)
        record.save(update_fields=["saida_em"])
        # Summary-only record (no saida_em) must stay out of the analysis.
        DischargeRecord.objects.create(
            prontuario="H2",
            data_internacao="INT-H2",
            alta_em=_bahia(day.year, day.month, day.day, 10, 0),
            especialidade="CIR",
        )

        response = self._chart(admin_client)
        context = response.context
        hour_dist = context["hour_dist"]
        assert hour_dist["CME"][18] == 1
        assert hour_dist["CME"][14] == 0
        assert "CIR" not in hour_dist
        assert "CIR" not in context["sorted_specialties"]
        row = next(
            r for r in context["hourly_table"] if r["especialidade"] == "CME"
        )
        assert row["total"] == 1
        assert row["after_16"] == 1
        assert row["pct"] == 100.0

    def test_exit_at_bahia_23h_is_grouped_on_bahia_date_and_hour(
        self, admin_client,
    ):
        """R5: 02:00 UTC is 23:00 America/Bahia on the previous local date."""
        yesterday = timezone.localdate(timezone=BAHIA) - timedelta(days=1)
        # yesterday 23:00 Bahia == today 02:00 UTC (Bahia is UTC-3).
        utc_day = yesterday + timedelta(days=1)
        stored_utc = datetime(
            utc_day.year, utc_day.month, utc_day.day, 2, 0,
            tzinfo=dt_timezone.utc,
        )
        _seed_captured_exit("TZ1", stored_utc, especialidade="CTI")

        response = self._chart(admin_client)
        chart = response.context["chart_data"]
        yesterday_index = chart["labels"].index(yesterday.strftime("%d/%m/%Y"))
        assert chart["counts"][yesterday_index] == 1

        hour_dist = response.context["hour_dist"]
        assert hour_dist["CTI"][23] == 1  # Bahia hour of the effective exit
        assert hour_dist["CTI"][2] == 0  # never the raw UTC hour


@pytest.mark.django_db
class TestChartEmptyState:
    """An empty period keeps the calendar axis and renders the empty state."""

    def test_empty_period_renders_empty_state(self, admin_client):
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart = response.context["chart_data"]
        assert chart["has_data"] is False
        assert chart["counts"] == [0] * 90

        content = response.content.decode()
        assert EMPTY_STATE_MESSAGE in content
