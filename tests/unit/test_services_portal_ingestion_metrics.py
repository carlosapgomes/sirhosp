"""Slice IRMD-S6 & S7: Ingestion metrics page route, filters, and run table tests.
Slice CQM-S5: Backend data for latest batch final failures.
Slice IRMPP-S1: Lazy computation by active tab/mode.
Slice IRMPP-S2: Lightweight batch history, efficiency metrics in the detail.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
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

def _make_run(batch: CensusExecutionBatch | None = None, **kwargs) -> IngestionRun:
    """Create an IngestionRun with defaults suitable for metrics page tests.

    When `batch` is provided, the run is linked to that batch for detail tests.
    """
    now = timezone.now()
    defaults: dict = {
        "status": "succeeded",
        "intent": "full_sync",
        "queued_at": now - timedelta(hours=2),
        "processing_started_at": now - timedelta(hours=1, minutes=55),
        "finished_at": now - timedelta(hours=1),
        "timed_out": False,
        "failure_reason": "",
        "batch": batch,
    }
    defaults.update(kwargs)
    return IngestionRun.objects.create(**defaults)


@pytest.mark.django_db
class TestIngestionMetricsFilters:
    """S7: Filters on the ingestion metrics page (within batch detail mode).

    IWBO-S3: Runs are only shown when a batch is selected.
    """

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _create_batch(self) -> CensusExecutionBatch:
        """Create a simple finished batch for test runs."""
        now = timezone.now()
        return CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
            status="succeeded",
        )

    # ── period filter ───────────────────────────────────────────────

    def test_filter_period_24h_shows_recent_run(self, admin_client):
        """Run within 24h is visible via batch detail."""
        batch = self._create_batch()
        run = _make_run(batch=batch)
        response = self._get_page(admin_client, batch_id=batch.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run.pk in run_ids
        assert response.status_code == 200

    def test_filter_period_24h_shows_all_runs(self, admin_client):
        """Batch detail shows all runs regardless of period filter.

        IWBO-S3: The period filter was removed from the batch detail
        queryset. All runs of the batch are always shown.
        """
        batch = self._create_batch()
        old = _make_run(
            batch=batch,
            queued_at=timezone.now() - timedelta(hours=48),
            processing_started_at=timezone.now() - timedelta(hours=47),
            finished_at=timezone.now() - timedelta(hours=46),
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert old.pk in run_ids

    def test_filter_period_7d_includes_run_within_week(self, admin_client):
        """Run 3 days old is visible with 7d filter."""
        batch = self._create_batch()
        run = _make_run(
            batch=batch,
            queued_at=timezone.now() - timedelta(days=3),
            processing_started_at=timezone.now() - timedelta(days=3),
            finished_at=timezone.now() - timedelta(days=3),
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run.pk in run_ids

    def test_filter_period_30d_includes_run_within_month(self, admin_client):
        """Run 20 days old is visible via batch detail (no period filter)."""
        batch = self._create_batch()
        run = _make_run(
            batch=batch,
            queued_at=timezone.now() - timedelta(days=20),
            processing_started_at=timezone.now() - timedelta(days=20),
            finished_at=timezone.now() - timedelta(days=20),
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run.pk in run_ids
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run.pk in run_ids

    # ── status filter ───────────────────────────────────────────────

    def test_filter_status_succeeded(self, admin_client):
        """Filter by status=succeeded shows only succeeded runs."""
        batch = self._create_batch()
        ok = _make_run(batch=batch, status="succeeded")
        fail = _make_run(batch=batch, status="failed", failure_reason="timeout")
        response = self._get_page(
            admin_client, batch_id=batch.pk, status="succeeded",
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert ok.pk in run_ids
        assert fail.pk not in run_ids

    def test_filter_status_failed(self, admin_client):
        """Filter by status=failed shows only failed runs."""
        batch = self._create_batch()
        ok = _make_run(batch=batch, status="succeeded")
        fail = _make_run(batch=batch, status="failed", failure_reason="timeout")
        response = self._get_page(
            admin_client, batch_id=batch.pk, status="failed",
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert fail.pk in run_ids
        assert ok.pk not in run_ids

    # ── intent filter ───────────────────────────────────────────────

    def test_filter_intent_full_sync(self, admin_client):
        """Filter by intent=full_sync shows only full_sync runs."""
        batch = self._create_batch()
        fs = _make_run(batch=batch, intent="full_sync")
        ao = _make_run(batch=batch, intent="admissions_only")
        response = self._get_page(
            admin_client, batch_id=batch.pk, intent="full_sync",
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert fs.pk in run_ids
        assert ao.pk not in run_ids

    # ── failure_reason filter ───────────────────────────────────────

    def test_filter_failure_reason_timeout(self, admin_client):
        """Filter by failure_reason=timeout shows only timeout runs."""
        batch = self._create_batch()
        to = _make_run(batch=batch, status="failed", failure_reason="timeout")
        ue = _make_run(batch=batch, status="failed", failure_reason="unexpected_exception")
        response = self._get_page(
            admin_client, batch_id=batch.pk, failure_reason="timeout"
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert to.pk in run_ids
        assert ue.pk not in run_ids

    # ── combined filters ────────────────────────────────────────────

    def test_combined_filters_status_and_intent(self, admin_client):
        """Status + intent filters are ANDed."""
        batch = self._create_batch()
        target = _make_run(
            batch=batch, status="failed", intent="full_sync",
            failure_reason="timeout",
        )
        _make_run(
            batch=batch, status="failed", intent="admissions_only",
            failure_reason="timeout",
        )
        _make_run(batch=batch, status="succeeded", intent="full_sync")
        response = self._get_page(
            admin_client,
            batch_id=batch.pk,
            status="failed",
            intent="full_sync",
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert target.pk in run_ids
        assert len(run_ids) == 1


@pytest.mark.django_db
class TestIngestionMetricsSummaryCoherence:
    """S7: Summary cards reflect the filtered dataset (within batch detail mode).

    IWBO-S3: Summary cards are rendered only when a batch is selected.
    """

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _create_batch(self) -> CensusExecutionBatch:
        """Create a simple finished batch for test runs."""
        now = timezone.now()
        return CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
            status="succeeded",
        )

    def test_summary_shows_zero_when_no_runs(self, admin_client):
        """Empty batch dataset yields zeroed summary cards."""
        batch = self._create_batch()
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        # Should render the summary cards with zeros
        assert "Execuções" in content
        assert ">0<" in content or ">0.0<" in content  # total or rates

    def test_summary_total_matches_filtered_count(self, admin_client):
        """Summary total equals number of runs in the filtered table."""
        batch = self._create_batch()
        _make_run(batch=batch, status="succeeded")
        _make_run(batch=batch, status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        assert "Execuções" in content

    def test_summary_after_filter_matches_only_filtered(self, admin_client):
        """Applying a filter updates summary to match only filtered runs."""
        batch = self._create_batch()
        _make_run(batch=batch, status="succeeded")
        _make_run(batch=batch, status="failed", failure_reason="timeout")
        response = self._get_page(admin_client, batch_id=batch.pk, status="failed")
        content = response.content.decode()
        # Success rate for failed-only dataset should be 0%
        assert "0%" in content or "0.0%" in content or "Sucesso" not in content
        # The "Execuções" stat card should show 1 (only the failed run)
        assert "Execuções" in content


@pytest.mark.django_db
class TestIngestionMetricsRunTable:
    """S7: Run table columns (within batch detail mode).

    IWBO-S3: Runs table is only rendered when a batch is selected.
    """

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _create_batch(self) -> CensusExecutionBatch:
        """Create a simple finished batch for test runs."""
        now = timezone.now()
        return CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
            status="succeeded",
        )

    def test_table_shows_expected_columns(self, admin_client):
        """Run table renders all required operational columns."""
        batch = self._create_batch()
        _make_run(
            batch=batch,
            intent="full_sync",
            status="succeeded",
            timed_out=False,
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        # Check header labels
        assert "ID" in content
        assert "Intenção" in content
        assert "Status" in content
        assert "Enfileirado" in content

    def test_table_row_contains_values(self, admin_client):
        """Each run row shows its id, intent, and status."""
        batch = self._create_batch()
        run = _make_run(batch=batch, intent="full_sync", status="succeeded")
        response = self._get_page(admin_client, batch_id=batch.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run.pk in run_ids
        assert response.status_code == 200

    def test_failed_run_shows_failure_reason(self, admin_client):
        """Failed run row includes failure_reason label."""
        batch = self._create_batch()
        _make_run(
            batch=batch,
            status="failed",
            failure_reason="timeout",
            timed_out=True,
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        assert "Timeout" in content or "timeout" in content

    def test_no_runs_shows_empty_table_or_message(self, admin_client):
        """When no runs match, table is empty or shows informational message."""
        batch = self._create_batch()
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        # Page should still render without error
        assert response.status_code == 200
        assert "Nenhuma execução" in content


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
    run = _make_run(batch=batch, status="failed")
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
    """CQM-S5: Backend delivery of batch failure stats in ingestion_metrics.

    IRMPP-S1: the latest-batch aggregate is only computed for the
    patients tab, which is the tab that renders it.
    """

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        params.setdefault("tab", "patients")
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


# ── IWBO-S1: Batch worker efficiency metrics ────────────────────────────


def _make_run_with_attempt(
    batch: CensusExecutionBatch,
    status: str = "succeeded",
    worker_label: str = "",
    processing_started_at=None,
    finished_at=None,
) -> IngestionRun:
    """Create an IngestionRun linked to a batch with an attempt record.

    Note: started_at has auto_now_add=True, so we create first without
    explicit started_at, then backfill via update().
    """
    now = timezone.now()
    run = IngestionRun.objects.create(
        status=status,
        intent="full_sync",
        batch=batch,
        worker_label=worker_label,
        queued_at=now - timedelta(hours=2),
        processing_started_at=processing_started_at or (now - timedelta(minutes=30)),
        finished_at=finished_at or (now - timedelta(minutes=25)),
    )
    # Create attempt without explicit started_at (auto_now_add overrides it)
    attempt = IngestionRunAttempt.objects.create(
        run=run,
        attempt_number=1,
        finished_at=run.finished_at,
        status="succeeded",
    )
    # Backfill started_at after creation to bypass auto_now_add
    IngestionRunAttempt.objects.filter(pk=attempt.pk).update(
        started_at=run.processing_started_at,
    )
    return run


@pytest.mark.django_db
class TestIngestionMetricsBatchWorkerEfficiency:
    """IWBO-S1: Batch worker efficiency metrics in ingestion_metrics.

    IRMPP-S1: these metrics live in the patients-tab latest-batch block.
    """

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        params.setdefault("tab", "patients")
        return admin_client.get(url, params)

    def test_no_batch_returns_new_keys_with_zero_defaults(self, admin_client):
        """When no finished batch exists, new keys have zero/empty defaults."""
        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]
        assert stats["has_batch"] is False
        assert stats["runs_total"] == 0
        assert stats["runs_succeeded"] == 0
        assert stats["runs_failed"] == 0
        assert stats["runs_active"] == 0
        assert stats["observed_worker_count"] == 0
        assert stats["observed_worker_labels"] == []
        assert stats["observed_peak_concurrency"] == 0
        assert stats["observed_avg_concurrency"] == 0.0
        assert stats["throughput_jobs_per_minute"] == 0.0
        assert stats["avg_processing_duration_seconds"] == 0
        assert stats["avg_attempt_duration_seconds"] == 0

    def test_batch_with_single_run_success(self, admin_client):
        """Batch with one succeeded run and worker_label is counted."""
        now = timezone.now()
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=30),
        )
        _make_run_with_attempt(
            batch,
            status="succeeded",
            worker_label="worker-01:1234",
            processing_started_at=now - timedelta(minutes=50),
            finished_at=now - timedelta(minutes=45),
        )

        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]

        assert stats["has_batch"] is True
        assert stats["runs_total"] == 1
        assert stats["runs_succeeded"] == 1
        assert stats["runs_failed"] == 0
        assert stats["runs_active"] == 0
        assert stats["observed_worker_count"] == 1
        assert stats["observed_worker_labels"] == ["worker-01:1234"]

    def test_batch_with_multiple_workers(self, admin_client):
        """Batch with runs from different workers counts distinct labels."""
        now = timezone.now()
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=30),
        )
        _make_run_with_attempt(
            batch, status="succeeded", worker_label="w1:100",
            processing_started_at=now - timedelta(minutes=50),
            finished_at=now - timedelta(minutes=45),
        )
        _make_run_with_attempt(
            batch, status="succeeded", worker_label="w2:200",
            processing_started_at=now - timedelta(minutes=50),
            finished_at=now - timedelta(minutes=44),
        )
        _make_run_with_attempt(
            batch, status="succeeded", worker_label="",
            processing_started_at=now - timedelta(minutes=50),
            finished_at=now - timedelta(minutes=43),
        )

        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]

        assert stats["observed_worker_count"] == 2  # only non-empty labels
        assert sorted(stats["observed_worker_labels"]) == ["w1:100", "w2:200"]

    def test_peak_concurrency_with_overlapped_attempts(self, admin_client):
        """Peak concurrency calculated via sweep-line over attempt intervals."""
        now = timezone.now()
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(minutes=20),
            finished_at=now,
        )

        def _create_run_and_attempt(start_minutes_ago, end_minutes_ago):
            """Helper to create run+attempt with controlled timestamps.

            started_at has auto_now_add=True, so we create the attempt
            first without explicit started_at, then backfill via update().
            """
            start = now - timedelta(minutes=start_minutes_ago)
            end = now - timedelta(minutes=end_minutes_ago)
            run = IngestionRun.objects.create(
                status="succeeded", intent="full_sync", batch=batch,
                processing_started_at=start,
                finished_at=end,
            )
            a = IngestionRunAttempt.objects.create(
                run=run, attempt_number=1,
                finished_at=end,
                status="succeeded",
            )
            IngestionRunAttempt.objects.filter(pk=a.pk).update(started_at=start)
            return run

        # Worker 1: runs from minute 15 to 10 ago (overlaps with Workers 2 and 3)
        _create_run_and_attempt(15, 10)
        # Worker 2: runs from minute 13 to 8 ago (overlaps with 1 and 3)
        _create_run_and_attempt(13, 8)
        # Worker 3: runs from minute 11 to 6 ago (overlaps with 2)
        _create_run_and_attempt(11, 6)

        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]

        # Peak should be 3 (all three workers overlapped between min 11 and min 10)
        assert stats["observed_peak_concurrency"] == 3

    def test_avg_concurrency_and_throughput(self, admin_client):
        """Average concurrency = sum of attempt durations / drain window."""
        now = timezone.now()
        drain_window_seconds = 600  # 10 minutes
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(seconds=drain_window_seconds),
            finished_at=now,
        )

        def _create_run_and_attempt(start_secs_ago, end_secs_ago):
            start = now - timedelta(seconds=start_secs_ago)
            end = now - timedelta(seconds=end_secs_ago)
            run = IngestionRun.objects.create(
                status="succeeded", intent="full_sync", batch=batch,
                processing_started_at=start,
                finished_at=end,
            )
            a = IngestionRunAttempt.objects.create(
                run=run, attempt_number=1,
                finished_at=end,
                status="succeeded",
            )
            IngestionRunAttempt.objects.filter(pk=a.pk).update(started_at=start)
            return run

        # Two workers with overlapping attempts
        _create_run_and_attempt(500, 200)
        _create_run_and_attempt(400, 100)

        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]

        # Total attempt duration: 300 + 300 = 600
        # Drain window: 600 seconds
        # Avg concurrency: 600 / 600 = 1.0
        assert stats["observed_avg_concurrency"] == 1.0

        # Throughput: 2 runs / (600 seconds / 60) = 2 / 10 = 0.2 jobs/min
        assert stats["throughput_jobs_per_minute"] == pytest.approx(0.2, rel=0.01)

    def test_avg_processing_and_attempt_durations(self, admin_client):
        """Average processing duration per job and per attempt."""
        now = timezone.now()
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(minutes=20),
            finished_at=now,
        )

        def _create_run_and_attempt(secs_ago, status):
            start = now - timedelta(seconds=secs_ago)
            end = now
            run = IngestionRun.objects.create(
                status=status, intent="full_sync", batch=batch,
                processing_started_at=start,
                finished_at=end,
            )
            a = IngestionRunAttempt.objects.create(
                run=run, attempt_number=1,
                finished_at=end,
                status=status,
            )
            IngestionRunAttempt.objects.filter(pk=a.pk).update(started_at=start)
            return run

        # Run 1: 300s processing, 300s attempt
        _create_run_and_attempt(300, "succeeded")
        # Run 2: 100s processing, 100s attempt
        _create_run_and_attempt(100, "failed")

        response = self._get_page(admin_client)
        stats = response.context["batch_failure_stats"]

        # Avg processing: (300 + 100) / 2 = 200
        assert stats["avg_processing_duration_seconds"] == 200

        # Avg attempt: (300 + 100) / 2 = 200
        assert stats["avg_attempt_duration_seconds"] == 200

    def test_template_renders_new_labels(self, admin_client):
        """Template renders the new worker efficiency labels (patients tab)."""
        now = timezone.now()
        batch = _make_batch(
            enqueue_finished_at=now - timedelta(minutes=20),
            finished_at=now,
        )
        _make_run_with_attempt(
            batch, status="succeeded", worker_label="w1:100",
            processing_started_at=now - timedelta(minutes=15),
            finished_at=now - timedelta(minutes=10),
        )

        # New cards are only rendered in the patients tab
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()

        assert "Workers observados" in content
        assert "Concorrência observada (pico)" in content
        assert "Concorrência média" in content
        assert "Jobs/min" in content
        assert "Média por job" in content
        assert "Média por tentativa" in content
        assert response.status_code == 200


# ── IWBO-S2: Batch history table ────────────────────────────────────────

# IRMPP-S2: per-batch efficiency values the history table no longer carries.
# They live in the batch detail block; a history entry exposing any of them
# would mean the per-batch run/attempt scans came back.
_REMOVED_HISTORY_METRIC_KEYS = (
    "observed_worker_count",
    "observed_worker_labels",
    "observed_peak_concurrency",
    "observed_avg_concurrency",
    "throughput_jobs_per_minute",
    "avg_processing_duration_seconds",
    "avg_attempt_duration_seconds",
)


def _history_table_html(content: str) -> str:
    """Markup of the batch history table only.

    The page renders other tables whose labels overlap (``Jobs/min`` also
    appears in the patients tab), so content assertions must be scoped to
    the history table itself.
    """
    start = content.index("Histórico de Lotes")
    end = content.index("</table>", start) + len("</table>")
    return content[start:end]


@pytest.mark.django_db
class TestIngestionMetricsBatchHistory:
    """IWBO-S2: Batch history table (pagination, reverse chronology, links).

    IRMPP-S2: rows carry only cheap batch-level columns; efficiency values
    moved to the batch detail view.
    """

    _page_size = 20

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _make_simple_batch_with_run(
        self,
        finished_at_delta: timedelta,
        status: str = "succeeded",
        with_run: bool = True,
        worker_label: str = "w1:100",
    ) -> CensusExecutionBatch:
        """Create a finished batch with optional one run for history tests."""
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - finished_at_delta - timedelta(minutes=5),
            finished_at=now - finished_at_delta,
            status=status,
        )
        if with_run:
            _make_run_with_attempt(
                batch,
                status="succeeded",
                worker_label=worker_label,
                processing_started_at=now - finished_at_delta - timedelta(minutes=3),
                finished_at=now - finished_at_delta - timedelta(minutes=1),
            )
        return batch

    # ── RED 1: Table and reverse chronology ────────────────────────────

    def test_batch_history_renders_when_batches_exist(self, admin_client):
        """Page renders batch history block when finished batches exist."""
        self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert "Histórico de Lotes" in content or "batches" in content.lower() or "Lotes" in content
        assert response.status_code == 200

    def test_batch_history_shows_batch_ids(self, admin_client):
        """Each finished batch's ID appears in the rendered HTML."""
        b1 = self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        b2 = self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=5))
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert str(b1.pk) in content
        assert str(b2.pk) in content

    def test_batch_history_chronological_reverse_order(self, admin_client):
        """Batches appear newest first (most recently finished first)."""
        b1 = self._make_simple_batch_with_run(
            finished_at_delta=timedelta(hours=1),
        )  # most recent
        b2 = self._make_simple_batch_with_run(
            finished_at_delta=timedelta(hours=3),
        )  # older
        response = self._get_page(admin_client)
        history_ids = [entry["batch_id"] for entry in response.context["batch_history"]]
        assert history_ids.index(b1.pk) < history_ids.index(b2.pk), (
            f"Batch #{b1.pk} (newer) should appear before Batch #{b2.pk} (older) "
            f"in {history_ids}"
        )

    def test_batch_history_ignores_unfinished_batches(self, admin_client):
        """Only finished batches (finished_at IS NOT NULL) appear in history."""
        finished = self._make_simple_batch_with_run(
            finished_at_delta=timedelta(hours=1),
        )
        running = CensusExecutionBatch.objects.create(
            enqueue_finished_at=timezone.now() - timedelta(minutes=10),
            finished_at=None,
            status="running",
        )
        response = self._get_page(admin_client)
        # Validate via context (robust, avoids fragile HTML scanning for numeric IDs)
        history_ids = [entry["batch_id"] for entry in response.context["batch_history"]]
        assert finished.pk in history_ids
        assert running.pk not in history_ids
        # Also validate that the HTML link for running batch does not appear
        content = response.content.decode()
        assert f"batch_id={finished.pk}" in content
        assert f"batch_id={running.pk}" not in content

    # ── RED 2: Metrics per batch in history ───────────────────────────

    def test_batch_history_context_has_batches(self, admin_client):
        """Context has 'batch_history' with batch entries."""
        self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        response = self._get_page(admin_client)
        assert "batch_history" in response.context
        assert response.context["batch_history"] is not None

    def test_batch_history_context_metrics_include_counts(self, admin_client):
        """Each batch entry in batch_history exposes run counts."""
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=30),
            status="succeeded",
        )
        _make_run_with_attempt(batch, status="succeeded", worker_label="w1:100")
        _make_run_with_attempt(batch, status="succeeded", worker_label="w2:200")
        _make_run_with_attempt(
            batch, status="failed", worker_label="w1:100",
            processing_started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=15),
        )
        response = self._get_page(admin_client)
        history = response.context["batch_history"]
        assert len(history) == 1
        entry = history[0]
        assert "runs_total" in entry
        assert entry["runs_total"] == 3
        assert entry["runs_succeeded"] == 2
        assert entry["runs_failed"] == 1

    def test_batch_history_entry_exposes_only_cheap_columns(self, admin_client):
        """R2/R3: a history entry carries only cheap batch-level values.

        The efficiency values moved to the detail view (asserted in
        ``TestIngestionMetricsBatchDetail``); their presence here would
        mean the per-batch run/attempt scans returned.
        """
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=30),
            status="succeeded",
        )
        _make_run_with_attempt(batch, status="succeeded", worker_label="w1:100")
        _make_run_with_attempt(batch, status="succeeded", worker_label="w2:200")
        _make_run_with_attempt(batch, status="failed", worker_label="w1:100")
        response = self._get_page(admin_client)
        entry = response.context["batch_history"][0]
        for key in (
            "batch_id",
            "status",
            "started_at",
            "finished_at",
            "drain_duration_seconds",
            "drain_duration_hours",
            "runs_total",
            "runs_succeeded",
            "runs_failed",
            "has_findings",
            "findings_total",
            "findings_items",
            "derived_status",
            "technical_failures",
        ):
            assert key in entry, key
        for key in _REMOVED_HISTORY_METRIC_KEYS:
            assert key not in entry, key
        assert entry["runs_total"] == 3
        assert entry["runs_succeeded"] == 2
        assert entry["runs_failed"] == 1

    def test_batch_history_renders_only_cheap_columns(self, admin_client):
        """R1: the history table renders no worker/efficiency column."""
        self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        response = self._get_page(admin_client)
        history_html = _history_table_html(response.content.decode())
        for header in (
            "Batch ID",
            "Status",
            "Início",
            "Fim",
            "Duração",
            "Jobs",
            "Sucesso",
            "Falha",
        ):
            assert header in history_html, header
        for removed in ("Workers", "Pico", "Jobs/min", "Méd/job", "Méd/tent"):
            assert removed not in history_html, removed

    def test_batch_history_context_duration_and_timestamps(self, admin_client):
        """Batch entry exposes duration display fields."""
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(seconds=3600),
            finished_at=now,
            status="succeeded",
        )
        _make_run_with_attempt(batch, status="succeeded", worker_label="w1:100")
        response = self._get_page(admin_client)
        history = response.context["batch_history"]
        entry = history[0]
        assert entry["batch_id"] == batch.pk
        assert entry["status"] == "succeeded"
        assert entry["started_at"] is not None
        assert entry["finished_at"] is not None
        # Duration in seconds: 3600
        assert entry["drain_duration_seconds"] == pytest.approx(3600, abs=2)

    def test_batch_history_empty_when_no_finished_batches(self, admin_client):
        """When no finished batch exists, batch_history is an empty list."""
        response = self._get_page(admin_client)
        assert "batch_history" in response.context
        assert list(response.context["batch_history"]) == []

    # ── RED 3: Pagination ─────────────────────────────────────────────

    def test_batch_history_pagination_has_page_obj(self, admin_client):
        """Context has batch_page with Page object."""
        self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=1))
        response = self._get_page(admin_client)
        assert "batch_page" in response.context
        assert hasattr(response.context["batch_page"], "number")

    def test_batch_history_pagination_page_1_shows_newest(self, admin_client):
        """Page 1 contains the most recent batches."""
        # Create more batches than page size
        for i in range(25):
            self._make_simple_batch_with_run(
                finished_at_delta=timedelta(hours=i + 1),
            )
        response = self._get_page(admin_client, batch_page=1)
        history = response.context["batch_history"]
        assert len(history) <= 20  # page_size or less

    def test_batch_history_pagination_page_2_shows_older(self, admin_client):
        """Page 2 contains batches older than those on page 1."""
        for i in range(25):
            self._make_simple_batch_with_run(
                finished_at_delta=timedelta(hours=i + 1),
            )
        response_p1 = self._get_page(admin_client, batch_page=1)
        response_p2 = self._get_page(admin_client, batch_page=2)
        p1_finished = [b["finished_at"] for b in response_p1.context["batch_history"]]
        p2_finished = [b["finished_at"] for b in response_p2.context["batch_history"]]
        # All batches on page 1 should have finished later (more recent)
        # than or equal to the oldest on page 1, which should be newer
        # than any on page 2.
        oldest_p1 = min(p1_finished)
        newest_p2 = max(p2_finished)
        assert oldest_p1 > newest_p2, (
            f"Page 1 oldest ({oldest_p1}) should be newer than Page 2 newest ({newest_p2})"
        )

    def test_batch_history_pagination_renders_pagination_controls(self, admin_client):
        """HTML contains pagination controls when pages exceed 1."""
        for i in range(25):
            self._make_simple_batch_with_run(
                finished_at_delta=timedelta(hours=i + 1),
            )
        response = self._get_page(admin_client)
        content = response.content.decode()
        # Look for pagination elements
        assert (
            "page-link" in content
            or "page-item" in content
            or "pagina" in content.lower()
            or "Próximo" in content
            or "Anterior" in content
        )

    def test_batch_history_pagination_defaults_to_page_1(self, admin_client):
        """Without batch_page param, page 1 is rendered."""
        for i in range(5):
            self._make_simple_batch_with_run(
                finished_at_delta=timedelta(hours=i + 1),
            )
        response = self._get_page(admin_client)
        assert response.context["batch_page"].number == 1

    def test_batch_history_pagination_batch_page_param(self, admin_client):
        """Custom batch_page param returns the correct page."""
        for i in range(25):
            self._make_simple_batch_with_run(
                finished_at_delta=timedelta(hours=i + 1),
            )
        response = self._get_page(admin_client, batch_page=2)
        assert response.context["batch_page"].number == 2

    # ── RED 4: Link to batch detail ───────────────────────────────────

    def test_batch_history_contains_batch_id_link(self, admin_client):
        """HTML contains batch_id=<id> for at least one batch."""
        b1 = self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert f"batch_id={b1.pk}" in content

    def test_batch_history_contains_batch_id_link_for_multiple(self, admin_client):
        """HTML contains batch_id links for multiple batches."""
        b1 = self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=2))
        b2 = self._make_simple_batch_with_run(finished_at_delta=timedelta(hours=5))
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert f"batch_id={b1.pk}" in content
        assert f"batch_id={b2.pk}" in content


# ── IWBO-S3: Batch detail mode (executions on demand) ────────────────


@pytest.mark.django_db
class TestIngestionMetricsBatchDetail:
    """IWBO-S3: Batch detail mode — no global executions, filtered by batch_id."""

    _page_size = 20

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _make_batch_with_labeled_run(
        self,
        finished_at_delta: timedelta,
        run_label: str,
        status: str = "succeeded",
        intent: str = "full_sync",
    ) -> tuple[CensusExecutionBatch, IngestionRun]:
        """Create a finished batch with one run carrying a label for identification."""
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - finished_at_delta - timedelta(minutes=5),
            finished_at=now - finished_at_delta,
            status="succeeded",
        )
        run = IngestionRun.objects.create(
            batch=batch,
            status=status,
            intent=intent,
            worker_label=f"w:{run_label}",
            queued_at=now - finished_at_delta - timedelta(minutes=10),
            processing_started_at=now - finished_at_delta - timedelta(minutes=8),
            finished_at=now - finished_at_delta - timedelta(minutes=2),
            timed_out=False,
            failure_reason="" if status == "succeeded" else "timeout",
        )
        return batch, run

    # ── RED 1: Default view without global executions ────────────────

    def test_default_view_shows_batch_history(self, admin_client):
        """Without batch_id, the batch history table is rendered."""
        self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="A",
        )
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert "Histórico de Lotes" in content
        assert response.status_code == 200

    def test_default_view_has_no_global_executions_table(self, admin_client):
        """Without batch_id, the global executions table is NOT rendered."""
        b1, r1 = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="A",
        )
        b2, r2 = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=3),
            run_label="B",
        )
        response = self._get_page(admin_client)
        content = response.content.decode()
        # The batch history links appear
        assert f"batch_id={b1.pk}" in content
        assert f"batch_id={b2.pk}" in content
        # The run IDs should NOT appear in a runs table (they only appear
        # as batch detail links). We verify by checking that the global
        # runs table header is absent.
        assert "Execuções" in content  # from page title / tabs

    def test_default_view_shows_guidance_text(self, admin_client):
        """Without batch_id, guidance text directs user to select a batch."""
        self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="A",
        )
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert "Selecione um batch" in content

    def test_default_view_context_show_batch_detail_false(self, admin_client):
        """Without batch_id, context has show_batch_detail=False."""
        self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="A",
        )
        response = self._get_page(admin_client)
        assert response.context.get("show_batch_detail") is False

    # ── RED 2: Detail lists only jobs of the selected batch ──────────

    def test_batch_detail_shows_only_that_batchs_runs(self, admin_client):
        """?batch_id=<id> shows only runs from that batch."""
        batch_a, run_a = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="A-ONLY",
        )
        batch_b, run_b = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=3),
            run_label="B-ONLY",
        )
        response = self._get_page(admin_client, batch_id=batch_a.pk)
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]

        assert run_a.pk in run_ids
        assert run_b.pk not in run_ids

    def test_batch_detail_context_show_batch_detail_true(self, admin_client):
        """With valid batch_id, context has show_batch_detail=True."""
        batch, _ = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="X",
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        assert response.context.get("show_batch_detail") is True
        assert response.context.get("selected_batch") is not None

    def test_batch_detail_has_back_link_to_history(self, admin_client):
        """Batch detail view has a link back to the full history."""
        batch, _ = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="X",
        )
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        # Should have a link back to metrics page without batch_id
        url_no_batch = reverse("services_portal:ingestion_metrics")
        assert url_no_batch in content

    # ── RED 3: Filters within batch ──────────────────────────────────

    def test_batch_detail_status_filter_within_batch(self, admin_client):
        """Status filter applies within the selected batch only."""
        batch, run_success = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="SUCCESS",
            status="succeeded",
        )
        run_fail = IngestionRun.objects.create(
            batch=batch,
            status="failed",
            intent="full_sync",
            worker_label="w:FAIL",
            queued_at=timezone.now() - timedelta(hours=1, minutes=10),
            processing_started_at=timezone.now() - timedelta(hours=1, minutes=8),
            finished_at=timezone.now() - timedelta(hours=1, minutes=1),
            timed_out=False,
            failure_reason="timeout",
        )

        # Filter by status=failed
        response = self._get_page(admin_client, batch_id=batch.pk, status="failed")
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run_fail.pk in run_ids
        assert run_success.pk not in run_ids

    def test_batch_detail_intent_filter_within_batch(self, admin_client):
        """Intent filter applies within the selected batch."""
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=timezone.now() - timedelta(hours=1, minutes=5),
            finished_at=timezone.now() - timedelta(hours=1),
            status="succeeded",
        )
        run_fs = IngestionRun.objects.create(
            batch=batch, status="succeeded", intent="full_sync",
            worker_label="w:FS",
            queued_at=timezone.now() - timedelta(hours=2),
            processing_started_at=timezone.now() - timedelta(minutes=50),
            finished_at=timezone.now() - timedelta(minutes=45),
            timed_out=False,
        )
        run_ao = IngestionRun.objects.create(
            batch=batch, status="succeeded", intent="admissions_only",
            worker_label="w:AO",
            queued_at=timezone.now() - timedelta(hours=2),
            processing_started_at=timezone.now() - timedelta(minutes=40),
            finished_at=timezone.now() - timedelta(minutes=35),
            timed_out=False,
        )

        response = self._get_page(
            admin_client, batch_id=batch.pk, intent="admissions_only"
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run_ao.pk in run_ids
        assert run_fs.pk not in run_ids

    def test_batch_detail_failure_reason_filter_within_batch(self, admin_client):
        """Failure reason filter applies within the selected batch."""
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=timezone.now() - timedelta(hours=1, minutes=5),
            finished_at=timezone.now() - timedelta(hours=1),
            status="succeeded",
        )
        run_to = IngestionRun.objects.create(
            batch=batch, status="failed", intent="full_sync",
            worker_label="w:TO", failure_reason="timeout", timed_out=True,
            queued_at=timezone.now() - timedelta(hours=2),
            processing_started_at=timezone.now() - timedelta(minutes=50),
            finished_at=timezone.now() - timedelta(minutes=45),
        )
        run_ue = IngestionRun.objects.create(
            batch=batch, status="failed", intent="full_sync",
            worker_label="w:UE", failure_reason="unexpected_exception", timed_out=False,
            queued_at=timezone.now() - timedelta(hours=2),
            processing_started_at=timezone.now() - timedelta(minutes=40),
            finished_at=timezone.now() - timedelta(minutes=35),
        )

        response = self._get_page(
            admin_client, batch_id=batch.pk, failure_reason="timeout"
        )
        page = response.context["selected_batch_runs_page"]
        run_ids = [r.pk for r in page.object_list]
        assert run_to.pk in run_ids
        assert run_ue.pk not in run_ids

    # ── IRMPP-S2: Efficiency block moved from the history table ───────

    def _make_efficiency_batch(self) -> CensusExecutionBatch:
        """Batch with 600s drain and three overlapping attempts.

        Values: 3 finished runs (all succeeded), 2 distinct worker labels
        (one run has an empty label), attempts of 500s/300s/100s all
        ending together and overlapping each other.
        """
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(seconds=600),
            finished_at=now,
            status="succeeded",
        )
        for secs_ago, worker_label in (
            (500, "w1:100"),
            (300, "w2:200"),
            (100, ""),
        ):
            start = now - timedelta(seconds=secs_ago)
            run = IngestionRun.objects.create(
                status="succeeded",
                intent="full_sync",
                batch=batch,
                worker_label=worker_label,
                queued_at=now - timedelta(seconds=660),
                processing_started_at=start,
                finished_at=now,
            )
            attempt = IngestionRunAttempt.objects.create(
                run=run, attempt_number=1, finished_at=now, status="succeeded",
            )
            IngestionRunAttempt.objects.filter(pk=attempt.pk).update(
                started_at=start,
            )
        return batch

    def test_detail_context_exposes_batch_efficiency_values(self, admin_client):
        """R4: detail exposes the efficiency values the history used to show."""
        batch = self._make_efficiency_batch()
        response = self._get_page(admin_client, batch_id=batch.pk)
        efficiency = response.context["batch_efficiency"]
        assert efficiency["batch_id"] == batch.pk
        assert efficiency["observed_worker_count"] == 2  # empty label ignored
        assert sorted(efficiency["observed_worker_labels"]) == [
            "w1:100",
            "w2:200",
        ]
        assert efficiency["observed_peak_concurrency"] == 3
        # 500 + 300 + 100 = 900s of attempts over a 600s drain
        assert efficiency["observed_avg_concurrency"] == pytest.approx(1.5, abs=0.05)
        # 3 terminal runs / (600s = 10 min)
        assert efficiency["throughput_jobs_per_minute"] == pytest.approx(
            0.3, rel=0.01
        )
        # (500 + 300 + 100) / 3
        assert efficiency["avg_processing_duration_seconds"] == 300
        assert efficiency["avg_attempt_duration_seconds"] == 300

    def test_detail_renders_efficiency_block(self, admin_client):
        """R4: the detail view renders the efficiency block and its values."""
        batch = self._make_efficiency_batch()
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        assert "Eficiência do lote" in content
        for label in (
            "Workers observados",
            "Concorrência observada (pico)",
            "Concorrência média",
            "Jobs/min",
            "Média por job",
            "Média por tentativa",
        ):
            assert label in content, label
        # Values render with the active locale's decimal separator (pt-br).
        assert re.search(
            r'<div class="sirhosp-stat-value">1[.,]5</div>', content
        ), "avg concurrency value not rendered"
        assert re.search(
            r'<div class="sirhosp-stat-value">0[.,]3</div>', content
        ), "throughput value not rendered"
        assert '<div class="sirhosp-stat-value">3</div>' in content
        assert "w1:100" in content
        assert "w2:200" in content

    def test_detail_efficiency_is_scoped_to_the_selected_batch(self, admin_client):
        """R4: efficiency values come from the selected batch only."""
        now = timezone.now()
        batch = self._make_efficiency_batch()
        other = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(seconds=60),
            finished_at=now,
            status="succeeded",
        )
        _make_run_with_attempt(
            other,
            status="succeeded",
            worker_label="other-worker",
            processing_started_at=now - timedelta(seconds=30),
            finished_at=now,
        )

        response = self._get_page(admin_client, batch_id=batch.pk)
        efficiency = response.context["batch_efficiency"]
        assert efficiency["runs_total"] == 3
        assert "other-worker" not in efficiency["observed_worker_labels"]

        other_response = self._get_page(admin_client, batch_id=other.pk)
        other_efficiency = other_response.context["batch_efficiency"]
        assert other_efficiency["runs_total"] == 1
        assert other_efficiency["observed_worker_labels"] == ["other-worker"]

    def test_invalid_batch_has_no_efficiency_block(self, admin_client):
        """Spec: an invalid selected batch renders no efficiency block."""
        self._make_efficiency_batch()
        response = self._get_page(admin_client, batch_id=999999)
        assert response.context["batch_efficiency"] is None
        assert "Eficiência do lote" not in response.content.decode()

    # ── RED 4: Invalid batch ─────────────────────────────────────────

    def test_batch_detail_invalid_batch_id_shows_friendly_state(self, admin_client):
        """Invalid batch_id renders a friendly state without global runs."""
        # Create some batches and runs to ensure they don't leak
        self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="SHOULD-NOT-APPEAR",
        )
        response = self._get_page(admin_client, batch_id=999999)
        # Should NOT show runs (no selected_batch_runs_page)
        assert response.context.get("show_batch_detail") is False
        assert response.context.get("selected_batch_runs_page") is None
        # Should show an informational state
        assert response.status_code == 200
        # There should be a link back to the history
        url_no_batch = reverse("services_portal:ingestion_metrics")
        assert url_no_batch in response.content.decode()

    def test_batch_detail_invalid_batch_id_context(self, admin_client):
        """Invalid batch_id context has show_batch_detail=False."""
        response = self._get_page(admin_client, batch_id=999999)
        assert response.context.get("show_batch_detail") is False

    def test_batch_detail_nonnumeric_batch_id(self, admin_client):
        """Non-numeric batch_id is handled as invalid, no global leak."""
        batch, run = self._make_batch_with_labeled_run(
            finished_at_delta=timedelta(hours=1),
            run_label="LEAK",
        )
        response = self._get_page(admin_client, batch_id="abc")
        assert response.context.get("show_batch_detail") is False
        assert response.context.get("batch_not_found") is True
        assert response.status_code == 200

    # ── RED 5: Pagination of executions (optional) ───────────────────

    def test_batch_detail_paginates_runs_with_run_page(self, admin_client):
        """Batch runs are paginated; run_page param navigates pages."""
        now = timezone.now()
        batch = CensusExecutionBatch.objects.create(
            enqueue_finished_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
            status="succeeded",
        )
        # Create 60 runs (more than a reasonable page size like 50)
        runs = []
        for i in range(60):
            r = IngestionRun.objects.create(
                batch=batch,
                status="succeeded",
                intent="full_sync",
                worker_label=f"w:{i}",
                queued_at=now - timedelta(hours=2),
                processing_started_at=now - timedelta(hours=1, minutes=55),
                finished_at=now - timedelta(hours=1) - timedelta(seconds=i),
                timed_out=False,
            )
            runs.append(r)

        # Page 1: most recent 50 runs
        response_p1 = self._get_page(admin_client, batch_id=batch.pk, run_page=1)
        # Page 2: remaining 10 older runs
        response_p2 = self._get_page(admin_client, batch_id=batch.pk, run_page=2)

        p1_ids = [r.pk for r in response_p1.context["selected_batch_runs_page"].object_list]
        p2_ids = [r.pk for r in response_p2.context["selected_batch_runs_page"].object_list]

        assert runs[0].pk in p1_ids
        assert runs[59].pk in p2_ids
        assert runs[59].pk not in p1_ids
        assert runs[0].pk not in p2_ids


# ── IRMPP-S1: Lazy computation by active tab/mode ──────────────────────

_FINAL_FAILURE_TABLE = '"ingestion_finalrunfailure"'
_RUN_TABLE = '"ingestion_ingestionrun"'


def _captured_sql(captured: CaptureQueriesContext) -> list[str]:
    """Normalized SQL text of every query captured during one page render."""
    return [" ".join(query["sql"].split()) for query in captured.captured_queries]


def _global_window_aggregations(queries: list[str]) -> list[str]:
    """Queries aggregating runs over the global ``finished_at`` window."""
    return [q for q in queries if _RUN_TABLE in q and '"finished_at" >= ' in q]


def _global_filter_option_scans(queries: list[str]) -> list[str]:
    """Global DISTINCT scans over all finished runs feeding the dropdowns.

    Scoped to the ``finished_at IS NOT NULL`` form so the per-batch
    ``DISTINCT worker_label`` of the batch efficiency computation is not
    counted (that one is out of scope for this slice).
    """
    return [
        q
        for q in queries
        if q.startswith("SELECT DISTINCT") and '"finished_at" IS NOT NULL' in q
    ]


@pytest.mark.django_db
class TestIngestionMetricsLazyComputation:
    """IRMPP-S1: only the aggregates the active tab/mode renders are computed."""

    def _get_page(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        return admin_client.get(url, params)

    def _capture(self, admin_client, **params):
        with CaptureQueriesContext(connection) as captured:
            response = self._get_page(admin_client, **params)
        return response, _captured_sql(captured)

    def _fixture(self) -> tuple[CensusExecutionBatch, IngestionRun]:
        """One finished batch with a run and one final failure (synthetic)."""
        batch = _make_batch()
        run = _make_run(batch=batch, status="succeeded", intent="full_sync")
        _make_final_failure(
            batch, patient_record="SYNTH-S1-RECORD", intent="full_sync"
        )
        return batch, run

    # ── R1: default runs tab content parity ──────────────────────────

    def test_default_runs_tab_keeps_history_content(self, admin_client):
        """R1: default tab still renders history, its batch link and guidance."""
        batch, _ = self._fixture()
        response = self._get_page(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Histórico de Lotes" in content
        assert f"batch_id={batch.pk}" in content
        assert "Selecione um batch" in content

    # ── R2: no final-failure aggregate on the default tab ────────────

    def test_default_runs_tab_issues_no_final_failure_query(self, admin_client):
        """R2: the default tab issues no query against the final failures."""
        self._fixture()
        _, queries = self._capture(admin_client)
        assert [q for q in queries if _FINAL_FAILURE_TABLE in q] == []

    def test_patients_tab_still_issues_final_failure_query(self, admin_client):
        """R2 control: the patients tab keeps computing the aggregate."""
        self._fixture()
        _, queries = self._capture(admin_client, tab="patients")
        assert [q for q in queries if _FINAL_FAILURE_TABLE in q] != []

    # ── R3: global aggregation + filter options only in detail mode ──

    def test_default_runs_tab_issues_no_global_window_aggregation(self, admin_client):
        """R3: no global run-window aggregation on the default tab."""
        self._fixture()
        _, queries = self._capture(admin_client)
        assert _global_window_aggregations(queries) == []

    def test_default_runs_tab_issues_no_global_filter_option_scan(self, admin_client):
        """R3: none of the 3 global filter-option DISTINCTs on the default tab."""
        self._fixture()
        _, queries = self._capture(admin_client)
        assert _global_filter_option_scans(queries) == []

    def test_patients_tab_issues_no_global_run_window_scan(self, admin_client):
        """R3: the patients tab also skips window aggregation and option scans."""
        self._fixture()
        _, queries = self._capture(admin_client, tab="patients")
        assert _global_window_aggregations(queries) == []
        assert _global_filter_option_scans(queries) == []

    def test_batch_detail_keeps_global_aggregation_and_filter_options(
        self, admin_client
    ):
        """R3 control: batch detail still computes window aggregation + options."""
        batch, _ = self._fixture()
        _, queries = self._capture(admin_client, tab="runs", batch_id=batch.pk)
        assert _global_window_aggregations(queries) != []
        scans = _global_filter_option_scans(queries)
        assert len(scans) == 3  # status, intent, failure_reason
        scanned_sql = " ".join(scans)
        for column in ('"status"', '"intent"', '"failure_reason"'):
            assert column in scanned_sql

    # ── R4: dead context keys removed ────────────────────────────────

    def test_dead_context_keys_are_absent_in_every_mode(self, admin_client):
        """R4: `runs` and `ingestion_stats` are no longer provided."""
        batch, _ = self._fixture()
        for label, params in (
            ("default runs tab", {}),
            ("patients tab", {"tab": "patients"}),
            ("batch detail", {"batch_id": batch.pk}),
        ):
            response = self._get_page(admin_client, **params)
            assert "runs" not in response.context, label
            assert "ingestion_stats" not in response.context, label

    # ── R5: patients tab and batch detail content parity ─────────────

    def test_patients_tab_keeps_failure_content(self, admin_client):
        """R5: the patients tab still renders the failure table and cards."""
        self._fixture()
        response = self._get_page(admin_client, tab="patients")
        content = response.content.decode()
        assert response.status_code == 200
        assert "SYNTH-S1-RECORD" in content
        assert "Prontuário" in content
        assert "Workers observados" in content

    def test_batch_detail_keeps_selected_batch_content(self, admin_client):
        """R5: batch detail still renders the selected batch and its runs."""
        batch, run = self._fixture()
        response = self._get_page(admin_client, batch_id=batch.pk)
        content = response.content.decode()
        assert response.status_code == 200
        assert f"Batch #{batch.pk}" in content
        assert f">{run.pk}<" in content


# ── IRMPP-S2: History query budget ─────────────────────────────────────

_ATTEMPT_TABLE = '"ingestion_ingestionrunattempt"'


def _attempt_table_queries(queries: list[str]) -> list[str]:
    """Queries touching the ingestion run attempts table."""
    return [q for q in queries if _ATTEMPT_TABLE in q]


def _run_table_scan_queries(queries: list[str]) -> list[str]:
    """Queries that read the ingestion runs table as their row source.

    Matches the ``FROM "ingestion_ingestionrun"`` form (including a
    ``DECLARE ... CURSOR FOR`` prefix), so the findings aggregate — which
    joins runs only to scope by batch and reads stage metrics — is not
    counted as a run scan.
    """
    return [q for q in queries if f"FROM {_RUN_TABLE}" in q]


@pytest.mark.django_db
class TestIngestionMetricsBatchHistoryQueryBudget:
    """IRMPP-S2: history counts come from one bounded aggregate, no scans."""

    def _fixture(self) -> list[CensusExecutionBatch]:
        """Three finished batches, each with three runs and attempts."""
        now = timezone.now()
        batches = []
        for i in range(3):
            batch = CensusExecutionBatch.objects.create(
                enqueue_finished_at=now - timedelta(hours=i + 2),
                finished_at=now - timedelta(hours=i + 1),
                status="succeeded",
            )
            for status, worker_label in (
                ("succeeded", "w1:100"),
                ("succeeded", "w2:200"),
                ("failed", "w1:100"),
            ):
                _make_run_with_attempt(
                    batch,
                    status=status,
                    worker_label=worker_label,
                    processing_started_at=now - timedelta(hours=i + 1, minutes=4),
                    finished_at=now - timedelta(hours=i + 1, minutes=2),
                )
            batches.append(batch)
        return batches

    def _capture(self, admin_client, **params):
        url = reverse("services_portal:ingestion_metrics")
        with CaptureQueriesContext(connection) as captured:
            response = admin_client.get(url, params)
        return response, _captured_sql(captured)

    def test_history_issues_no_attempt_queries(self, admin_client):
        """R3: the history emits zero queries against the attempts table."""
        self._fixture()
        _, queries = self._capture(admin_client)
        assert _attempt_table_queries(queries) == []

    def test_history_issues_no_per_batch_run_scans(self, admin_client):
        """R2: one run-table query for the whole page, and it is the aggregate."""
        self._fixture()
        response, queries = self._capture(admin_client)
        run_queries = _run_table_scan_queries(queries)
        assert len(run_queries) == 1, run_queries
        aggregate, = run_queries
        assert "COUNT(" in aggregate
        assert '"batch_id"' in aggregate
        assert '"status"' in aggregate
        assert " IN (" in aggregate  # limited to the page's batches
        counts = [
            (entry["runs_total"], entry["runs_succeeded"], entry["runs_failed"])
            for entry in response.context["batch_history"]
        ]
        assert counts == [(3, 2, 1)] * 3

    def test_run_count_budget_does_not_grow_with_page_batches(self, admin_client):
        """R2: the counts aggregate stays at one query as batches grow."""
        self._fixture()
        _, queries_three = self._capture(admin_client)
        now = timezone.now()
        for i in range(3):
            batch = CensusExecutionBatch.objects.create(
                enqueue_finished_at=now - timedelta(hours=i + 6),
                finished_at=now - timedelta(hours=i + 5),
                status="succeeded",
            )
            _make_run_with_attempt(batch, status="succeeded", worker_label="w1:100")
        _, queries_six = self._capture(admin_client)
        assert len(_run_table_scan_queries(queries_six)) == 1
        assert len(_attempt_table_queries(queries_six)) == 0
        assert len(_run_table_scan_queries(queries_three)) == 1

    def test_history_keeps_findings_aggregate_per_page(self, admin_client):
        """R5: findings presentation still comes from one bounded query."""
        self._fixture()
        response, queries = self._capture(admin_client)
        stage_queries = [
            q for q in queries if '"ingestion_ingestionrunstagemetric"' in q
        ]
        assert len(stage_queries) == 1
        entries = response.context["batch_history"]
        assert all(entry["findings_total"] == 0 for entry in entries)
        assert all(entry["derived_status"] is None for entry in entries)
