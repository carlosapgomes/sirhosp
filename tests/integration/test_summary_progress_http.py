"""APS-S7: Integration tests for chunk-level progress page and HTMX polling.

Tests:
- Fragment endpoint requires auth and returns 404 for nonexistent run.
- Status page shows chunk-level progress (completed/in-progress/failed).
- Runs queued/running have HTMX polling; succeeded/partial/failed do not.
- UX message: user can leave and come back later.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.patients.models import Admission, Patient
from apps.summaries.models import SummaryRun, SummaryRunChunk

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user():
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username="progresstester", password="progresstest123"
    )


def _login(client: Client):
    client.force_login(_make_user())


def _make_admission() -> Admission:
    patient = Patient.objects.create(
        patient_source_key="S7-P001",
        source_system="tasy",
        name="S7 TEST PATIENT",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="S7-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        ward="Enfermaria A",
    )


def _make_run(admission: Admission, status: str) -> SummaryRun:
    run = SummaryRun.objects.create(
        admission=admission,
        mode=SummaryRun.Mode.GENERATE,
        target_end_date=date.today(),
        status=status,
        total_chunks=3,
        current_chunk_index=0,
    )
    # Create chunk records for more realistic progress display
    for i in range(3):
        chunk_status = (
            SummaryRunChunk.Status.SUCCEEDED
            if i == 0
            else (
                SummaryRunChunk.Status.RUNNING
                if i == 1
                else SummaryRunChunk.Status.QUEUED
            )
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=i,
            window_start=date(2026, 4, 1),
            window_end=date(2026, 4, 5),
            status=chunk_status,
            input_event_count=5,
        )
    return run


# ---------------------------------------------------------------------------
# Fragment endpoint auth + existence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFragmentAuth:
    """Fragment endpoint must require authentication."""

    def test_anonymous_redirects_to_login(self):
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.QUEUED)
        client = Client()
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestFragmentNotFound:
    """Fragment endpoint returns 404 for nonexistent run."""

    def test_authenticated_fragment_404(self):
        client = Client()
        _login(client)
        url = reverse("summaries:run_progress", args=[99999])
        response = client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fragment progress content
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFragmentProgress:
    """Fragment endpoint returns chunk-level progress HTML."""

    def test_fragment_for_queued_shows_chunks(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.QUEUED)
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Should show chunk progress (succeeded, running, queued)
        assert "Concluído" in content
        assert "Em andamento" in content
        assert "Pendente" in content

    def test_fragment_for_running_shows_chunks(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.RUNNING)
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Concluído" in content
        assert "Em andamento" in content
        assert "Pendente" in content


# ---------------------------------------------------------------------------
# HTMX polling conditional
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPollingConditional:
    """Polling is active only for non-terminal runs."""

    def test_status_page_queued_has_polling(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.QUEUED)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Status page should include HTMX polling for the progress area
        assert 'hx-get="' in content
        assert 'hx-trigger="every 3s' in content

    def test_status_page_running_has_polling(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.RUNNING)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'hx-get="' in content
        assert 'hx-trigger="every 3s' in content

    def test_status_page_succeeded_no_polling(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.SUCCEEDED)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # No HTMX polling for terminal state
        assert 'hx-trigger="every' not in content

    def test_status_page_failed_no_polling(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.FAILED)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'hx-trigger="every' not in content

    def test_status_page_partial_no_polling(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.PARTIAL)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'hx-trigger="every' not in content


# ---------------------------------------------------------------------------
# UX message: user can leave and come back
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUXLeaveAndReturn:
    """Status page must inform user they can leave and come back later."""

    def test_leave_message_for_queued_run(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.QUEUED)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "voltar depois" in content or "pode sair" in content

    def test_leave_message_for_running_run(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.RUNNING)
        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "voltar depois" in content or "pode sair" in content


# ---------------------------------------------------------------------------
# Fragment also shows leave message
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFragmentLeaveMessage:
    """Fragment should also include the leave-and-come-back message."""

    def test_fragment_contains_leave_message(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.RUNNING)
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "voltar depois" in content or "pode sair" in content


# ---------------------------------------------------------------------------
# Chunk status labels (completed / in-progress / failed)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChunkStatusLabels:
    """Each chunk displays its correct status label."""

    def test_succeeded_chunk_shows_concluido(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = _make_run(admission, SummaryRun.Status.RUNNING)
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Concluído" in content

    def test_failed_chunk_shows_falhou(self):
        client = Client()
        _login(client)
        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode=SummaryRun.Mode.GENERATE,
            target_end_date=date.today(),
            status=SummaryRun.Status.PARTIAL,
            total_chunks=2,
            current_chunk_index=0,
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2026, 4, 1),
            window_end=date(2026, 4, 5),
            status=SummaryRunChunk.Status.FAILED,
            error_message="timeout",
            input_event_count=3,
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=1,
            window_start=date(2026, 4, 6),
            window_end=date(2026, 4, 10),
            status=SummaryRunChunk.Status.QUEUED,
            input_event_count=0,
        )
        url = reverse("summaries:run_progress", args=[run.pk])
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Falhou" in content
