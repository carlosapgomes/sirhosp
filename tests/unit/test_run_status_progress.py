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
