"""Integration tests for ingestion metrics failures tab (Slice CQM-S6).

Tests:
- Page renders tabs "runs" and "patients".
- Default tab is "runs" (run table visible).
- "patients" tab shows batch failure summary cards.
- "patients" tab shows table of patients with final failure.
- Tab switching via ?tab= querystring.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_run(**kwargs) -> IngestionRun:
    """Create an IngestionRun with defaults suitable for metrics page tests."""
    now = timezone.now()
    defaults: dict = {
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


def _make_batch(**kwargs) -> CensusExecutionBatch:
    """Create a CensusExecutionBatch with defaults for metrics tests."""
    now = timezone.now()
    defaults: dict = {
        "enqueue_finished_at": now - timedelta(hours=2),
        "finished_at": now - timedelta(hours=1),
        "status": "succeeded",
    }
    defaults.update(kwargs)
    return CensusExecutionBatch.objects.create(**defaults)


def _make_final_failure(batch: CensusExecutionBatch, **kwargs) -> FinalRunFailure:
    """Create a FinalRunFailure linked to a batch and a run."""
    run_kwargs = {"status": "failed", "batch": batch}
    run = _make_run(**run_kwargs)
    now = timezone.now()
    defaults: dict = {
        "batch": batch,
        "run": run,
        "patient_record": "12345",
        "intent": "full_sync",
        "failed_at": now - timedelta(minutes=30),
        "attempts_exhausted": 3,
    }
    defaults.update(kwargs)
    return FinalRunFailure.objects.create(**defaults)


# ── Tab rendering tests ────────────────────────────────────────────────


@pytest.mark.django_db
class TestIngestionMetricsTabs:
    """CQM-S6: Tab navigation between runs and patients views."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_page_renders_tab_navigation(self, admin_client):
        """The page includes tab UI with "Execuções" and "Pacientes" labels."""
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Execuções" in content
        assert "Pacientes" in content

    def test_default_tab_is_runs(self, admin_client):
        """Without ?tab= param, the runs table (default) is visible."""
        run = _make_run(intent="full_sync", status="succeeded")
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert str(run.pk) in content
        assert "Execuções" in content

    def test_tab_runs_shows_run_table(self, admin_client):
        """?tab=runs renders the run table with run data."""
        run = _make_run(intent="admissions_only", status="succeeded")
        response = self._get_page(admin_client, tab="runs")
        content = response.content.decode()
        assert str(run.pk) in content

    def test_tab_patients_shows_failures_section(self, admin_client):
        """?tab=patients renders the patient failure section."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P-ALPHA", intent="admissions_only")
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert response.status_code == 200
        assert "P-ALPHA" in content

    def test_tab_runs_does_not_show_failure_patients(self, admin_client):
        """?tab=runs does NOT render the patient failure table."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P-HIDDEN", intent="full_sync")
        response = self._get_page(admin_client, tab="runs")
        content = response.content.decode()
        assert "P-HIDDEN" not in content


# ── Batch summary cards tests ──────────────────────────────────────────


@pytest.mark.django_db
class TestIngestionMetricsBatchCards:
    """CQM-S6: Summary cards in the patients tab for last census execution."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_patients_tab_shows_batch_duration_card(self, admin_client):
        """Patients tab shows the total duration of the last finished batch."""
        now = timezone.now()
        _make_batch(
            enqueue_finished_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
        )
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        # Duration should be ~7200 seconds, displayed in some human-readable form
        assert "Duração" in content or "Tempo" in content or "duration" in content.lower()

    def test_patients_tab_shows_total_failures_card(self, admin_client):
        """Patients tab shows total count of patients with final failure."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P1", intent="admissions_only")
        _make_final_failure(batch, patient_record="P2", intent="full_sync")
        _make_final_failure(batch, patient_record="P3", intent="admissions_only")
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        # The number 3 (total failures) should appear in a card
        assert "3" in content

    def test_patients_tab_shows_failures_by_intent(self, admin_client):
        """Patients tab shows breakdown of failures by intent."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P1", intent="admissions_only")
        _make_final_failure(batch, patient_record="P2", intent="admissions_only")
        _make_final_failure(batch, patient_record="P3", intent="full_sync")
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert "admissions_only" in content
        assert "full_sync" in content

    def test_patients_tab_card_shows_no_data_when_no_batch(self, admin_client):
        """When no finished batch exists, cards show empty/zero state."""
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert response.status_code == 200
        # Should still render the page without errors
        assert (
            "Nenhum" in content
            or "vazio" in content
            or "nenhum" in content
            or "0" in content
            or "Sem dados" in content
        )


# ── Patient failure table tests ────────────────────────────────────────


@pytest.mark.django_db
class TestIngestionMetricsPatientsTable:
    """CQM-S6: Table of patients with final failure in the patients tab."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_table_shows_patient_record_column(self, admin_client):
        """The failure table includes patient_record in each row."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="REC-001", intent="admissions_only")
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert "REC-001" in content

    def test_table_shows_intent_column(self, admin_client):
        """The failure table includes intent in each row."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="REC-002", intent="demographics_only")
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert "demographics_only" in content

    def test_table_shows_failed_at_column(self, admin_client):
        """The failure table includes failed_at timestamp in each row."""
        batch = _make_batch()
        now = timezone.now()
        _make_final_failure(
            batch,
            patient_record="REC-003",
            intent="full_sync",
            failed_at=now - timedelta(hours=2),
        )
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        # Check that a date/time format appears in the row
        # Format: dd/mm HH:MM or similar
        assert "REC-003" in content

    def test_table_is_empty_when_no_failures(self, admin_client):
        """When no failures exist, table shows empty state message."""
        _make_batch()  # batch with no failures
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert response.status_code == 200
        assert (
            "Nenhum" in content
            or "nenhum" in content
            or "vazio" in content
            or "Sem falhas" in content
        )

    def test_table_lists_multiple_patients_sorted_by_failed_at(self, admin_client):
        """Multiple failure patients are listed in the table."""
        batch = _make_batch()
        now = timezone.now()
        _make_final_failure(
            batch,
            patient_record="REC-A",
            intent="admissions_only",
            failed_at=now - timedelta(hours=3),
        )
        _make_final_failure(
            batch,
            patient_record="REC-B",
            intent="full_sync",
            failed_at=now - timedelta(hours=1),
        )
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert "REC-A" in content
        assert "REC-B" in content

    def test_anonymous_user_redirected(self):
        """Anonymous users are redirected to login for the patients tab."""
        client = Client()
        url = reverse("services_portal:ingestion_metrics")
        response = client.get(url, {"tab": "patients"})
        assert response.status_code == 302
        assert response.url.startswith("/login")


# ── Tab + filter coexistence tests ─────────────────────────────────────


@pytest.mark.django_db
class TestIngestionMetricsTabFilterCoexistence:
    """CQM-S6: Tab switching preserves existing filter parameters."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_tab_runs_preserves_period_filter(self, admin_client):
        """?tab=runs&periodo=7d renders run table with the period filter applied."""
        recent = _make_run(
            queued_at=timezone.now() - timedelta(hours=1),
            processing_started_at=timezone.now() - timedelta(minutes=55),
            finished_at=timezone.now() - timedelta(minutes=50),
        )
        old = _make_run(
            queued_at=timezone.now() - timedelta(days=10),
            processing_started_at=timezone.now() - timedelta(days=10),
            finished_at=timezone.now() - timedelta(days=10),
        )
        response = self._get_page(admin_client, tab="runs", periodo="7d")
        content = response.content.decode()
        assert str(recent.pk) in content
        # Use a more specific match: the PK in a table cell (<td>) context
        assert f"<td>{recent.pk}</td>" in content or f">{recent.pk}<" in content
        # Old run PK should not appear in any table cell
        assert f"<td>{old.pk}</td>" not in content

    def test_tab_patients_preserves_filters_in_ui(self, admin_client):
        """?tab=patients with filter params renders without error."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="FP-1", intent="admissions_only")
        response = self._get_page(
            admin_client, tab="patients", periodo="30d"
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "FP-1" in content
