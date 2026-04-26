"""Tests for expanded IngestionRun lifecycle/observability fields and helpers."""

from datetime import datetime, timezone

import pytest
from django.utils import timezone as django_timezone

from apps.ingestion.models import IngestionRun


@pytest.mark.django_db
class TestIngestionRunDefaults:
    """RED: Verify defaults for new lifecycle fields on creation."""

    def test_default_timed_out_is_false(self):
        run = IngestionRun.objects.create()

        assert run.timed_out is False

    def test_default_failure_reason_is_empty(self):
        run = IngestionRun.objects.create()

        assert run.failure_reason == ""

    def test_default_worker_label_is_empty(self):
        run = IngestionRun.objects.create()

        assert run.worker_label == ""

    def test_processing_started_at_is_none_by_default(self):
        run = IngestionRun.objects.create()

        assert run.processing_started_at is None

    def test_queued_at_is_set_on_creation(self):
        run = IngestionRun.objects.create()

        assert run.queued_at is not None
        # Should be a datetime close to now
        now = django_timezone.now()
        diff = abs((run.queued_at - now).total_seconds())
        assert diff < 5  # within 5 seconds

    def test_failure_reason_accepts_valid_choice(self):
        run = IngestionRun.objects.create(failure_reason="timeout")

        run.refresh_from_db()
        assert run.failure_reason == "timeout"

    def test_timed_out_can_be_set_true(self):
        run = IngestionRun.objects.create(timed_out=True)

        run.refresh_from_db()
        assert run.timed_out is True

    def test_worker_label_persists_value(self):
        run = IngestionRun.objects.create(worker_label="worker-01")

        run.refresh_from_db()
        assert run.worker_label == "worker-01"


@pytest.mark.django_db
class TestIngestionRunDurations:
    """RED: Verify duration helpers return None or correct values."""

    def _create_run_with_timestamps(self, queued_dt, processing_dt, finished_dt):
        """Helper to create a run and override auto_now_add on queued_at."""
        run = IngestionRun.objects.create()
        # Override auto_now_add by updating after creation
        IngestionRun.objects.filter(pk=run.pk).update(
            queued_at=queued_dt,
            processing_started_at=processing_dt,
            finished_at=finished_dt,
        )
        run.refresh_from_db()
        return run

    def test_queue_latency_none_when_no_processing(self):
        run = IngestionRun.objects.create()
        # processing_started_at is None by default

        assert run.queue_latency_seconds is None

    def test_queue_latency_none_when_no_queued_at(self):
        run = IngestionRun.objects.create()
        run.refresh_from_db()
        # processing_started_at is None, so already None
        assert run.queue_latency_seconds is None

    def test_queue_latency_returns_seconds(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        processing = datetime(2026, 1, 1, 10, 0, 30, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, processing, None)

        assert run.queue_latency_seconds == 30.0

    def test_processing_duration_none_when_no_finished(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        processing = datetime(2026, 1, 1, 10, 0, 30, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, processing, None)

        assert run.processing_duration_seconds is None

    def test_processing_duration_none_when_no_processing(self):
        run = IngestionRun.objects.create()
        # processing_started_at is None

        assert run.processing_duration_seconds is None

    def test_processing_duration_returns_seconds(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        processing = datetime(2026, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 1, 1, 10, 5, 30, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, processing, finished)

        assert run.processing_duration_seconds == 270.0  # 4 min 30 sec

    def test_total_duration_none_when_no_finished(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, None, None)

        assert run.total_duration_seconds is None

    def test_total_duration_none_when_no_queued(self):
        run = IngestionRun.objects.create()
        run.refresh_from_db()
        assert run.total_duration_seconds is None  # finished_at is None

    def test_total_duration_returns_seconds(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 1, 1, 10, 10, 0, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, None, finished)

        assert run.total_duration_seconds == 600.0

    def test_all_durations_with_complete_lifecycle(self):
        queued = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        processing = datetime(2026, 1, 1, 10, 0, 30, tzinfo=timezone.utc)
        finished = datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
        run = self._create_run_with_timestamps(queued, processing, finished)

        assert run.queue_latency_seconds == 30.0
        assert run.processing_duration_seconds == 270.0
        assert run.total_duration_seconds == 300.0


class TestFailureReasonChoices:
    """RED: Verify failure_reason choices are validated."""

    def test_failure_reason_choices_match_spec(self):
        expected = [
            "timeout",
            "source_unavailable",
            "invalid_payload",
            "unexpected_exception",
            "validation_error",
        ]
        # Verify field has choices configured
        field = IngestionRun._meta.get_field("failure_reason")
        assert hasattr(field, "choices")
        actual_choices = [c[0] for c in field.choices if c[0]]
        assert actual_choices == expected

    @pytest.mark.django_db
    def test_all_failure_reasons_persist(self):
        reasons = [
            "timeout",
            "source_unavailable",
            "invalid_payload",
            "unexpected_exception",
            "validation_error",
        ]
        for reason in reasons:
            run = IngestionRun.objects.create(failure_reason=reason)
            run.refresh_from_db()
            assert run.failure_reason == reason
