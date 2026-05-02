"""Tests for sync_status context processor.

Verifies that the context processor returns the correct sync time
based on the latest succeeded IngestionRun, or a fallback when
no succeeded runs exist.
"""

from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.core.context_processors import sync_status
from apps.ingestion.models import IngestionRun


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def fake_request(rf: RequestFactory):
    return rf.get("/")


class TestSyncStatusContextProcessor:
    """sync_status must return real sync time from IngestionRun."""

    def test_no_runs_returns_fallback(
        self, fake_request, db
    ):
        """When no IngestionRun exists, returns '--:--'."""
        result = sync_status(fake_request)

        assert result == {"sync_time": "--:--"}

    def test_running_only_returns_fallback(
        self, fake_request, db
    ):
        """When only running (non-finished) runs exist, returns '--:--'."""
        IngestionRun.objects.create(status="running")

        result = sync_status(fake_request)

        assert result == {"sync_time": "--:--"}

    def test_single_succeeded_returns_time(
        self, fake_request, db
    ):
        """A single succeeded run returns its finished_at as HH:MM."""
        now = timezone.now()
        IngestionRun.objects.create(
            status="succeeded",
            finished_at=now,
        )

        result = sync_status(fake_request)

        expected = timezone.localtime(now).strftime("%H:%M")
        assert result == {"sync_time": expected}

    def test_multiple_succeeded_returns_latest(
        self, fake_request, db
    ):
        """With multiple succeeded runs, returns the most recent finished_at."""
        now = timezone.now()
        older = now - timedelta(hours=3)
        newest = now - timedelta(minutes=15)

        IngestionRun.objects.create(
            status="succeeded", finished_at=older
        )
        IngestionRun.objects.create(
            status="succeeded", finished_at=newest
        )

        result = sync_status(fake_request)

        expected = timezone.localtime(newest).strftime("%H:%M")
        assert result == {"sync_time": expected}

    def test_ignores_failed_runs(
        self, fake_request, db
    ):
        """Failed runs are ignored; only succeeded runs are considered."""
        now = timezone.now()
        failed_time = now - timedelta(minutes=10)
        succeeded_time = now - timedelta(hours=1)

        IngestionRun.objects.create(
            status="failed", finished_at=failed_time
        )
        IngestionRun.objects.create(
            status="succeeded", finished_at=succeeded_time
        )

        result = sync_status(fake_request)

        expected = timezone.localtime(succeeded_time).strftime("%H:%M")
        assert result == {"sync_time": expected}

    def test_returns_dict_with_sync_time_key(
        self, fake_request, db
    ):
        """Return value is always a dict with 'sync_time' key."""
        result = sync_status(fake_request)

        assert isinstance(result, dict)
        assert "sync_time" in result
        assert isinstance(result["sync_time"], str)
