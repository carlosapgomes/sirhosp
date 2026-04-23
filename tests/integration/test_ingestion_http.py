"""Integration tests for HTTP surface of on-demand ingestion (Slice S4).

Tests the user-facing endpoints:
- POST to create an ingestion run
- GET to check run status with counters and timestamps
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.ingestion.models import IngestionRun


@pytest.mark.django_db
class TestAnonymousAccessBlocked:
    """Anonymous users must be redirected to login for ingestion endpoints."""

    def test_anonymous_create_run_get_redirects_to_login(self):
        """GET to create-run without auth redirects to LOGIN_URL with next."""
        client = Client()
        url = reverse("ingestion:create_run")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")
        assert f"next={url}" in response.url

    def test_anonymous_create_run_post_redirects_to_login(self):
        """POST to create-run without auth redirects to LOGIN_URL."""
        client = Client()
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        assert response.status_code == 302
        assert response.url.startswith("/login/")
        assert IngestionRun.objects.count() == 0

    def test_anonymous_run_status_redirects_to_login(self):
        """GET to run-status without auth redirects to LOGIN_URL."""
        run = IngestionRun.objects.create(
            status="queued",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")
        assert f"next={url}" in response.url

    def test_health_endpoint_stays_public(self):
        """Health endpoint must remain accessible without auth."""
        client = Client()
        response = client.get("/health/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestCreateIngestionRunView:
    """HTTP tests for creating an on-demand ingestion run."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser", password="testpass123")
        client.force_login(user)

    def test_create_run_returns_200_on_get(self):
        """GET to the create-run endpoint renders the form."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.get(url)
        assert response.status_code == 200

    def test_create_run_post_success(self):
        """POST with valid data creates a queued IngestionRun and redirects."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        # Should redirect to status page
        assert response.status_code == 302
        run = IngestionRun.objects.get()
        assert run.status == "queued"
        assert run.parameters_json["patient_record"] == "12345"
        assert run.parameters_json["start_date"] == "2026-04-01"
        assert run.parameters_json["end_date"] == "2026-04-19"
        # Redirect should point to status page
        assert str(run.pk) in response.url

    def test_create_run_post_missing_patient_record(self):
        """POST without patient_record returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        assert response.status_code == 200  # re-renders form
        assert IngestionRun.objects.count() == 0
        assert "obrigat" in response.content.decode("utf-8").lower() or \
               "required" in response.content.decode("utf-8").lower()

    def test_create_run_post_missing_start_date(self):
        """POST without start_date returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "",
                "end_date": "2026-04-19",
            },
        )
        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0

    def test_create_run_post_missing_end_date(self):
        """POST without end_date returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "",
            },
        )
        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0

    def test_create_run_post_end_before_start(self):
        """POST with end_date before start_date returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-19",
                "end_date": "2026-04-01",
            },
        )
        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0

    def test_create_run_invalid_date_format(self):
        """POST with invalid date format returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "01/04/2026",
                "end_date": "19/04/2026",
            },
        )
        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0


@pytest.mark.django_db
class TestRunStatusView:
    """HTTP tests for viewing ingestion run status."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser2", password="testpass123")
        client.force_login(user)

    def test_status_queued_shows_processing_message(self):
        """Queued run shows 'em processamento' feedback."""
        run = IngestionRun.objects.create(
            status="queued",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        assert "fila" in content or "processamento" in content or "queued" in content

    def test_status_succeeded_shows_success_message(self):
        """Succeeded run shows success feedback with counters."""
        run = IngestionRun.objects.create(
            status="succeeded",
            events_processed=5,
            events_created=3,
            events_skipped=2,
            events_revised=0,
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "3" in content  # events_created
        assert "2" in content  # events_skipped
        assert (
            "sucesso" in content.lower()
            or "conclu" in content.lower()
            or "succeeded" in content.lower()
        )

    def test_status_failed_shows_error_message(self):
        """Failed run shows error message preserving traceability."""
        run = IngestionRun.objects.create(
            status="failed",
            error_message="Timeout ao conectar com o sistema fonte após 90s",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert (
            "falha" in content.lower()
            or "falhou" in content.lower()
            or "failed" in content.lower()
        )
        # Error message should be visible (not hidden from user)
        assert "90s" in content or "Timeout" in content

    def test_status_shows_timestamps(self):
        """Status page shows started_at and finished_at timestamps."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={"patient_record": "12345"},
        )
        # Manually set timestamps for deterministic test
        run.started_at = datetime(2026, 4, 19, 10, 0, 0, tzinfo=tz)
        run.finished_at = datetime(2026, 4, 19, 10, 2, 30, tzinfo=tz)
        run.save()

        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Should show some form of the timestamp
        assert "10:00" in content or "10h00" in content or "19/04" in content

    def test_status_nonexistent_run_returns_404(self):
        """Requesting status of non-existent run returns 404."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[99999])
        response = client.get(url)
        assert response.status_code == 404

    def test_status_running_shows_processing(self):
        """Running run shows 'em processamento' feedback."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        assert "execução" in content or "processamento" in content or "running" in content

    def test_status_queued_has_auto_refresh(self):
        """Queued/running states should auto-refresh every 5 seconds."""
        run = IngestionRun.objects.create(
            status="queued",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        response = client.get(reverse("ingestion:run_status", args=[run.pk]))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'http-equiv="refresh"' in content
        assert 'content="5"' in content

    def test_status_terminal_state_has_no_auto_refresh(self):
        """Terminal states should not force immediate refresh loops."""
        run = IngestionRun.objects.create(
            status="failed",
            error_message="Falha de teste",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)
        response = client.get(reverse("ingestion:run_status", args=[run.pk]))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'http-equiv="refresh"' not in content

    def test_status_shows_patient_record(self):
        """Status page shows the patient record from parameters."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={
                "patient_record": "98765",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "98765" in content

    def test_status_shows_date_range(self):
        """Status page shows the date range from parameters."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "2026-04-01" in content or "01/04/2026" in content
        assert "2026-04-19" in content or "19/04/2026" in content


@pytest.mark.django_db
class TestCreateRunPrefill:
    """Test that patient_record can be prefilled via querystring."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser_pf", password="testpass123")
        client.force_login(user)

    def test_get_with_patient_record_prefills_form(self):
        """GET /ingestao/criar/?patient_record=P100 prefills the field."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run") + "?patient_record=P100"
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "P100" in content

    def test_get_without_patient_record_renders_empty_form(self):
        """GET /ingestao/criar/ without prefill renders empty field."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestIngestionFlowEndToEnd:
    """End-to-end flow: create run, then check its status."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser3", password="testpass123")
        client.force_login(user)

    def test_create_then_status(self):
        """Full flow: create a run, redirect to status, verify status page."""
        client = Client()
        self._login(client)

        # Step 1: Create run
        create_url = reverse("ingestion:create_run")
        response = client.post(
            create_url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        assert response.status_code == 302
        run = IngestionRun.objects.get()

        # Step 2: Follow redirect to status
        status_url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(status_url)
        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        # Should show queued state
        assert "fila" in content or "processamento" in content or "queued" in content


@pytest.mark.django_db
class TestAdmissionsOnlyRunHTTP:
    """HTTP tests for admissions-only run creation and status (AFMF-S2)."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser_adm", password="testpass123")
        client.force_login(user)

    def test_create_admissions_only_run_success(self):
        """POST to create admissions-only run with valid patient_record succeeds."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_admissions_only")
        response = client.post(
            url,
            {"patient_record": "99999"},
        )
        assert response.status_code == 302
        run = IngestionRun.objects.get()
        assert run.status == "queued"
        params = run.parameters_json
        assert params["patient_record"] == "99999"
        assert params["intent"] == "admissions_only"
        assert str(run.pk) in response.url

    def test_create_admissions_only_run_missing_record(self):
        """POST without patient_record returns form with error."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_admissions_only")
        response = client.post(url, {"patient_record": ""})
        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0
        body = response.content.decode("utf-8").lower()
        assert "obrigat" in body or "required" in body

    def test_create_admissions_only_get_renders_form(self):
        """GET renders the admissions-only form with prefilled patient_record."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_admissions_only") + "?patient_record=P200"
        response = client.get(url)
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "P200" in body

    def test_admissions_only_status_shows_intent(self):
        """Status page for admissions-only run shows intent-specific info."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={
                "patient_record": "99999",
                "intent": "admissions_only",
            },
            admissions_seen=3,
            admissions_created=2,
            admissions_updated=1,
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        body = response.content.decode("utf-8").lower()
        assert "internação" in body or "internacoes" in body or "admiss" in body

    def test_admissions_only_empty_snapshot_status(self):
        """Status page for admissions-only run with empty snapshot shows no-admissions message."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={
                "patient_record": "99999",
                "intent": "admissions_only",
            },
            admissions_seen=0,
            admissions_created=0,
            admissions_updated=0,
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        body = response.content.decode("utf-8").lower()
        assert (
            "sem internação" in body
            or "sem internacoes" in body
            or "nenhuma internação" in body
            or "no admissions" in body
            or "no_admissions" in body
        )
        assert "nova extração" not in body
        assert "voltar para pacientes" in body


@pytest.mark.django_db
class TestFullAdmissionSyncRunHTTP:
    """S3: HTTP tests for full-admission-sync run creation (from admission selection)."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="testuser_fullsync", password="testpass123")
        client.force_login(user)

    def test_create_run_with_admission_derived_dates_succeeds(self):
        """POST from admission CTA persists full-sync intent and context."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": "2026-04-23",
                "intent": "full_admission_sync",
                "admission_id": "77",
                "admission_source_key": "ADM-2026-77",
            },
        )
        assert response.status_code == 302
        run = IngestionRun.objects.get()
        assert run.status == "queued"
        assert run.intent == "full_admission_sync"
        params = run.parameters_json
        assert params["patient_record"] == "12345"
        assert params["start_date"] == "2026-04-15"
        assert params["end_date"] == "2026-04-23"
        assert params["intent"] == "full_admission_sync"
        assert params["admission_id"] == "77"
        assert params["admission_source_key"] == "ADM-2026-77"

    def test_run_status_shows_full_sync_date_range(self):
        """Status page for full-sync run shows date range and admission context."""
        run = IngestionRun.objects.create(
            status="queued",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": "2026-04-23",
                "intent": "full_admission_sync",
                "admission_id": "77",
                "admission_source_key": "ADM-2026-77",
            },
        )
        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Sincronização completa de internação" in content
        assert "ADM-2026-77" in content
        assert "2026-04-15" in content
        assert "2026-04-23" in content
