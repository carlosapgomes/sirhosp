"""Tests for the census freshness context processor (topbar badge).

``sync_status`` must expose the time of the latest census photo
(``CensusSnapshot`` with maximum ``captured_at``) — never per-run
``IngestionRun`` signals and never the request time — with the closed
presentation contract:

- ``census_sync_label``: "HH:MM" for a photo from today, "dd/mm HH:MM"
  otherwise, "--:--" when no photo exists;
- ``census_sync_title``: full local timestamp of the photo;
- ``census_sync_age_class``: "is-fresh" (<= 2 h), "is-stale" (<= 6 h),
  "is-outdated" (> 6 h or no photo).

Any database failure degrades to the "--:--" + "is-outdated" fallback
(fail-closed).
"""

from datetime import datetime, timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.core.context_processors import (
    FRESH_WITHIN,
    STALE_WITHIN,
    census_badge_values,
    latest_census_photo,
    sync_status,
)


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def fake_request(rf: RequestFactory):
    return rf.get("/")


def make_snapshot(captured_at: datetime) -> CensusSnapshot:
    """Create a synthetic census snapshot row (no patient data)."""
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        setor="UTI TESTE",
        leito="L01",
        bed_status=BedStatus.EMPTY,
    )


class TestCensusBadgeConstants:
    """Age thresholds are explicit operational decisions (design D3)."""

    def test_fresh_within_is_two_hours(self) -> None:
        assert FRESH_WITHIN == timedelta(hours=2)

    def test_stale_within_is_six_hours(self) -> None:
        assert STALE_WITHIN == timedelta(hours=6)


class TestLatestCensusPhoto:
    """latest_census_photo returns Max(captured_at) or None."""

    def test_no_snapshots_returns_none(self, db) -> None:
        assert latest_census_photo() is None

    def test_returns_latest_captured_at(self, db) -> None:
        now = timezone.now()
        make_snapshot(now - timedelta(hours=3))
        newest = make_snapshot(now - timedelta(minutes=15))

        assert latest_census_photo() == newest.captured_at


class TestSyncStatusPhotoSemantics:
    """sync_status derives the badge from the census photo, not runs."""

    def test_photo_today_returns_hhmm_label(self, fake_request, db) -> None:
        """A photo from today shows only "HH:MM" (label prefix lives in
        the template). Uses a fixed hour of *today* so the expectation is
        deterministic regardless of when the test runs."""
        captured = timezone.localtime().replace(
            hour=12, minute=34, second=0, microsecond=0
        )
        make_snapshot(captured)

        result = sync_status(fake_request)

        assert result["census_sync_label"] == "12:34"

    def test_photo_today_returns_fresh_class(self, fake_request, db) -> None:
        make_snapshot(timezone.localtime() - timedelta(minutes=5))

        result = sync_status(fake_request)

        assert result["census_sync_age_class"] == "is-fresh"

    def test_photo_today_returns_full_title(self, fake_request, db) -> None:
        captured = timezone.localtime().replace(
            hour=12, minute=34, second=0, microsecond=0
        )
        make_snapshot(captured)

        result = sync_status(fake_request)

        expected = captured.strftime("Foto do censo de %d/%m/%Y %H:%M")
        assert result["census_sync_title"] == expected

    def test_photo_not_today_returns_date_in_label(
        self, fake_request, db
    ) -> None:
        """A photo from another day shows "dd/mm HH:MM"."""
        captured = timezone.localtime() - timedelta(days=3)
        make_snapshot(captured)

        result = sync_status(fake_request)

        expected = timezone.localtime(captured).strftime("%d/%m %H:%M")
        assert result["census_sync_label"] == expected

    def test_old_photo_returns_outdated_class(self, fake_request, db) -> None:
        captured = timezone.localtime() - timedelta(days=3)
        make_snapshot(captured)

        result = sync_status(fake_request)

        assert result["census_sync_age_class"] == "is-outdated"

    def test_multiple_snapshots_use_latest(self, fake_request, db) -> None:
        """With several snapshots, the newest captured_at wins. Both rows
        are pinned to fixed hours of *today*, so the expected label is
        deterministic regardless of when the test runs."""
        today = timezone.localtime()
        make_snapshot(today.replace(hour=20, minute=0))
        newest = make_snapshot(today.replace(hour=23, minute=45))

        result = sync_status(fake_request)

        expected = timezone.localtime(newest.captured_at).strftime("%H:%M")
        assert result["census_sync_label"] == expected

    def test_no_photo_returns_fail_closed_values(
        self, fake_request, db
    ) -> None:
        """Without any snapshot: "--:--" + outdated (fail-closed)."""
        result = sync_status(fake_request)

        assert result["census_sync_label"] == "--:--"
        assert result["census_sync_age_class"] == "is-outdated"

    def test_database_failure_returns_fail_closed_values(
        self, fake_request, db, monkeypatch
    ) -> None:
        """Any database failure degrades to the fallback, never raises."""

        def boom() -> None:
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(
            "apps.core.context_processors.latest_census_photo", boom
        )

        result = sync_status(fake_request)

        assert result["census_sync_label"] == "--:--"
        assert result["census_sync_age_class"] == "is-outdated"

    def test_contract_only_badge_keys_no_sync_time(
        self, fake_request, db
    ) -> None:
        """The old 'sync_time' key is gone; exactly the badge keys exist."""
        result = sync_status(fake_request)

        assert set(result) == {
            "census_sync_label",
            "census_sync_title",
            "census_sync_age_class",
        }


class TestCensusBadgeAgeBoundaries:
    """Closed age classes at the 2 h / 6 h boundaries (pure function).

    Boundaries are inclusive on the lower class side: exactly 2 h is
    fresh, exactly 6 h is stale; only beyond 6 h is outdated.
    """

    REF = timezone.make_aware(datetime(2026, 9, 1, 12, 0, 0))

    def values(self, age: timedelta) -> dict:
        return census_badge_values(self.REF - age, now=self.REF)

    def test_no_photo_is_outdated(self) -> None:
        values = census_badge_values(None, now=self.REF)

        assert values["census_sync_age_class"] == "is-outdated"
        assert values["census_sync_label"] == "--:--"

    def test_recent_photo_is_fresh(self) -> None:
        assert self.values(timedelta(minutes=30))[
            "census_sync_age_class"
        ] == "is-fresh"

    def test_exactly_two_hours_is_fresh(self) -> None:
        assert self.values(timedelta(hours=2))[
            "census_sync_age_class"
        ] == "is-fresh"

    def test_just_over_two_hours_is_stale(self) -> None:
        assert self.values(timedelta(hours=2, seconds=1))[
            "census_sync_age_class"
        ] == "is-stale"

    def test_between_two_and_six_hours_is_stale(self) -> None:
        assert self.values(timedelta(hours=4))[
            "census_sync_age_class"
        ] == "is-stale"

    def test_exactly_six_hours_is_stale(self) -> None:
        assert self.values(timedelta(hours=6))[
            "census_sync_age_class"
        ] == "is-stale"

    def test_just_over_six_hours_is_outdated(self) -> None:
        assert self.values(timedelta(hours=6, seconds=1))[
            "census_sync_age_class"
        ] == "is-outdated"

    def test_way_old_photo_is_outdated(self) -> None:
        assert self.values(timedelta(hours=25))[
            "census_sync_age_class"
        ] == "is-outdated"
