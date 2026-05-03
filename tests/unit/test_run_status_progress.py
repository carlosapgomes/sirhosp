"""Tests for run status progress feedback (Slice PF-1)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


@pytest.mark.django_db
class TestRunStatusFragmentView:
    """Tests for the run_status_fragment endpoint."""

    def _login(self, client):
        from django.contrib.auth.models import User

        user = User.objects.create_user(
            username="testuser_pf1", password="testpass123"
        )
        client.force_login(user)

    def _create_run_with_stages(self):
        """Helper: create a running run with stage metrics."""
        run = IngestionRun.objects.create(
            status="running",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
                "intent": "full_admission_sync",
            },
        )
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
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="evolution_extraction",
            started_at=now,
            finished_at=None,
            status="succeeded",
        )
        return run

    def test_fragment_returns_stages_for_running_run(self):
        """Fragment endpoint returns stage names and statuses."""
        run = self._create_run_with_stages()
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Check that stage info is present
        assert "admissions_capture" in content.lower() or \
            "Captura" in content or \
            "internações" in content.lower()
        # Check Bootstrap structure
        assert "run-progress" in content

    def test_fragment_returns_200_for_run_without_stages(self):
        """Fragment should still render (with appropriate message) for
        runs with no stage metrics yet."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "99999"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should have the progress container
        assert "run-progress" in content

    def test_fragment_404_for_nonexistent_run(self):
        """Nonexistent run_id returns 404."""
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[99999])
        response = client.get(url)

        assert response.status_code == 404

    def test_fragment_requires_authentication(self):
        """Anonymous access redirects to login."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 302
        assert "/login/" in response.url

    def test_fragment_for_failed_run_shows_failed_stage(self):
        """Fragment shows failed stage with error details."""
        run = IngestionRun.objects.create(
            status="failed",
            parameters_json={"patient_record": "12345"},
        )
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
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="evolution_extraction",
            started_at=now,
            finished_at=now,
            status="failed",
            details_json={
                "error_type": "TimeoutError",
                "error_message": "Timeout after 120s",
            },
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should show all stages including the failed one
        assert "admissions_capture" in content.lower() or \
            "Captura" in content
        assert "evolution_extraction" in content.lower() or \
            "Extração" in content or \
            "Evolu" in content


@pytest.mark.django_db
class TestRunStatusViewIncludesStages:
    """Tests for the main run_status view including stage metrics."""

    def _login(self, client):
        from django.contrib.auth.models import User

        user = User.objects.create_user(
            username="testuser_pf2", password="testpass123"
        )
        client.force_login(user)

    def test_run_status_context_includes_stage_metrics(self):
        """run_status view includes stage_metrics in template context.

        PF-1 only adds stage_metrics to the context; the template
        include is done in PF-2, so we verify via context, not HTML.
        """
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        now = timezone.now()
        metric = IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        # stage_metrics is in the template context with the expected metric
        assert "stage_metrics" in response.context
        assert metric in response.context["stage_metrics"]


@pytest.mark.django_db
class TestRunStatusAdmissionDisplay:
    """Tests for human-readable admission display on run status page."""

    def _login(self, client):
        from django.contrib.auth.models import User

        user = User.objects.create_user(
            username="testuser_admdisp", password="testpass123"
        )
        client.force_login(user)

    def test_shows_patient_name_and_bed_when_admission_resolved(self):
        """Status page shows patient name and bed when admission is found."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from apps.patients.models import Admission, Patient

        tz = ZoneInfo("America/Sao_Paulo")
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="Maria Silva",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-999",
            source_system="tasy",
            admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=tz),
            discharge_date=datetime(2026, 4, 23, 10, 0, tzinfo=tz),
            bed="301-A",
            ward="UTI",
        )

        run = IngestionRun.objects.create(
            status="succeeded",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": "2026-04-23",
                "intent": "full_admission_sync",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-999",
            },
            events_processed=5,
            events_created=3,
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should show patient name
        assert "Maria Silva" in content
        # Should show bed
        assert "301-A" in content
        # Should show formatted period with discharge
        assert "15/04/2026" in content
        assert "23/04/2026" in content
        assert "→" in content
        # Should NOT show the raw admission source key
        assert "ADM-999" not in content

    def test_shows_atual_when_no_discharge_date(self):
        """Status page shows '→ atual' when admission has no discharge date."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from apps.patients.models import Admission, Patient

        tz = ZoneInfo("America/Sao_Paulo")
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="João Souza",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-888",
            source_system="tasy",
            admission_date=datetime(2026, 5, 1, 14, 0, tzinfo=tz),
            discharge_date=None,
            bed="202-B",
            ward="Enfermaria",
        )

        run = IngestionRun.objects.create(
            status="running",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-05-01",
                "end_date": "2026-05-03",
                "intent": "full_admission_sync",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-888",
            },
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert "João Souza" in content
        assert "202-B" in content
        assert "01/05/2026" in content
        assert "→ atual" in content
        assert "ADM-888" not in content

    def test_fallback_to_source_key_when_admission_not_found(self):
        """Status page shows source_key when admission_id doesn't resolve."""
        run = IngestionRun.objects.create(
            status="succeeded",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-15",
                "end_date": "2026-04-23",
                "intent": "full_admission_sync",
                "admission_id": "99999",
                "admission_source_key": "ADM-2026-77",
            },
            events_processed=5,
            events_created=3,
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Fallback: shows the source key (no admission resolved)
        assert "ADM-2026-77" in content
        # No misleading period section
        assert "Período da internação" not in content
        # No misleading patient section
        assert "Paciente:" not in content

    def test_no_admission_info_when_no_admission_context(self):
        """Status page without admission context shows no extra info."""
        run = IngestionRun.objects.create(
            status="succeeded",
            intent="admissions_only",
            parameters_json={
                "patient_record": "12345",
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
        content = response.content.decode("utf-8")

        # No admission context means no "Paciente:" or "Período da internação"
        assert "Paciente:" not in content
        assert "Período da internação" not in content

    def test_shows_name_without_bed_when_bed_is_empty(self):
        """Status page shows patient name even when bed is empty."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from apps.patients.models import Admission, Patient

        tz = ZoneInfo("America/Sao_Paulo")
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="Carlos Lima",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-777",
            source_system="tasy",
            admission_date=datetime(2026, 3, 10, 9, 0, tzinfo=tz),
            discharge_date=None,
            bed="",
            ward="",
        )

        run = IngestionRun.objects.create(
            status="succeeded",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-03-10",
                "end_date": "2026-03-15",
                "intent": "full_admission_sync",
                "admission_id": str(admission.pk),
                "admission_source_key": "ADM-777",
            },
            events_processed=2,
            events_created=1,
        )

        client = Client()
        self._login(client)
        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should show patient name
        assert "Carlos Lima" in content
        # Should show period
        assert "10/03/2026" in content
        assert "→ atual" in content
        # Should NOT include the bed separator right after the patient name
        assert "Carlos Lima —" not in content
