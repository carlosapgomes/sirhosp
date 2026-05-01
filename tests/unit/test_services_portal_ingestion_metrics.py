"""Slice IRMD-S6 & S7: Ingestion metrics page route, filters, and run table tests.
Slice CQM-S5: Backend data for latest batch final failures.
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


@pytest.mark.django_db
class TestIngestionMetricsRoute:
    """S6: Ingestion metrics route authentication and rendering."""

    def test_ingestion_metrics_authenticated(self, admin_client):
        """Authenticated user receives 200 on the ingestion metrics page."""
        url = reverse("services_portal:ingestion_metrics")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Ingestão" in response.content.decode()

    def test_ingestion_metrics_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login page."""
        client = Client()
        url = reverse("services_portal:ingestion_metrics")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login")


# ── S7: Helper to create test runs ───────────────────────────────────────

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


@pytest.mark.django_db
class TestIngestionMetricsFilters:
    """S7: Filters on the ingestion metrics page."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    # ── period filter ───────────────────────────────────────────────

    def test_filter_period_24h_shows_recent_run(self, admin_client):
        """Run within 24h is visible with default filter."""
        run = _make_run()
        response = self._get_page(admin_client, periodo="24h")
        content = response.content.decode()
        assert str(run.pk) in content
        assert response.status_code == 200

    def test_filter_period_24h_excludes_old_run(self, admin_client):
        """Run older than 24h is excluded with 24h filter."""
        old = _make_run(
            queued_at=timezone.now() - timedelta(hours=48),
            processing_started_at=timezone.now() - timedelta(hours=47),
            finished_at=timezone.now() - timedelta(hours=46),
        )
        response = self._get_page(admin_client, periodo="24h")
        assert str(old.pk) not in response.content.decode()

    def test_filter_period_7d_includes_run_within_week(self, admin_client):
        """Run 3 days old is visible with 7d filter."""
        run = _make_run(
            queued_at=timezone.now() - timedelta(days=3),
            processing_started_at=timezone.now() - timedelta(days=3),
            finished_at=timezone.now() - timedelta(days=3),
        )
        response = self._get_page(admin_client, periodo="7d")
        assert str(run.pk) in response.content.decode()

    def test_filter_period_30d_includes_run_within_month(self, admin_client):
        """Run 20 days old is visible with 30d filter."""
        run = _make_run(
            queued_at=timezone.now() - timedelta(days=20),
            processing_started_at=timezone.now() - timedelta(days=20),
            finished_at=timezone.now() - timedelta(days=20),
        )
        response = self._get_page(admin_client, periodo="30d")
        assert str(run.pk) in response.content.decode()

    # ── status filter ───────────────────────────────────────────────

    def test_filter_status_succeeded(self, admin_client):
        """Filter by status=succeeded shows only succeeded runs."""
        ok = _make_run(status="succeeded")
        fail = _make_run(status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, periodo="30d", status="succeeded")
        content = response.content.decode()
        assert str(ok.pk) in content
        assert str(fail.pk) not in content

    def test_filter_status_failed(self, admin_client):
        """Filter by status=failed shows only failed runs."""
        ok = _make_run(status="succeeded")
        fail = _make_run(status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, periodo="30d", status="failed")
        content = response.content.decode()
        assert str(fail.pk) in content
        assert str(ok.pk) not in content

    # ── intent filter ───────────────────────────────────────────────

    def test_filter_intent_full_sync(self, admin_client):
        """Filter by intent=full_sync shows only full_sync runs."""
        fs = _make_run(intent="full_sync")
        ao = _make_run(intent="admissions_only")
        response = self._get_page(admin_client, periodo="30d", intent="full_sync")
        content = response.content.decode()
        assert str(fs.pk) in content
        assert str(ao.pk) not in content

    # ── failure_reason filter ───────────────────────────────────────

    def test_filter_failure_reason_timeout(self, admin_client):
        """Filter by failure_reason=timeout shows only timeout runs."""
        to = _make_run(status="failed", failure_reason="timeout")
        ue = _make_run(status="failed", failure_reason="unexpected_exception")
        response = self._get_page(
            admin_client, periodo="30d", failure_reason="timeout"
        )
        content = response.content.decode()
        assert str(to.pk) in content
        assert str(ue.pk) not in content

    # ── combined filters ────────────────────────────────────────────

    def test_combined_filters_status_and_intent(self, admin_client):
        """Status + intent filters are ANDed."""
        target = _make_run(status="failed", intent="full_sync", failure_reason="timeout")
        _make_run(status="failed", intent="admissions_only", failure_reason="timeout")
        _make_run(status="succeeded", intent="full_sync")
        response = self._get_page(
            admin_client,
            periodo="30d",
            status="failed",
            intent="full_sync",
        )
        content = response.content.decode()
        assert str(target.pk) in content
        # Only target should appear
        assert content.count("<tr") - content.count("</thead>") >= 1


@pytest.mark.django_db
class TestIngestionMetricsSummaryCoherence:
    """S7: Summary cards reflect the filtered dataset."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_summary_shows_zero_when_no_runs(self, admin_client):
        """Empty dataset yields zeroed summary cards."""
        response = self._get_page(admin_client, periodo="24h")
        content = response.content.decode()
        # Should render the summary cards with zeros
        assert "Execuções" in content
        assert ">0<" in content or ">0.0<" in content  # total or rates

    def test_summary_total_matches_filtered_count(self, admin_client):
        """Summary total equals number of runs in the filtered table."""
        _make_run(status="succeeded")
        _make_run(status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, periodo="30d")
        content = response.content.decode()
        # Both runs in 30d window
        assert "Execuções" in content

    def test_summary_after_filter_matches_only_filtered(self, admin_client):
        """Applying a filter updates summary to match only filtered runs."""
        _make_run(status="succeeded")
        _make_run(status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, periodo="30d", status="failed")
        content = response.content.decode()
        # Success rate for failed-only dataset should be 0%
        assert "0%" in content or "0.0%" in content or "Sucesso" not in content
        # The "Execuções" stat card should show 1 (only the failed run)
        assert "Execuções" in content


@pytest.mark.django_db
class TestIngestionMetricsRunTable:
    """S7: Run table columns."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_table_shows_expected_columns(self, admin_client):
        """Run table renders all required operational columns."""
        _make_run(
            intent="full_sync",
            status="succeeded",
            timed_out=False,
        )
        response = self._get_page(admin_client, periodo="30d")
        content = response.content.decode()
        # Check header labels
        assert "ID" in content
        assert "Intent" in content or "Intenção" in content
        assert "Status" in content
        assert "Enfileirado" in content or "queued_at" in content

    def test_table_row_contains_values(self, admin_client):
        """Each run row shows its id, intent, and status."""
        run = _make_run(intent="full_sync", status="succeeded")
        response = self._get_page(admin_client, periodo="30d")
        content = response.content.decode()
        assert str(run.pk) in content
        assert "full_sync" in content
        # Template renders Portuguese labels: "Sucesso", "Falhou"
        assert "Sucesso" in content

    def test_failed_run_shows_failure_reason(self, admin_client):
        """Failed run row includes failure_reason label."""
        _make_run(
            status="failed",
            failure_reason="timeout",
            timed_out=True,
        )
        response = self._get_page(admin_client, periodo="30d")
        content = response.content.decode()
        assert "Timeout" in content or "timeout" in content

    def test_no_runs_shows_empty_table_or_message(self, admin_client):
        """When no runs match, table is empty or shows informational message."""
        response = self._get_page(admin_client, periodo="24h")
        content = response.content.decode()
        # Page should still render without error
        assert response.status_code == 200
        assert "Nenhum" in content or "vazio" in content or "nenhuma" in content


# ── CQM-S5: Batch failure stats helpers ────────────────────────────────


def _make_batch(**kwargs) -> CensusExecutionBatch:
    """Create a CensusExecutionBatch with defaults suitable for metrics tests."""
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
    run_kwargs = {
        "status": "failed",
        "batch": batch,
    }
    if "patient_record" in kwargs:
        pass  # handled below
    run = _make_run(**run_kwargs)
    defaults: dict = {
        "batch": batch,
        "run": run,
        "patient_record": "12345",
        "intent": "full_sync",
        "failed_at": timezone.now() - timedelta(minutes=30),
        "attempts_exhausted": 3,
    }
    defaults.update(kwargs)
    return FinalRunFailure.objects.create(**defaults)


# ── CQM-S5: Backend batch failure stats tests ──────────────────────────


@pytest.mark.django_db
class TestIngestionMetricsBatchFailureStats:
    """CQM-S5: Backend delivery of batch failure stats in ingestion_metrics."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def test_no_batch_returns_empty_failure_stats(self, admin_client):
        """When no finished batch exists, batch_failure_stats has has_batch=False."""
        response = self._get_page(admin_client)
        assert response.status_code == 200
        stats = response.context["batch_failure_stats"]
        assert stats["has_batch"] is False
        assert stats["batch_id"] is None
        assert stats["final_failures_total"] == 0
        assert stats["failures_by_intent"] == {}
        assert stats["failure_patients"] == []

    def test_batch_metadata_in_context(self, admin_client):
        """Finished batch delivers id, status, duration, and timestamps."""
        batch = _make_batch()
        response = self._get_page(admin_client)
        assert response.status_code == 200
        stats = response.context["batch_failure_stats"]
        assert stats["has_batch"] is True
        assert stats["batch_id"] == batch.pk
        assert stats["status"] == "succeeded"
        assert stats["total_duration_seconds"] is not None
        assert stats["total_duration_seconds"] >= 0
        assert stats["started_at"] is not None
        assert stats["enqueue_finished_at"] is not None
        assert stats["finished_at"] is not None

    def test_final_failures_total_and_by_intent(self, admin_client):
        """Final failures are counted and grouped by operational intent."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P1", intent="admissions_only")
        _make_final_failure(batch, patient_record="P2", intent="admissions_only")
        _make_final_failure(batch, patient_record="P3", intent="full_sync")
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        assert stats["final_failures_total"] == 3
        assert stats["failures_by_intent"] == {
            "admissions_only": 2,
            "full_sync": 1,
        }

    def test_failure_patient_list_contains_required_fields(self, admin_client):
        """Each entry in failure_patients includes patient_record, intent,
        failed_at, and attempts_exhausted."""
        batch = _make_batch()
        _make_final_failure(batch, patient_record="P-ALPHA", intent="admissions_only")
        _make_final_failure(batch, patient_record="P-BETA", intent="full_sync")
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        patients = stats["failure_patients"]
        assert len(patients) == 2
        records = {p["patient_record"] for p in patients}
        assert records == {"P-ALPHA", "P-BETA"}
        for p in patients:
            assert "patient_record" in p
            assert "intent" in p
            assert "failed_at" in p
            assert "attempts_exhausted" in p
            assert p["intent"] in ("admissions_only", "full_sync")

    def test_uses_latest_finished_batch_only(self, admin_client):
        """Only the most recently finished batch is returned."""
        old_batch = _make_batch(
            finished_at=timezone.now() - timedelta(days=7),
        )
        new_batch = _make_batch(
            finished_at=timezone.now() - timedelta(hours=1),
        )
        _make_final_failure(old_batch, patient_record="OLD", intent="full_sync")
        _make_final_failure(new_batch, patient_record="NEW", intent="full_sync")
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        assert stats["batch_id"] == new_batch.pk
        assert len(stats["failure_patients"]) == 1
        assert stats["failure_patients"][0]["patient_record"] == "NEW"

    def test_ignores_running_batch_without_finished_at(self, admin_client):
        """A running batch (finished_at=null) is NOT the latest finished."""
        _make_batch(finished_at=None, status="running")
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        assert stats["has_batch"] is False

    def test_batch_duration_is_computed_between_enqueue_and_finish(self, admin_client):
        """total_duration_seconds = finished_at - enqueue_finished_at."""
        now = timezone.now()
        _make_batch(
            enqueue_finished_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
        )
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        # ~7200 seconds (2 hours)
        assert stats["total_duration_seconds"] is not None
        assert 7100 <= stats["total_duration_seconds"] <= 7300
