"""Integration test for cross-run cost isolation (STC-S4).

When two runs exist for the same admission, each status/read page
SHALL display only the pipeline cost of its own run.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    AdmissionSummaryState,
    SummaryPipelineRun,
    SummaryPipelineStepRun,
    SummaryRun,
)

UTC = timezone.utc


def _make_user(username: str = "crossrunner") -> User:
    return User.objects.create_user(
        username=username, password="test",
    )


def _make_patient() -> Patient:
    return Patient.objects.create(
        patient_source_key="STC-S4-PT",
        source_system="tasy",
        name="STC-S4 Patient",
    )


def _make_admission(patient: Patient | None = None) -> Admission:
    if patient is None:
        patient = _make_patient()
    return Admission.objects.create(
        patient=patient,
        source_admission_key="STC-S4-ADM",
        source_system="tasy",
        admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
    )


def _make_summary_run(
    admission: Admission,
    *,
    mode: str = "generate",
    status: str = "succeeded",
    target_end_date: date = date(2025, 1, 5),
) -> SummaryRun:
    return SummaryRun.objects.create(
        admission=admission,
        mode=mode,
        status=status,
        target_end_date=target_end_date,
        started_at=datetime(2025, 1, 2, 8, 0, tzinfo=UTC),
        finished_at=datetime(2025, 1, 2, 8, 10, tzinfo=UTC),
    )


def _make_pipeline_run(
    summary_run: SummaryRun,
    *,
    phase1_cost: Decimal = Decimal("0.10"),
    phase2_cost: Decimal = Decimal("0.05"),
    user: User | None = None,
) -> SummaryPipelineRun:
    """Create a pipeline run linked to a specific SummaryRun."""
    pr = SummaryPipelineRun.objects.create(
        admission=summary_run.admission,
        summary_run=summary_run,
        requested_by=user,
        mode=summary_run.mode,
        status=SummaryPipelineRun.Status.SUCCEEDED,
        phase1_cost_total=phase1_cost,
        phase2_cost_total=phase2_cost,
        started_at=datetime(2025, 1, 2, 8, 0, tzinfo=UTC),
        finished_at=datetime(2025, 1, 2, 8, 10, tzinfo=UTC),
    )
    # Phase 1 step
    SummaryPipelineStepRun.objects.create(
        pipeline_run=pr,
        step_type=SummaryPipelineStepRun.StepType.PHASE1_CANONICAL,
        status=SummaryPipelineStepRun.Status.SUCCEEDED,
        provider_name="test",
        model_name="test",
        cost_total=phase1_cost,
        cost_usd_reported=phase1_cost,
        cost_usd_estimated=phase1_cost,
        cost_is_reported=True,
        started_at=datetime(2025, 1, 2, 8, 0, tzinfo=UTC),
        finished_at=datetime(2025, 1, 2, 8, 5, tzinfo=UTC),
    )
    # Phase 2 step
    SummaryPipelineStepRun.objects.create(
        pipeline_run=pr,
        step_type=SummaryPipelineStepRun.StepType.PHASE2_RENDER,
        status=SummaryPipelineStepRun.Status.SUCCEEDED,
        provider_name="test",
        model_name="test",
        cost_total=phase2_cost,
        cost_usd_reported=phase2_cost,
        cost_usd_estimated=phase2_cost,
        cost_is_reported=True,
        started_at=datetime(2025, 1, 2, 8, 5, tzinfo=UTC),
        finished_at=datetime(2025, 1, 2, 8, 10, tzinfo=UTC),
    )
    return pr


@pytest.mark.django_db
class TestCrossRunCostIsolation:
    """Two summary runs for the same admission SHALL NOT leak costs."""

    def test_status_page_shows_only_own_pipeline_cost(self):
        """Each run status page shows cost from its own pipeline only."""
        user = _make_user()
        admission = _make_admission()
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            narrative_markdown="# Resumo",
        )

        # Run 1 with cost 0.10/0.05
        run1 = _make_summary_run(admission)
        _make_pipeline_run(
            run1, phase1_cost=Decimal("0.10"),
            phase2_cost=Decimal("0.05"), user=user,
        )

        # Run 2 with cost 0.30/0.15 — same admission!
        run2 = _make_summary_run(admission)
        _make_pipeline_run(
            run2, phase1_cost=Decimal("0.30"),
            phase2_cost=Decimal("0.15"), user=user,
        )

        client = Client()
        client.force_login(user)

        # Run 1 page should show 0.10/0.05
        resp1 = client.get(f"/summaries/status/{run1.pk}/")
        assert resp1.status_code == 200
        content1 = resp1.content.decode()
        assert "$ 0.10" in content1 or "$ 0,10" in content1, (
            f"Expected phase1=0.10 in run1 page: {content1[:800]}"
        )
        assert "$ 0.05" in content1 or "$ 0,05" in content1, (
            f"Expected phase2=0.05 in run1 page: {content1[:800]}"
        )

        # Should NOT show run2's cost
        assert "$ 0.30" not in content1 and "$ 0,30" not in content1

        # Run 2 page should show 0.30/0.15
        resp2 = client.get(f"/summaries/status/{run2.pk}/")
        assert resp2.status_code == 200
        content2 = resp2.content.decode()
        assert "$ 0.30" in content2 or "$ 0,30" in content2, (
            f"Expected phase1=0.30 in run2 page: {content2[:800]}"
        )
        assert "$ 0.15" in content2 or "$ 0,15" in content2, (
            f"Expected phase2=0.15 in run2 page: {content2[:800]}"
        )

        # Should NOT show run1's cost
        assert "$ 0.10" not in content2 and "$ 0,10" not in content2
