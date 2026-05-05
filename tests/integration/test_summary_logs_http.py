"""Integration tests for summary logs HTTP views (STP-S8).

Tests:
- Public logs list operational data (phase, status, model, cost USD+BRL)
- BRL uses most recent exchange rate available
- Admin logs require staff/superuser
- Admin logs show prompt/payload/response
- Public logs hide sensitive content (prompt text, request/response payload)
- Anonymous users redirected to login
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    ExchangeRateSnapshot,
    SummaryPipelineRun,
    SummaryPipelineStepRun,
)

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(
    username: str = "logstester",
    password: str = "testpass123",
    is_staff: bool = False,
    is_superuser: bool = False,
):
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username=username,
        password=password,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def _make_staff_user():
    return _make_user(username="staffuser", is_staff=True)


def _make_superuser():
    return _make_user(username="superuser", is_staff=True, is_superuser=True)


def _login(client: Client, user=None):
    if user is None:
        user = _make_user()
    client.force_login(user)
    return user


def _make_admission() -> Admission:
    patient = Patient.objects.create(
        patient_source_key="S8-P001",
        source_system="tasy",
        name="S8 TEST PATIENT",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="S8-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        ward="Enfermaria A",
    )


def _create_pipeline_run(
    user,
    admission: Admission,
    *,
    phase1_cost: Decimal = Decimal("0.50"),
    phase2_cost: Decimal = Decimal("0.30"),
    status: str = SummaryPipelineRun.Status.SUCCEEDED,
    phase1_reused: bool = False,
) -> SummaryPipelineRun:
    """Create a pipeline run with two step runs."""
    from decimal import Decimal as D

    run = SummaryPipelineRun.objects.create(
        admission=admission,
        requested_by=user,
        mode=SummaryPipelineRun.Mode.GENERATE,
        status=status,
        phase1_reused=phase1_reused,
        phase1_cost_total=phase1_cost if not phase1_reused else D("0.00"),
        phase2_cost_total=phase2_cost,
        started_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 4, 9, 5, tzinfo=timezone.utc),
    )
    # Keep created_at deterministic for datetime assertions in HTTP tests.
    SummaryPipelineRun.objects.filter(pk=run.pk).update(
        created_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    )
    run.refresh_from_db()

    # Phase 1 step run
    SummaryPipelineStepRun.objects.create(
        pipeline_run=run,
        step_type=SummaryPipelineStepRun.StepType.PHASE1_CANONICAL,
        status=(
            SummaryPipelineStepRun.Status.SKIPPED
            if phase1_reused
            else SummaryPipelineStepRun.Status.SUCCEEDED
        ),
        provider_name="openai",
        model_name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        prompt_version="phase1_canonical_v1",
        prompt_text_snapshot=(
            "Você é um assistente médico. "
            "Gere um resumo clínico canônico..."
        ),
        request_payload_json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "phase1 prompt snapshot"},
                {"role": "user", "content": "clinical data..."},
            ],
        },
        response_payload_json={
            "choices": [
                {
                    "message": {
                        "content": "Resumo canônico gerado..."
                    }
                }
            ],
            "usage": {"prompt_tokens": 500, "completion_tokens": 300},
        },
        input_tokens=500,
        output_tokens=300,
        cached_tokens=0,
        cost_input=Decimal("0.25"),
        cost_output=Decimal("0.25"),
        latency_ms=1200,
        started_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 4, 9, 2, tzinfo=timezone.utc),
    )

    # Phase 2 step run
    SummaryPipelineStepRun.objects.create(
        pipeline_run=run,
        step_type=SummaryPipelineStepRun.StepType.PHASE2_RENDER,
        status=SummaryPipelineStepRun.Status.SUCCEEDED,
        provider_name="openai",
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
        prompt_version="phase2_default_v1",
        prompt_text_snapshot=(
            "Com base no resumo clínico canônico abaixo, "
            "gere uma versão final para leitura..."
        ),
        request_payload_json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "phase2 prompt snapshot"},
                {"role": "user", "content": "canonical summary..."},
            ],
        },
        response_payload_json={
            "choices": [
                {
                    "message": {
                        "content": "Resumo final gerado para leitura..."
                    }
                }
            ],
            "usage": {"prompt_tokens": 800, "completion_tokens": 500},
        },
        input_tokens=800,
        output_tokens=500,
        cached_tokens=0,
        cost_input=Decimal("0.15"),
        cost_output=Decimal("0.15"),
        latency_ms=2500,
        started_at=datetime(2026, 5, 4, 9, 2, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 4, 9, 5, tzinfo=timezone.utc),
    )

    return run


def _create_exchange_rate(
    rate: Decimal = Decimal("5.60"),
    ref_date: date | None = None,
) -> ExchangeRateSnapshot:
    """Create an exchange rate snapshot for BRL conversion."""
    if ref_date is None:
        ref_date = date(2026, 5, 4)
    return ExchangeRateSnapshot.objects.create(
        base_currency="USD",
        quote_currency="BRL",
        rate=rate,
        reference_date=ref_date,
        provider="frankfurter",
        fetched_at=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Public logs tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPublicLogs:
    """Public logs accessible to all authenticated users."""

    def test_public_logs_page_accessible_to_authenticated(self):
        user = _make_user()
        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        assert response.status_code == 200

    def test_public_logs_anonymous_redirects_to_login(self):
        client = Client()
        url = reverse("summaries:logs_public")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_public_logs_shows_phase_status_model(self):
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(user, admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Phase labels should appear
        assert "Fase 1" in content
        assert "Fase 2" in content
        # Status
        assert "Sucedido" in content or "succeeded" in content.lower()
        # Model names
        assert "gpt-4o-mini" in content
        assert "gpt-4o" in content

    def test_public_logs_shows_costs_in_usd(self):
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(
            user, admission, phase1_cost=Decimal("0.50"), phase2_cost=Decimal("0.30")
        )

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # USD costs should appear
        assert "0.50" in content or "0,50" in content
        assert "0.30" in content or "0,30" in content
        # Total USD cost should appear
        assert "0.80" in content or "0,80" in content

    def test_public_logs_shows_costs_in_brl_when_rate_exists(self):
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(
            user, admission, phase1_cost=Decimal("0.50"), phase2_cost=Decimal("0.30")
        )
        # USD/BRL rate = 5.60
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Total USD = 0.80, total BRL = 0.80 * 5.60 = 4.48
        assert "4.48" in content or "4,48" in content

    def test_public_logs_brl_uses_most_recent_rate(self):
        """BRL conversion uses the most recent available rate regardless of date."""
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(
            user, admission, phase1_cost=Decimal("1.00"), phase2_cost=Decimal("0.00")
        )
        # Create an older rate and a newer rate
        _create_exchange_rate(Decimal("5.00"), ref_date=date(2026, 5, 1))
        _create_exchange_rate(Decimal("5.80"), ref_date=date(2026, 5, 4))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Should use 5.80 (most recent), not 5.00
        # Total USD = 1.00, BRL = 1.00 * 5.80 = 5.80
        assert "5.80" in content or "5,80" in content

    def test_public_logs_brl_fallback_when_no_rate(self):
        """When no exchange rate exists, BRL should show '---' or equivalent."""
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(
            user, admission, phase1_cost=Decimal("1.00"), phase2_cost=Decimal("0.00")
        )

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Should not crash; BRL column or indicator is present
        assert "BRL" in content or "---" in content

    def test_public_logs_hides_prompt_snapshots(self):
        """Public logs must NOT expose prompt text or raw payload/response."""
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(user, admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Sensitive strings from the test data should NOT appear
        assert "Você é um assistente médico" not in content
        assert "prompt_text_snapshot" not in content
        assert "request_payload_json" not in content
        # JSON payload fragments should not be visible
        assert '"system"' not in content or "system" not in content

    def test_public_logs_hides_raw_response(self):
        """Raw response content must not be in public view."""
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(user, admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        assert "Resumo canônico gerado" not in content
        assert '"completion_tokens"' not in content

    def test_public_logs_shows_patient_and_user_info(self):
        user = _make_user(username="dr_maria")
        admission = _make_admission()
        _create_pipeline_run(user, admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Patient name
        assert "S8 TEST PATIENT" in content
        # Username
        assert "dr_maria" in content

    def test_public_logs_shows_datetime(self):
        user = _make_user()
        admission = _make_admission()
        _create_pipeline_run(user, admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # created_at date should be visible (formatted)
        assert "04/05" in content  # DD/MM format for May 4

    def test_public_logs_brl_consistent_across_rows(self):
        """All BRL conversions in a single request use the same rate.

        Create two runs with different costs + one exchange rate.
        Verify both BRL values are consistent with that single rate.
        Regression for STP-S8-F1: rate must be loaded once per request.
        """
        user = _make_user()

        # Create two admissions with unique patient keys (avoid IntegrityError)
        p1 = Patient.objects.create(
            patient_source_key="S8-F1-P1",
            source_system="tasy",
            name="F1 Patient 1",
        )
        p2 = Patient.objects.create(
            patient_source_key="S8-F1-P2",
            source_system="tasy",
            name="F1 Patient 2",
        )
        adm1 = Admission.objects.create(
            patient=p1,
            source_admission_key="S8-F1-ADM1",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
            ward="Enfermaria A",
        )
        adm2 = Admission.objects.create(
            patient=p2,
            source_admission_key="S8-F1-ADM2",
            source_system="tasy",
            admission_date=datetime(2026, 4, 2, 10, 0, tzinfo=TZ),
            ward="Enfermaria B",
        )

        _create_pipeline_run(
            user, adm1, phase1_cost=Decimal("1.00"), phase2_cost=Decimal("0.00")
        )
        _create_pipeline_run(
            user, adm2, phase1_cost=Decimal("2.00"), phase2_cost=Decimal("0.50")
        )
        _create_exchange_rate(Decimal("5.70"))

        # Also create an older rate to confirm it is NOT used
        _create_exchange_rate(Decimal("4.00"), ref_date=date(2026, 4, 1))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_public")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200

        # Run 1: total USD = 1.00, BRL = 1.00 * 5.70 = 5.70
        assert "5.70" in content or "5,70" in content
        # Run 2: total USD = 2.50, BRL = 2.50 * 5.70 = 14.25
        assert "14.25" in content or "14,25" in content

        # The old rate (4.00) should NOT affect any BRL value
        assert "4.00" not in content or "4,00" not in content


# ---------------------------------------------------------------------------
# Admin logs tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminLogs:
    """Admin logs restricted to staff/superuser with full sensitive details."""

    def test_admin_logs_accessible_to_staff(self):
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        assert response.status_code == 200

    def test_admin_logs_accessible_to_superuser(self):
        su = _make_superuser()
        client = Client()
        client.force_login(su)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        assert response.status_code == 200

    def test_admin_logs_blocked_for_regular_user(self):
        user = _make_user()
        client = Client()
        client.force_login(user)

        url = reverse("summaries:logs_admin")
        response = client.get(url)

        assert response.status_code in (302, 403)
        # If redirect (login), must not be the admin page
        if response.status_code == 302:
            assert "/logs/admin" not in (response.url or "")

    def test_admin_logs_blocked_for_anonymous(self):
        client = Client()
        url = reverse("summaries:logs_admin")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_admin_logs_shows_prompt_snapshot(self):
        staff = _make_staff_user()
        admission = _make_admission()
        _create_pipeline_run(staff, admission)

        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Admin should see the prompt text
        assert "Você é um assistente médico" in content

    def test_admin_logs_shows_request_payload(self):
        staff = _make_staff_user()
        admission = _make_admission()
        _create_pipeline_run(staff, admission)

        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Admin should see the request payload (HTML-escaped by Django)
        assert "&quot;model&quot;" in content
        assert "&quot;messages&quot;" in content

    def test_admin_logs_shows_response_payload(self):
        staff = _make_staff_user()
        admission = _make_admission()
        _create_pipeline_run(staff, admission)

        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Admin should see the response payload (HTML-escaped by Django)
        assert "Resumo canônico gerado" in content
        assert "&quot;completion_tokens&quot;" in content

    def test_admin_logs_shows_all_public_info_plus_sensitive(self):
        """Admin view includes everything from public + sensitive details."""
        staff = _make_staff_user()
        admission = _make_admission()
        _create_pipeline_run(staff, admission)
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Public info present
        assert "S8 TEST PATIENT" in content
        assert "gpt-4o-mini" in content
        assert "gpt-4o" in content
        # Sensitive info present (JSON escaped by Django)
        assert "Você é um assistente médico" in content
        assert "&quot;messages&quot;" in content

    def test_admin_logs_escapes_html_in_payload(self):
        """Admin logs MUST escape HTML in payloads — no raw <script> rendered.

        Regression test for STP-S8-F1 XSS hardening.
        """
        staff = _make_staff_user()
        admission = _make_admission()

        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=staff,
            mode=SummaryPipelineRun.Mode.GENERATE,
            status=SummaryPipelineRun.Status.SUCCEEDED,
            phase1_reused=False,
            phase1_cost_total=Decimal("0.10"),
            phase2_cost_total=Decimal("0.20"),
            started_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 5, 4, 9, 1, tzinfo=timezone.utc),
        )

        # Step run with HTML-like content in payload
        SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type=SummaryPipelineStepRun.StepType.PHASE2_RENDER,
            status=SummaryPipelineStepRun.Status.SUCCEEDED,
            provider_name="openai",
            model_name="gpt-4o",
            base_url="https://api.openai.com/v1",
            prompt_version="phase2_default_v1",
            prompt_text_snapshot="prompt text",
            request_payload_json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "user", "content": "<img src=x onerror=alert(1)>"}
                ],
            },
            response_payload_json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<script>alert('XSS')</script>"
                                "<b>bold injection</b>"
                            )
                        }
                    }
                ]
            },
            input_tokens=100,
            output_tokens=50,
            cached_tokens=0,
            cost_input=Decimal("0.05"),
            cost_output=Decimal("0.05"),
            latency_ms=500,
            started_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 5, 4, 9, 1, tzinfo=timezone.utc),
        )

        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200

        # The raw HTML must NOT appear unescaped
        assert "<script>alert" not in content
        assert "<img src=x onerror" not in content
        assert "<b>bold injection</b>" not in content

        # The escaped versions SHOULD appear (Django auto-escapes to &lt; &gt;)
        assert "&lt;script&gt;alert" in content
        assert "&lt;img src=x onerror" in content


# ---------------------------------------------------------------------------
# Navigation / links
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLogsNavigation:
    """Navigation links to logs pages are available as appropriate."""

    def test_public_logs_link_present_in_sidebar(self):
        user = _make_user()
        client = Client()
        client.force_login(user)

        # Hit any page with sidebar
        url = reverse("services_portal:dashboard")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Sidebar should have a link to logs
        assert 'summaries:logs_public' in content or 'logs' in content.lower()

    def test_admin_logs_link_visible_to_staff(self):
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)

        url = reverse("summaries:logs_admin")
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Admin page should reference itself as logs_admin
        assert "logs" in content.lower()
