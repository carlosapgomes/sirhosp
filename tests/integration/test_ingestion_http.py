"""Integration tests for HTTP surface of on-demand ingestion (Slice S4).

Tests the user-facing endpoints:
- POST to create an ingestion run
- GET to check run status with counters and timestamps
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

TZ = ZoneInfo("America/Sao_Paulo")


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

    def test_create_run_get_without_context_redirects_to_patients(self):
        """GET to create-run without context redirects to /patients/."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.get(url)
        assert response.status_code == 302
        assert "/patients/" in response.url

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
        """Queued/running states should use HTMX polling, not meta-refresh."""
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
        assert 'http-equiv="refresh"' not in content
        assert "hx-get" in content
        assert "hx-trigger" in content

    def test_status_terminal_state_has_no_auto_refresh(self):
        """Terminal states should not have meta-refresh or HTMX polling."""
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
        assert "hx-trigger" not in content

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

    def test_get_with_patient_record_and_admission_prefills_form(self):
        """GET /ingestao/criar/?patient_record=P100&admission_id=X prefills fields."""
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="P100",
            source_system="tasy",
            name="TEST PREFILL",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-PF",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 4, 10, 14, 0, tzinfo=TZ),
            ward="UTI",
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run") + f"?patient_record=P100&admission_id={admission.pk}"
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "P100" in content
        assert "2026-04-01" in content
        assert "2026-04-10" in content

    def test_get_with_patient_record_and_admission_without_discharge_uses_today(self):
        """GET with admission that has no discharge_date prefills end_date as today."""
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="P101",
            source_system="tasy",
            name="TEST NO DISCHARGE",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-ND",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            ward="UTI",
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run") + f"?patient_record=P101&admission_id={admission.pk}"
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        today_str = date.today().isoformat()
        assert "2026-04-01" in content
        assert today_str in content

    def test_get_without_context_redirects_to_patients(self):
        """GET /ingestao/criar/ without patient_record redirects to /patients/."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.get(url)
        assert response.status_code == 302
        assert "/patients/" in response.url

    def test_get_with_patient_record_but_invalid_admission_redirects(self):
        """GET with valid patient_record but nonexistent admission_id redirects."""
        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run") + "?patient_record=P100&admission_id=99999"
        response = client.get(url)
        assert response.status_code == 302
        assert "/patients/" in response.url

    def test_post_with_admission_context_creates_run(self):
        """POST from contextual flow creates a run with admission context."""
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="P100",
            source_system="tasy",
            name="TEST POST CTX",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-CTX",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 4, 10, 14, 0, tzinfo=TZ),
            ward="UTI",
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "P100",
                "start_date": "2026-04-01",
                "end_date": "2026-04-10",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-CTX",
            },
        )
        assert response.status_code == 302
        run = IngestionRun.objects.get()
        assert run.parameters_json["patient_record"] == "P100"
        assert run.parameters_json["start_date"] == "2026-04-01"
        assert run.parameters_json["end_date"] == "2026-04-10"
        assert run.parameters_json["admission_id"] == str(admission.pk)
        assert run.parameters_json["admission_source_key"] == "ADM-CTX"

    def test_post_with_context_rejects_out_of_bounds_range(self):
        """POST with range outside admission bounds returns validation error."""
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="P100",
            source_system="tasy",
            name="TEST OOB",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-OOB",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 4, 10, 14, 0, tzinfo=TZ),
            ward="UTI",
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "P100",
                "start_date": "2026-03-31",
                "end_date": "2026-04-10",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-OOB",
            },
        )

        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0
        assert "fora dos limites" in response.content.decode("utf-8").lower()

    def test_post_with_context_rejects_patient_mismatch(self):
        """POST with admission from another patient returns validation error."""
        from apps.patients.models import Admission, Patient

        owner = Patient.objects.create(
            patient_source_key="P100",
            source_system="tasy",
            name="OWNER",
        )
        Patient.objects.create(
            patient_source_key="P200",
            source_system="tasy",
            name="OTHER",
        )
        admission = Admission.objects.create(
            patient=owner,
            source_admission_key="ADM-OWN",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 4, 10, 14, 0, tzinfo=TZ),
            ward="UTI",
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "P200",
                "start_date": "2026-04-01",
                "end_date": "2026-04-10",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-OWN",
            },
        )

        assert response.status_code == 200
        assert IngestionRun.objects.count() == 0
        assert "não pertence ao registro" in response.content.decode("utf-8").lower()


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
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="TEST FULLSYNC",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-2026-77",
            source_system="tasy",
            admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 4, 23, 10, 0, tzinfo=TZ),
            ward="UTI",
        )

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
                "admission_id": str(admission.pk),
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
        assert params["admission_id"] == str(admission.pk)
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

    def test_create_run_with_active_full_sync_redirects_to_existing_run(self):
        """POST with same admission context reuses queued/running full-sync run."""
        from apps.patients.models import Admission, Patient

        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="TEST DUPLICATE FULLSYNC",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-2026-88",
            source_system="tasy",
            admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=TZ),
            ward="UTI",
        )

        existing_run = IngestionRun.objects.create(
            status="running",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": date.today().isoformat(),
                "intent": "full_admission_sync",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-2026-88",
            },
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:create_run")
        response = client.post(
            url,
            {
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": date.today().isoformat(),
                "intent": "full_admission_sync",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-2026-88",
            },
        )

        assert response.status_code == 302
        assert response.url == reverse("ingestion:run_status", args=[existing_run.pk])
        assert IngestionRun.objects.count() == 1


@pytest.mark.django_db
class TestRunStatusProgressFeedback:
    """Integration tests for run status progress feedback (PF-2)."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(
            username="testuser_pf_int", password="testpass123"
        )
        client.force_login(user)

    def test_run_status_includes_progress_section(self):
        """Main run_status page includes the progress partial."""
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
        content = response.content.decode("utf-8")
        assert "run-progress" in content

    def test_run_status_uses_htmx_not_meta_refresh(self):
        """Running runs should use HTMX polling, not meta-refresh."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert 'http-equiv="refresh"' not in content
        assert "hx-get" in content
        assert "hx-trigger" in content or "every 3s" in content

    def test_run_status_hx_get_points_to_fragment_url(self):
        """HTMX hx-get should point to the fragment endpoint."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        fragment_url = reverse("ingestion:run_status_fragment", args=[run.pk])
        assert fragment_url in content

    def test_terminal_state_no_htmx_polling(self):
        """Succeeded/failed runs should NOT have HTMX polling active."""
        client = Client()
        self._login(client)
        for status in ["succeeded", "failed"]:
            run = IngestionRun.objects.create(
                status=status,
                parameters_json={"patient_record": "12345"},
            )

            url = reverse("ingestion:run_status", args=[run.pk])
            response = client.get(url)

            content = response.content.decode("utf-8")
            assert "hx-trigger" not in content or \
                   "every 3s" not in content

    def test_queued_run_has_htmx_polling(self):
        """Queued runs should also use HTMX polling."""
        run = IngestionRun.objects.create(
            status="queued",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        assert "hx-get" in content
        assert 'http-equiv="refresh"' not in content

    def test_htmx_script_loaded_in_page(self):
        """Any page extending base.html should load HTMX script."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        assert "htmx.org" in content

    def test_progress_section_present_on_failed_run(self):
        """Failed runs should still show progress section with stage info."""
        run = IngestionRun.objects.create(
            status="failed",
            error_message="Test failure",
            parameters_json={"patient_record": "12345"},
        )
        from django.utils import timezone

        now = timezone.now()
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="gap_planning",
            started_at=now,
            finished_at=now,
            status="failed",
            details_json={"error_type": "ValueError",
                          "error_message": "Bad input"},
        )

        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        assert "run-progress" in content
        assert "Falhou" in content or "failed" in content.lower() or \
               "gap_planning" in content.lower()
