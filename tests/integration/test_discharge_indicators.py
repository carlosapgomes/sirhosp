"""Integration: effective-exit indicators and separate summary indicators.

RPSA-S8: proves through the real HTTP views and the real management
command that:

- both dashboard cards render and navigate to ``/painel/altas/``;
- the discharge chart exposes two labeled series — hospital exits by
  ``saida_em`` (from ``DailyDischargeCount``) and medical summaries by
  ``alta_em`` (derived on request) — over the same window, grouping and
  today-excluded boundary;
- moving averages stay on the exit series only;
- the aggregate rebuild counts canonical exits only (death-closed
  episodes and merged duplicates excluded) and a cross-midnight
  ``alta_em``/``saida_em`` pair lands on its respective local date;
- the empty period renders the empty state.

All fixtures are synthetic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

BAHIA = ZoneInfo("America/Bahia")

EXIT_SERIES_LABEL = "Saídas hospitalares (saida_em)"
SUMMARY_SERIES_LABEL = "Sumários de alta (alta_em)"


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
    """The chart carries two labeled daily series."""

    def test_chart_has_two_labeled_series(self, admin_client):
        today = timezone.localdate()
        for i in range(5):
            day = today - timedelta(days=5 - i)
            DailyDischargeCount.objects.create(date=day, count=i + 1)
        alta_day = today - timedelta(days=3)
        _seed_summary("901", _bahia(alta_day.year, alta_day.month, alta_day.day, 10, 0))
        _seed_summary("902", _bahia(alta_day.year, alta_day.month, alta_day.day, 11, 0))

        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

        chart = response.context["chart_data"]
        assert chart["counts"] == [1, 2, 3, 4, 5]
        assert len(chart["summary_counts"]) == len(chart["labels"])
        summary_index = chart["labels"].index(alta_day.strftime("%d/%m/%Y"))
        assert chart["summary_counts"][summary_index] == 2
        assert sum(chart["summary_counts"]) == 2

        html = response.content.decode()
        assert EXIT_SERIES_LABEL in html
        assert SUMMARY_SERIES_LABEL in html

    def test_cross_midnight_pair_lands_on_respective_local_dates(
        self, admin_client,
    ):
        """``alta_em`` 23:50 on D stays a summary; ``saida_em`` 00:10 on E
        becomes the exit — the two indicators keep their own dates."""
        d = date(2026, 3, 7)
        e = date(2026, 3, 8)
        _seed_exit("CM1", _bahia(2026, 3, 8, 0, 10))
        _seed_summary("CM1", _bahia(2026, 3, 7, 23, 50))
        DischargeRecord.objects.filter(prontuario="CM1").update(
            saida_em=_bahia(2026, 3, 8, 0, 10),
        )

        call_command("refresh_daily_discharge_counts")
        # Historical aggregate row for D so both dates sit on the chart axis.
        DailyDischargeCount.objects.create(date=d, count=4)

        assert DailyDischargeCount.objects.get(date=e).count == 1
        assert DailyDischargeCount.objects.get(date=d).count == 4

        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        chart = response.context["chart_data"]

        d_index = chart["labels"].index(d.strftime("%d/%m/%Y"))
        e_index = chart["labels"].index(e.strftime("%d/%m/%Y"))
        assert chart["counts"][d_index] == 4  # exits on D are the seeded aggregate
        assert chart["counts"][e_index] == 1  # exit by saida_em on E
        assert chart["summary_counts"][d_index] == 1  # summary by alta_em on D
        assert chart["summary_counts"][e_index] == 0

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
    """Default 90-day window through yesterday; moving averages exit-only."""

    def _chart(self, admin_client, query: str = ""):
        url = reverse("services_portal:discharge_chart") + query
        response = admin_client.get(url)
        assert response.status_code == 200
        return response

    def test_default_window_is_90_days_through_yesterday(self, admin_client):
        today = timezone.localdate()
        for i in range(120):
            day = today - timedelta(days=120 - i)
            DailyDischargeCount.objects.create(date=day, count=1)

        response = self._chart(admin_client)
        chart = response.context["chart_data"]

        assert len(chart["labels"]) == 90
        assert today.strftime("%d/%m/%Y") not in chart["labels"]
        assert len(chart["summary_counts"]) == 90

    def test_dias_parameter_still_respected(self, admin_client):
        today = timezone.localdate()
        for i in range(60):
            day = today - timedelta(days=60 - i)
            DailyDischargeCount.objects.create(date=day, count=1)

        response = self._chart(admin_client, "?dias=30")
        chart = response.context["chart_data"]
        assert len(chart["labels"]) <= 30

    def test_moving_averages_remain_on_exit_series_only(self, admin_client):
        today = timezone.localdate()
        for i in range(10):
            day = today - timedelta(days=10 - i)
            DailyDischargeCount.objects.create(date=day, count=i + 1)
        summary_day = today - timedelta(days=2)
        _seed_summary(
            "MA1", _bahia(summary_day.year, summary_day.month, summary_day.day, 10, 0)
        )

        response = self._chart(admin_client, "?dias=10")
        chart = response.context["chart_data"]

        assert chart["counts"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        sma7 = chart["sma7"]
        ema7 = chart["ema7"]
        sma30 = chart["sma30"]
        assert sma7[6] == 4.0  # mean(1..7)
        assert ema7[6] == sma7[6]  # EMA seeds with SMA
        assert sma30[6] is None  # only 10 exit points → no SMA-30
        # The summary record never enters the exit series or its averages.
        assert sum(chart["counts"]) == 55

    def test_hourly_specialty_parameters_unchanged(self, admin_client):
        response = self._chart(admin_client)
        context = response.context
        assert "h_start" in context
        assert "h_end" in context
        assert "hourly_table" in context
        assert "hour_labels" in context


@pytest.mark.django_db
class TestChartEmptyState:
    """An empty period renders the empty-state message."""

    def test_empty_period_renders_empty_state(self, admin_client):
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Nenhum dado" in content
