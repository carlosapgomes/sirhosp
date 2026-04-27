"""Integration tests for summary HTTP surface (APS-S2).

Tests the user-facing endpoints:
- POST to create a summary run (enqueue)
- GET to check run status with metadata
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.patients.models import Admission, Patient
from apps.summaries.models import SummaryRun

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user():
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username="summarytester", password="testpass123"
    )


def _login(client: Client):
    client.force_login(_make_user())


def _make_admission(
    *,
    discharge_date: datetime | None = None,
) -> Admission:
    patient = Patient.objects.create(
        patient_source_key="S2-P001",
        source_system="tasy",
        name="S2 TEST PATIENT",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="S2-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        discharge_date=discharge_date,
        ward="Enfermaria A",
    )


# ---------------------------------------------------------------------------
# Anonymous access
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnonymousAccessBlocked:
    """Anonymous users must be redirected to login for summary endpoints."""

    def test_anonymous_create_get_redirects_to_login(self):
        admission = _make_admission()
        client = Client()
        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_create_post_redirects_to_login(self):
        admission = _make_admission()
        client = Client()
        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {"mode": "generate"})
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]
        assert SummaryRun.objects.count() == 0

    def test_anonymous_status_redirects_to_login(self):
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
        )
        client = Client()
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Create summary run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateSummaryRunView:
    """HTTP tests for creating an on-demand summary run."""

    def test_create_run_success_redirects_to_status(self):
        """POST with valid admission_id creates a queued run and redirects."""
        admission = _make_admission()
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {"mode": "generate"})

        assert response.status_code == 302
        run = SummaryRun.objects.get()
        assert run.status == "queued"
        assert run.admission_id == admission.pk
        assert run.mode == "generate"
        assert str(run.pk) in response.url

    def test_create_run_open_admission_sets_target_end_date_today(self):
        """Open admission (no discharge_date) sets target_end_date = today."""
        admission = _make_admission(discharge_date=None)
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {"mode": "generate"})

        assert response.status_code == 302
        run = SummaryRun.objects.get()
        assert run.target_end_date == date.today()

    def test_create_run_closed_admission_sets_target_end_date_discharge(self):
        """Closed admission sets target_end_date = discharge_date."""
        discharge = datetime(2026, 4, 20, 14, 0, tzinfo=TZ)
        admission = _make_admission(discharge_date=discharge)
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {"mode": "generate"})

        assert response.status_code == 302
        run = SummaryRun.objects.get()
        # discharge date is 2026-04-20, which is <= today (2026-04-26)
        assert run.target_end_date == discharge.date()

    def test_create_run_with_update_mode(self):
        """POST with mode=update creates a run with that mode."""
        admission = _make_admission()
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        client.post(url, {"mode": "update"})

        run = SummaryRun.objects.get()
        assert run.mode == "update"
        assert run.status == "queued"

    def test_create_run_with_regenerate_mode(self):
        """POST with mode=regenerate creates a run with that mode."""
        admission = _make_admission()
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        client.post(url, {"mode": "regenerate"})

        run = SummaryRun.objects.get()
        assert run.mode == "regenerate"
        assert run.status == "queued"

    def test_create_run_nonexistent_admission_returns_404(self):
        """POST with non-existent admission_id returns 404."""
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[99999])
        response = client.post(url, {"mode": "generate"})

        assert response.status_code == 404
        assert SummaryRun.objects.count() == 0

    def test_create_run_missing_mode_returns_400(self):
        """POST without mode returns Bad Request."""
        admission = _make_admission()
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {})

        assert response.status_code == 400
        assert SummaryRun.objects.count() == 0

    def test_create_run_invalid_mode_returns_400(self):
        """POST with unsupported mode returns Bad Request."""
        admission = _make_admission()
        client = Client()
        _login(client)

        url = reverse("summaries:create_summary_run", args=[admission.pk])
        response = client.post(url, {"mode": "invalid_mode"})

        assert response.status_code == 400
        assert SummaryRun.objects.count() == 0


# ---------------------------------------------------------------------------
# Summary run status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryRunStatusView:
    """HTTP tests for viewing summary run status."""

    def test_status_shows_status_field(self):
        """Status page displays the current run status."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        assert "queued" in content

    def test_status_shows_admission_info(self):
        """Status page displays the admission reference."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert admission.patient.name in content
        assert admission.source_admission_key in content

    def test_status_shows_mode(self):
        """Status page displays the run mode."""
        admission = _make_admission()
        client = Client()
        _login(client)

        for mode in ["generate", "update", "regenerate"]:
            run = SummaryRun.objects.create(
                admission=admission,
                mode=mode,
                target_end_date=date.today(),
                status="queued",
            )

            url = reverse("summaries:run_status", args=[run.pk])
            response = client.get(url)

            assert response.status_code == 200
            content = response.content.decode("utf-8").lower()
            assert mode in content

    def test_status_shows_timestamps(self):
        """Status page shows created_at timestamp."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
        )
        # Set deterministic timestamps
        tz = ZoneInfo("America/Sao_Paulo")
        run.started_at = datetime(2026, 4, 26, 14, 0, 0, tzinfo=tz)
        run.finished_at = datetime(2026, 4, 26, 14, 5, 0, tzinfo=tz)
        run.save(update_fields=["started_at", "finished_at"])

        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        # Should show created_at (which is still the default auto_now_add)
        assert run.created_at is not None

    def test_status_nonexistent_run_returns_404(self):
        """Requesting status of non-existent run returns 404."""
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[99999])
        response = client.get(url)

        assert response.status_code == 404

    def test_status_shows_target_end_date(self):
        """Status page shows the target end date."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date(2026, 4, 25),
            status="queued",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "25/04/2026" in content or "2026-04-25" in content
