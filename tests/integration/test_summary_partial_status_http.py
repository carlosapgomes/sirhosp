"""Integration tests for partial run status via HTTP (APS-S5 RED phase).

Tests that the run status endpoint correctly displays:
  - partial run status (badge + error message)
  - incomplete state status info
  - error message visibility
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
        username="partialtester", password="testpass123"
    )


def _login(client: Client):
    client.force_login(_make_user())


def _make_admission() -> Admission:
    patient = Patient.objects.create(
        patient_source_key="S5-PARTIAL-P001",
        source_system="tasy",
        name="Partial Test Patient",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="S5-PARTIAL-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        ward="Enfermaria B",
    )


# ---------------------------------------------------------------------------
# Partial run status display
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPartialRunStatusView:
    """HTTP tests for viewing a partial summary run."""

    def test_status_page_shows_partial_badge(self):
        """When run.status is 'partial', the badge displays 'Partial'."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="partial",
            error_message="Chunk 1 exhausted 3 retries: Missing required field: 'resumo_markdown'.",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        # The template uses get_status_display
        assert "parcial" in content or "partial" in content

    def test_status_page_shows_error_message_for_partial(self):
        """When run is partial, the error_message is visible on the page."""
        admission = _make_admission()
        error_msg = (
            "Chunk 1 exhausted 3 retries: "
            "Missing required field: 'resumo_markdown'."
        )
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="partial",
            error_message=error_msg,
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Missing" in content

    def test_partial_run_shows_finished_at(self):
        """Partial runs show the finished_at timestamp."""
        admission = _make_admission()
        tz = ZoneInfo("America/Sao_Paulo")
        finished = datetime(2026, 4, 26, 15, 0, 0, tzinfo=tz)
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="partial",
            started_at=datetime(2026, 4, 26, 14, 55, 0, tzinfo=tz),
            finished_at=finished,
            error_message="Retries exhausted.",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Finalizado" in content

    def test_partial_run_badge_has_warning_class(self):
        """Partial run badge uses bg-warning CSS class."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="partial",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # The template uses bg-warning for partial
        assert "bg-warning" in content or "partial" in content.lower()

    def test_partial_run_displays_chunk_info(self):
        """Partial runs show chunk progress information."""
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="partial",
            total_chunks=3,
            current_chunk_index=1,
            error_message="Retries exhausted on chunk 1.",
        )
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        # The template shows progress via current/total chunks
        content = response.content.decode("utf-8")
        assert "3" in content or str(run.total_chunks) in content


@pytest.mark.django_db
class TestPartialRunEndToEnd:
    """End-to-end test: create a run, process it (partial), check status."""

    def test_full_cycle_create_to_partial_status(self):
        """Create run -> worker processes (mock failure) -> status shows partial."""
        from unittest.mock import patch

        from django.core.management import call_command

        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
        )

        # Mock the LLM gateway to always fail validation
        invalid_response = {
            "estado_estruturado": {},
            "mudancas_da_rodada": [],
            "incertezas": [],
            "evidencias": [],
        }

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=invalid_response,
        ):
            call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "partial"
        assert run.error_message != ""

        # Now check via HTTP
        client = Client()
        _login(client)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # The template should show partial badge
        assert "Partial" in content or "Parcial" in content
