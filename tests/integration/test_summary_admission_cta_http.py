"""APS-S6: Integration tests for summary CTA on admission page.

Tests that the CTA buttons on the admission list page correctly create
SummaryRun records via POST to create_summary_run.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from apps.patients.models import Admission, Patient
from apps.summaries.models import SummaryRun

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def patient_joao_cta(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P700",
        source_system="tasy",
        name="JOAO CTA TEST",
    )


@pytest.fixture
def admission_joao_open(patient_joao_cta: Patient) -> Admission:
    """Open admission (no discharge_date)."""
    return Admission.objects.create(
        patient=patient_joao_cta,
        source_admission_key="ADM700",
        source_system="tasy",
        admission_date=datetime(2026, 4, 10, 9, 0, tzinfo=TZ),
        ward="CLINICA MEDICA",
    )


@pytest.fixture
def admission_joao_closed(patient_joao_cta: Patient) -> Admission:
    """Closed admission with discharge_date."""
    return Admission.objects.create(
        patient=patient_joao_cta,
        source_admission_key="ADM701",
        source_system="tasy",
        admission_date=datetime(2026, 3, 1, 10, 0, tzinfo=TZ),
        discharge_date=datetime(2026, 3, 5, 14, 0, tzinfo=TZ),
        ward="UTI",
    )


@pytest.fixture
def auth_client_cta(client: Client, db: object) -> Client:
    """Authenticated client for CTA integration tests."""
    from django.contrib.auth.models import User

    User.objects.create_user(username="ctauser", password="ctapass123")
    client.login(username="ctauser", password="ctapass123")
    return client


class TestGenerateCTA:
    """POST from 'Gerar resumo' CTA creates correct SummaryRun."""

    def test_generate_cta_creates_queued_run(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        """Posting mode=generate creates a QUEUED SummaryRun."""
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "generate"},
        )
        assert response.status_code == 302

        run = SummaryRun.objects.get(admission=admission_joao_open)
        assert run.mode == "generate"
        assert run.status == SummaryRun.Status.QUEUED
        assert run.target_end_date == date.today()

    def test_generate_cta_redirects_to_run_status(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        """After creating run, redirects to run status page."""
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "generate"},
        )
        assert response.status_code == 302
        run = SummaryRun.objects.latest("created_at")
        assert f"/summaries/{run.pk}/" in response.url  # type: ignore[attr-defined]


class TestUpdateCTA:
    """POST from 'Atualizar resumo' CTA creates correct SummaryRun."""

    def test_update_cta_creates_queued_run(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        """Posting mode=update creates a QUEUED SummaryRun."""
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "update"},
        )
        assert response.status_code == 302

        run = SummaryRun.objects.get(admission=admission_joao_open)
        assert run.mode == "update"
        assert run.status == SummaryRun.Status.QUEUED


class TestRegenerateCTA:
    """POST from 'Regenerar resumo' CTA creates correct SummaryRun."""

    def test_regenerate_cta_creates_queued_run(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        """Posting mode=regenerate creates a QUEUED SummaryRun."""
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "regenerate"},
        )
        assert response.status_code == 302

        run = SummaryRun.objects.get(admission=admission_joao_open)
        assert run.mode == "regenerate"
        assert run.status == SummaryRun.Status.QUEUED


class TestClosedAdmissionCTA:
    """CTA for closed admission uses correct target_end_date."""

    def test_closed_admission_target_end_is_discharge_date(
        self,
        auth_client_cta: Client,
        admission_joao_closed: Admission,
    ) -> None:
        """For closed admission, target_end_date = min(today, discharge_date).
        Since discharge_date is in the past, it should be discharge_date.
        """
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_closed.pk}/summary/create/",
            {"mode": "generate"},
        )
        assert response.status_code == 302

        run = SummaryRun.objects.get(admission=admission_joao_closed)
        assert run.target_end_date == date(2026, 3, 5)


class TestInvalidMode:
    """Invalid mode is rejected."""

    def test_invalid_mode_returns_400(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "invalid_mode"},
        )
        assert response.status_code == 400

    def test_empty_mode_returns_400(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
    ) -> None:
        response = auth_client_cta.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": ""},
        )
        assert response.status_code == 400


class TestAuthRequired:
    """Summary CTA endpoints require authentication."""

    def test_create_run_redirects_anonymous(
        self,
        client: Client,
        admission_joao_open: Admission,
    ) -> None:
        response = client.post(
            f"/admissions/{admission_joao_open.pk}/summary/create/",
            {"mode": "generate"},
        )
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


class TestAdmissionPageRendersCTA:
    """The admission list page must render the summary CTA form."""

    def test_page_has_csrf_token_in_cta_form(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
        patient_joao_cta: Patient,
    ) -> None:
        """Admission page must include CSRF token for summary forms."""
        response = auth_client_cta.get(
            f"/patients/{patient_joao_cta.pk}/admissions/"
        )
        content = response.content.decode()
        assert "csrfmiddlewaretoken" in content

    def test_page_without_summary_has_generate_form(
        self,
        auth_client_cta: Client,
        admission_joao_open: Admission,
        patient_joao_cta: Patient,
    ) -> None:
        """When no summary, the page renders a form posting to create
        with mode=generate."""
        response = auth_client_cta.get(
            f"/patients/{patient_joao_cta.pk}/admissions/"
        )
        content = response.content.decode()
        assert "Gerar resumo" in content
        assert 'mode' in content
        assert 'generate' in content
