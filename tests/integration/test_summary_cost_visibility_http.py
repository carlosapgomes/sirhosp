"""Integration tests for cost visibility in status and read pages (STP-S9).

Tests:
- Status page shows cost per phase (phase1/phase2/total) in USD and BRL
- Read page shows total cost and phase 1 reuse flag
- Fallback when no pipeline run exists (page still works)
- Fallback when no exchange rate exists (USD shown, BRL shows '---')
- Fallback when costs/tokens/câmbio are missing
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
    AdmissionSummaryState,
    ExchangeRateSnapshot,
    SummaryPipelineRun,
    SummaryPipelineStepRun,
    SummaryRun,
)

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(
    username: str = "costtester",
    password: str = "testpass123",
) -> object:
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username=username,
        password=password,
    )


def _make_admission(
    patient_key: str = "S9-P001",
    adm_key: str = "S9-ADM",
    patient_name: str = "S9 COST PATIENT",
) -> Admission:
    patient = Patient.objects.create(
        patient_source_key=patient_key,
        source_system="tasy",
        name=patient_name,
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key=adm_key,
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        ward="Enfermaria S9",
    )


def _make_run(admission: Admission) -> SummaryRun:
    """Create a simple SummaryRun for status/read views."""
    return SummaryRun.objects.create(
        admission=admission,
        mode=SummaryRun.Mode.GENERATE,
        target_end_date=date.today(),
        status=SummaryRun.Status.SUCCEEDED,
        current_chunk_index=3,
        total_chunks=5,
    )


def _make_run_with_state(admission: Admission) -> SummaryRun:
    """Create SummaryRun + AdmissionSummaryState."""
    run = SummaryRun.objects.create(
        admission=admission,
        mode=SummaryRun.Mode.GENERATE,
        target_end_date=date.today(),
        status=SummaryRun.Status.SUCCEEDED,
        current_chunk_index=3,
        total_chunks=5,
    )
    AdmissionSummaryState.objects.create(
        admission=admission,
        coverage_start=date(2026, 4, 1),
        coverage_end=date(2026, 4, 5),
        narrative_markdown="# Resumo de Internação\n\nPaciente estável.",
        status=AdmissionSummaryState.Status.COMPLETE,
    )
    return run


def _create_pipeline_run(
    user,
    admission: Admission,
    *,
    phase1_cost: Decimal = Decimal("0.50"),
    phase2_cost: Decimal = Decimal("0.30"),
    phase1_reused: bool = False,
) -> SummaryPipelineRun:
    """Create a pipeline run with two step runs."""
    from decimal import Decimal as D

    run = SummaryPipelineRun.objects.create(
        admission=admission,
        requested_by=user,
        mode=SummaryPipelineRun.Mode.GENERATE,
        status=SummaryPipelineRun.Status.SUCCEEDED,
        phase1_reused=phase1_reused,
        phase1_cost_total=phase1_cost if not phase1_reused else D("0.00"),
        phase2_cost_total=phase2_cost,
        started_at=datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 4, 9, 5, tzinfo=timezone.utc),
    )

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
        prompt_text_snapshot="Você é um assistente médico...",
        request_payload_json={"model": "gpt-4o-mini", "messages": []},
        response_payload_json={"choices": [{"message": {"content": "ok"}}]},
        input_tokens=500,
        output_tokens=300,
        cached_tokens=0,
        cost_input=phase1_cost / 2 if not phase1_reused else D("0.00"),
        cost_output=phase1_cost / 2 if not phase1_reused else D("0.00"),
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
        prompt_text_snapshot="Com base no resumo clínico...",
        request_payload_json={"model": "gpt-4o", "messages": []},
        response_payload_json={"choices": [{"message": {"content": "ok"}}]},
        input_tokens=800,
        output_tokens=500,
        cached_tokens=0,
        cost_input=phase2_cost / 2,
        cost_output=phase2_cost / 2,
        latency_ms=2500,
        started_at=datetime(2026, 5, 4, 9, 2, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 4, 9, 5, tzinfo=timezone.utc),
    )

    return run


def _create_exchange_rate(rate: Decimal = Decimal("5.60")) -> ExchangeRateSnapshot:
    """Create an exchange rate snapshot for BRL conversion."""
    return ExchangeRateSnapshot.objects.create(
        base_currency="USD",
        quote_currency="BRL",
        rate=rate,
        reference_date=date(2026, 5, 4),
        provider="frankfurter",
        fetched_at=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Status page cost visibility tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatusCostVisibility:
    """Status page displays costs per phase in USD and BRL."""

    def test_status_shows_phase_costs_in_usd(self):
        """Status page shows phase1/phase2/total costs in USD."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # USD costs should appear in the page
        # Decimal(0.50) renders as "0.50" or "0,50" depending on locale
        assert "0.50" in content or "0,50" in content
        assert "0.30" in content or "0,30" in content
        # Total = 0.80
        assert "0.80" in content or "0,80" in content

    def test_status_shows_phase_costs_in_brl(self):
        """Status page converts USD costs to BRL using latest rate."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # BRL = total USD * rate = 0.80 * 5.60 = 4.48
        assert "4.48" in content or "4,48" in content

    def test_status_cost_fallback_no_pipeline_run(self):
        """Status page works without a pipeline run (no cost section)."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Should still have the normal status content
        assert "Resumo" in content
        # Should not crash — just no cost section

    def test_status_cost_fallback_no_exchange_rate(self):
        """Status page shows USD costs with BRL fallback when no rate exists."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        # No exchange rate created — simulate missing rate

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # USD costs still shown
        assert "0.50" in content or "0,50" in content
        # BRL fallback indicator or "---" should appear
        assert "---" in content or "Câmbio" in content

    def test_status_phase1_reused_indicator(self):
        """Status page shows phase 1 reuse indicator when reused."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.00"),
            phase2_cost=Decimal("0.30"),
            phase1_reused=True,
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Phase 1 reused indicator
        assert "Reutilizado" in content or "reutilizado" in content.lower()
        # Phase 1 cost should be 0
        assert "0.00" in content or "0,00" in content

    def test_status_page_auth_required(self):
        """Status page requires authentication."""
        admission = _make_admission()
        run = _make_run(admission)
        client = Client()

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_status_shows_cost_section_structure(self):
        """Status cost section has clear labels for Fase 1, Fase 2, Total."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:run_status", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Should have labeled cost section
        assert "Custo" in content
        # Phase labels
        assert "Fase 1" in content or "Base clínica" in content
        assert "Fase 2" in content or "Versão final" in content


# ---------------------------------------------------------------------------
# Read page cost visibility tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReadCostVisibility:
    """Read page displays total cost and phase 1 reuse flag."""

    def test_read_shows_total_cost_in_usd_and_brl(self):
        """Read page shows total run cost in USD and BRL."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Total USD cost
        assert "0.80" in content or "0,80" in content
        # BRL converted
        assert "4.48" in content or "4,48" in content

    def test_read_shows_phase1_reuse_flag(self):
        """Read page indicates when phase 1 was reused."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.00"),
            phase2_cost=Decimal("0.30"),
            phase1_reused=True,
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Phase 1 reused indicator
        assert "Base clínica reutilizada" in content

    def test_read_fallback_no_pipeline_run(self):
        """Read page works without a pipeline run (no cost info)."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Should still render the summary content
        assert "Resumo de Internação" in content
        assert "Paciente estável" in content

    def test_read_fallback_no_exchange_rate(self):
        """Read page shows USD cost with BRL fallback when no rate."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        # No exchange rate

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # USD cost shown
        assert "0.80" in content or "0,80" in content
        # BRL fallback indicator
        assert "---" in content or "Câmbio" in content

    def test_read_page_retains_existing_content(self):
        """Read page still shows patient info, summary content, and disclaimer."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.50"),
            phase2_cost=Decimal("0.30"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Existing content preserved
        assert "Resumo de Internação" in content
        assert "Paciente estável" in content
        assert "assistido" in content.lower() or "IA" in content
        assert "Copiar" in content
        # Patient name present
        assert "S9 COST PATIENT" in content

    def test_read_cost_fallback_zero_costs(self):
        """Read page handles zero costs gracefully (no traceback)."""
        user = _make_user()
        admission = _make_admission()
        run = _make_run_with_state(admission)
        _create_pipeline_run(
            user, admission,
            phase1_cost=Decimal("0.00"),
            phase2_cost=Decimal("0.00"),
        )
        _create_exchange_rate(Decimal("5.60"))

        client = Client()
        client.force_login(user)

        url = reverse("summaries:read", args=[run.pk])
        response = client.get(url)
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        # Zero costs are displayed
        assert "0.00" in content or "0,00" in content
