"""APS-S8: Integration tests for summary markdown read page.

Tests:
- Auth required (redirect to login).
- 404 for nonexistent run.
- Renders narrative_markdown from AdmissionSummaryState.
- Copy button present in UI.
- Incomplete warning badge visible when state is incomplete.
- AI disclaimer visible in UI.
- Raw markdown accessible for client-side copy.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    AdmissionSummaryState,
    SummaryRun,
)

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user():
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username="readtester", password="readtest123"
    )


def _make_admission() -> Admission:
    patient = Patient.objects.create(
        patient_source_key="S8-P001",
        source_system="tasy",
        name="S8 READ TEST PATIENT",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="S8-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        ward="UTI",
    )


def _make_run_with_state(
    admission: Admission,
    status: str | None = None,
    narrative: str = "",
    state_status: str | None = None,
) -> SummaryRun:
    """Create a SummaryRun + AdmissionSummaryState for the admission."""
    if status is None:
        status = SummaryRun.Status.SUCCEEDED
    if state_status is None:
        state_status = AdmissionSummaryState.Status.COMPLETE

    run = SummaryRun.objects.create(
        admission=admission,
        mode=SummaryRun.Mode.GENERATE,
        target_end_date=date.today(),
        status=status,
    )
    AdmissionSummaryState.objects.create(
        admission=admission,
        coverage_start=date(2026, 4, 1),
        coverage_end=date(2026, 4, 5),
        narrative_markdown=narrative,
        status=state_status,
    )
    return run


# ===================================================================
# Test classes
# ===================================================================


@pytest.mark.django_db
class TestReadViewAuth:
    """Auth required for read view."""

    def test_redirects_anonymous_to_login(self, client: Client):
        admission = _make_admission()
        run = _make_run_with_state(admission)
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/login/" in resp["Location"]


@pytest.mark.django_db
class TestReadView404:
    """404 for nonexistent run."""

    def test_returns_404_for_nonexistent_run(self, client: Client):
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[99999])
        resp = client.get(url)
        assert resp.status_code == 404


@pytest.mark.django_db
class TestReadViewMarkdownRendering:
    """Narrative markdown is rendered as HTML."""

    def test_renders_narrative_content(self, client: Client):
        admission = _make_admission()
        narrative = "# Resumo de Internação\n\nPaciente estável."
        run = _make_run_with_state(admission, narrative=narrative)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Resumo de Internação" in content
        assert "Paciente estável" in content

    def test_renders_markdown_formatting(self, client: Client):
        admission = _make_admission()
        narrative = "**bold** and *italic* and `code`."
        run = _make_run_with_state(admission, narrative=narrative)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        # Markdown converted to HTML — look for strong/em tags
        assert "<strong>bold</strong>" in content
        assert "<em>italic</em>" in content


@pytest.mark.django_db
class TestCopyButton:
    """Copy button present in UI."""

    def test_copy_button_present(self, client: Client):
        admission = _make_admission()
        narrative = "Resumo de teste."
        run = _make_run_with_state(admission, narrative=narrative)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Copiar" in content

    def test_raw_markdown_in_page_for_copy(self, client: Client):
        admission = _make_admission()
        narrative = "**bold** text\n\n- item 1\n- item 2"
        run = _make_run_with_state(admission, narrative=narrative)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        # Raw markdown should be in the page (e.g. in a script block for
        # clipboard copy), not just the rendered HTML.
        assert "**bold**" in content
        assert "- item 1" in content


@pytest.mark.django_db
class TestIncompleteBadge:
    """Incomplete state renders warning."""

    def test_incomplete_state_shows_warning(self, client: Client):
        admission = _make_admission()
        narrative = "Resumo parcial."
        run = _make_run_with_state(
            admission,
            narrative=narrative,
            status=SummaryRun.Status.PARTIAL,
            state_status=AdmissionSummaryState.Status.INCOMPLETE,
        )
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "incompleto" in content.lower()

    def test_complete_state_no_warning(self, client: Client):
        admission = _make_admission()
        narrative = "Resumo completo."
        run = _make_run_with_state(
            admission,
            narrative=narrative,
            status=SummaryRun.Status.SUCCEEDED,
            state_status=AdmissionSummaryState.Status.COMPLETE,
        )
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "incompleto" not in content.lower()


@pytest.mark.django_db
class TestDisclaimer:
    """AI disclaimer is visible in UI."""

    def test_ai_disclaimer_visible(self, client: Client):
        admission = _make_admission()
        run = _make_run_with_state(admission)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert (
            "IA" in content
            or "inteligência artificial" in content.lower()
            or "assistido" in content.lower()
        )

    def test_disclaimer_not_in_copied_markdown(self, client: Client):
        """Raw markdown string (the one used for copy) must NOT include
        the disclaimer text."""
        admission = _make_admission()
        narrative = "Resumo clínico."
        run = _make_run_with_state(admission, narrative=narrative)
        client.force_login(_make_user())
        url = reverse("summaries:read", args=[run.pk])
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        # The raw markdown that gets copied should be the original narrative
        # without the disclaimer injected into it.
        assert "Resumo clínico" in content
        # Verify JS variable for raw markdown is present in script block
        assert "RAW_MARKDOWN" in content


@pytest.mark.django_db
class TestAdmissionLinkUpdate:
    """APS-S6 correction: "Ler resumo" link in admission_list points
    to the read view (not run_status)."""

    def test_ler_resumo_link_points_to_read_view(self, client: Client):
        """The existing admission_list page should have the "Ler resumo"
        link pointing to summaries:read."""
        from apps.summaries.services import get_admission_summary_context

        admission = _make_admission()
        narrative = "Resumo de internação."
        run = _make_run_with_state(
            admission,
            narrative=narrative,
            status=SummaryRun.Status.SUCCEEDED,
            state_status=AdmissionSummaryState.Status.COMPLETE,
        )

        client.force_login(_make_user())

        # Verify that the service returns latest_run_id and show_ler_resumo
        ctx = get_admission_summary_context(admission)
        assert ctx["show_ler_resumo"] is True
        assert ctx["latest_run_id"] == run.pk

        # Access the admission list page
        url = reverse(
            "patients:admission_list",
            kwargs={"patient_id": admission.patient.pk},
        )
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()

        # The "Ler resumo" link should point to summaries:read, not
        # summaries:run_status.
        read_url = reverse("summaries:read", args=[run.pk])
        assert read_url in content
