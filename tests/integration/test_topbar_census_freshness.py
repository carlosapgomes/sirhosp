"""Integration tests: topbar census freshness badge (change TCF-S1).

The portal shell topbar must show the latest census photo time
(``Max(CensusSnapshot.captured_at)``), never individual ingestion runs.
Age classes close at 2 h (fresh) and 6 h (stale); the tooltip always
carries the full timestamp; any authenticated shell page renders it.

Shell page choice: ``/censo/`` is used instead of ``/painel/`` because
the dashboard view itself evaluates an ``ingestion_ingestionrun`` count
for its 24 h metrics card (out of scope and untouchable here); ``/censo/``
isolates the badge contract: today exactly one such query exists (the
context processor), and after TCF-S1 it must be zero.
"""

from datetime import datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot

SHELL_URL = "/censo/"


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user(username="operador", password="testpass123")


@pytest.fixture
def auth_client(client: Client, user: User) -> Client:
    client.login(username="operador", password="testpass123")
    return client


def make_snapshot(captured_at: datetime) -> CensusSnapshot:
    """Create a synthetic census snapshot row (no patient data)."""
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        setor="UTI TESTE",
        leito="L01",
        bed_status=BedStatus.EMPTY,
    )


class TestTopbarCensusBadge:
    def test_badge_shows_photo_time_today(self, auth_client: Client) -> None:
        """Photo from today renders "Censo: HH:MM" and the old per-run
        label disappears from the shell."""
        captured = timezone.localtime().replace(
            hour=12, minute=34, second=0, microsecond=0
        )
        make_snapshot(captured)

        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Label prefix lives inside its own span in the badge markup.
        assert "Censo: </span>12:34" in content
        assert "Sincronizado:" not in content

    def test_badge_shows_date_when_photo_not_today(
        self, auth_client: Client
    ) -> None:
        """Photo from another day renders "Censo: dd/mm HH:MM"."""
        captured = timezone.localtime() - timedelta(days=3)
        make_snapshot(captured)
        expected = timezone.localtime(captured).strftime("Censo: %d/%m %H:%M")

        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        expected = timezone.localtime(captured).strftime("%d/%m %H:%M")
        # Label prefix lives inside its own span in the badge markup.
        assert f"Censo: </span>{expected}" in resp.content.decode()

    def test_badge_fresh_age_class_in_html(self, auth_client: Client) -> None:
        """A recent photo puts the fresh class on the dot."""
        make_snapshot(timezone.localtime() - timedelta(minutes=5))

        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        assert 'class="dot is-fresh"' in resp.content.decode()

    def test_badge_outdated_age_class_for_old_photo(
        self, auth_client: Client
    ) -> None:
        """A photo older than 6 h puts the outdated class on the dot."""
        make_snapshot(timezone.localtime() - timedelta(days=3))

        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        assert 'class="dot is-outdated"' in resp.content.decode()

    def test_badge_title_carries_full_timestamp(
        self, auth_client: Client
    ) -> None:
        """The tooltip always carries the full local timestamp."""
        captured = timezone.localtime().replace(
            hour=12, minute=34, second=0, microsecond=0
        )
        make_snapshot(captured)
        expected = captured.strftime("Foto do censo de %d/%m/%Y %H:%M")

        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        assert f'title="{expected}"' in resp.content.decode()

    def test_no_photo_renders_placeholder(self, auth_client: Client) -> None:
        """Without snapshots: "--:--" with the outdated dot (fail-closed)."""
        resp = auth_client.get(SHELL_URL)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Label prefix lives inside its own span in the badge markup.
        assert "Censo: </span>--:--" in content
        assert 'class="dot is-outdated"' in content

    def test_render_never_queries_ingestionrun(
        self, auth_client: Client
    ) -> None:
        """No query may read ``ingestion_ingestionrun`` while rendering an
        authenticated shell page: the badge value comes from the census
        photo alone."""
        make_snapshot(timezone.localtime().replace(hour=12, minute=34))

        with CaptureQueriesContext(connection) as ctx:
            auth_client.get(SHELL_URL)

        run_queries = [
            q["sql"]
            for q in ctx.captured_queries
            if "ingestion_ingestionrun" in q["sql"]
        ]
        assert run_queries == []
