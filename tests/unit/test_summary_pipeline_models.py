"""Tests for summary pipeline models (STP-S1 RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.patients.models import Admission, Patient

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patient():
    return Patient.objects.create(
        patient_source_key="P001",
        source_system="tasy",
        name="TEST PATIENT",
    )


def _make_admission(patient=None):
    if patient is None:
        patient = _make_patient()
    return Admission.objects.create(
        patient=patient,
        source_admission_key="ADM001",
        source_system="tasy",
        admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
    )


def _make_user(username="testuser"):
    return User.objects.create_user(username=username, password="pass")


# ---------------------------------------------------------------------------
# SummaryPipelineRun
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryPipelineRun:
    def test_create_pipeline_run_minimum_fields(self):
        """Pipeline run can be created with required fields."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
        )
        assert run.pk is not None
        assert run.admission == admission
        assert run.requested_by == user
        assert run.mode == "generate"
        assert run.status == "queued"
        assert run.phase1_reused is False
        assert run.phase1_cost_total == Decimal("0.00")
        assert run.phase2_cost_total == Decimal("0.00")
        assert run.currency == "USD"

    def test_default_status_is_queued(self):
        """Default status for new pipeline run is queued."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="update",
        )
        assert run.status == "queued"

    def test_default_currency_is_usd(self):
        """Default currency is USD."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
        )
        assert run.currency == "USD"

    def test_total_cost_is_sum_of_phase_costs(self):
        """Total cost = phase1_cost_total + phase2_cost_total."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            phase1_cost_total=Decimal("0.15"),
            phase2_cost_total=Decimal("0.35"),
        )
        assert run.phase1_cost_total == Decimal("0.15")
        assert run.phase2_cost_total == Decimal("0.35")
        assert run.total_cost == Decimal("0.50")

    def test_total_cost_zero_when_no_phase_costs(self):
        """Total cost is zero when both phase costs are zero."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
        )
        assert run.total_cost == Decimal("0.00")

    def test_phase1_reused_marks_flag(self):
        """When phase 1 is reused, flag is True and cost can be zero."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="update",
            phase1_reused=True,
            phase1_cost_total=Decimal("0.00"),
            phase2_cost_total=Decimal("0.20"),
        )
        assert run.phase1_reused is True
        assert run.phase1_cost_total == Decimal("0.00")
        assert run.total_cost == Decimal("0.20")

    def test_save_with_update_fields_keeps_total_cost_consistent(self):
        """total_cost is persisted correctly even when save(update_fields=[...]).

        Regression: save() recalculates total_cost in-memory, but if
        update_fields doesn't include "total_cost" the DB won't persist
        the recomputed value. The save() override must add "total_cost"
        to update_fields automatically.
        """
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            phase1_cost_total=Decimal("0.10"),
            phase2_cost_total=Decimal("0.20"),
        )
        assert run.total_cost == Decimal("0.30")

        # Update only one phase cost via update_fields —
        # total_cost must still be persisted.
        run.phase1_cost_total = Decimal("0.50")
        run.save(update_fields=["phase1_cost_total"])
        run.refresh_from_db()

        assert run.phase1_cost_total == Decimal("0.50")
        assert run.phase2_cost_total == Decimal("0.20")
        assert run.total_cost == Decimal("0.70")

    def test_mode_choices_constrained(self):
        """Mode is one of generate, update, regenerate."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()

        for mode in ["generate", "update", "regenerate"]:
            run = SummaryPipelineRun.objects.create(
                admission=admission,
                requested_by=user,
                mode=mode,
            )
            assert run.mode == mode

    def test_status_choices_constrained(self):
        """Status is one of queued, running, succeeded, partial, failed."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        user = _make_user()

        for status in ["queued", "running", "succeeded", "partial", "failed"]:
            run = SummaryPipelineRun.objects.create(
                admission=admission,
                requested_by=user,
                mode="generate",
                status=status,
            )
            assert run.status == status

    def test_requested_by_can_be_null(self):
        """requested_by FK can be null for pipeline runs without user."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        assert run.pk is not None
        assert run.requested_by is None

    def test_error_message_stored(self):
        """Failed run stores error message for debugging."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
            status="failed",
            error_message="Phase 1 LLM timeout after 3 retries",
        )
        assert run.status == "failed"
        assert "LLM timeout" in run.error_message

    def test_started_at_and_finished_at_timestamps(self):
        """Run records started_at and finished_at for observability."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        finished = datetime(2025, 1, 15, 10, 3, tzinfo=timezone.utc)
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
            status="succeeded",
            started_at=now,
            finished_at=finished,
        )
        assert run.started_at == now
        assert run.finished_at == finished

    def test_ordering_by_created_at_desc(self):
        """Pipeline runs ordered newest first for operational visibility."""
        from apps.summaries.models import SummaryPipelineRun

        admission = _make_admission()
        SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        SummaryPipelineRun.objects.create(
            admission=admission,
            mode="update",
        )
        runs = list(SummaryPipelineRun.objects.all())
        assert len(runs) == 2
        assert runs[0].created_at >= runs[1].created_at


# ---------------------------------------------------------------------------
# SummaryPipelineStepRun
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryPipelineStepRun:
    def test_create_step_run_for_phase1(self):
        """Step run for phase1_canonical can be created with full trace."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
            status="succeeded",
            provider_name="openai",
            model_name="gpt-4o",
            base_url="https://api.openai.com/v1",
            prompt_version="v1",
            prompt_text_snapshot="You are a clinical assistant...",
            request_payload_json={"model": "gpt-4o", "messages": []},
            response_payload_json={"choices": [{"message": {"content": "..."}}]},
            input_tokens=1500,
            output_tokens=800,
            cached_tokens=200,
            cost_input=Decimal("0.015"),
            cost_output=Decimal("0.008"),
            cost_total=Decimal("0.023"),
            latency_ms=3200,
        )
        assert step.pk is not None
        assert step.pipeline_run == run
        assert step.step_type == "phase1_canonical"
        assert step.status == "succeeded"
        assert step.provider_name == "openai"
        assert step.model_name == "gpt-4o"
        assert step.prompt_version == "v1"
        assert "clinical assistant" in step.prompt_text_snapshot
        assert isinstance(step.request_payload_json, dict)
        assert isinstance(step.response_payload_json, dict)
        assert step.input_tokens == 1500
        assert step.output_tokens == 800
        assert step.cached_tokens == 200
        assert step.cost_input == Decimal("0.015")
        assert step.cost_output == Decimal("0.008")
        assert step.cost_total == Decimal("0.023")
        assert step.latency_ms == 3200

    def test_create_step_run_for_phase2(self):
        """Step run for phase2_render can be created with custom prompt."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase2_render",
            status="succeeded",
            provider_name="anthropic",
            model_name="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
            prompt_version="custom",
            prompt_text_snapshot="Summarize in plain portuguese for a lawyer...",
            request_payload_json={"model": "claude-sonnet-4-20250514"},
            response_payload_json={"content": [{"text": "Resumo..."}]},
            input_tokens=2500,
            output_tokens=1200,
            cost_input=Decimal("0.0375"),
            cost_output=Decimal("0.018"),
            cost_total=Decimal("0.0555"),
            latency_ms=4500,
        )
        assert step.step_type == "phase2_render"
        assert step.prompt_version == "custom"
        assert "lawyer" in step.prompt_text_snapshot

    def test_step_type_choices_constrained(self):
        """Step type is one of phase1_canonical, phase2_render."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )

        for step_type in ["phase1_canonical", "phase2_render"]:
            step = SummaryPipelineStepRun.objects.create(
                pipeline_run=run,
                step_type=step_type,
                status="succeeded",
            )
            assert step.step_type == step_type

    def test_default_status_is_running(self):
        """Default status for new step run is running."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
        )
        assert step.status == "running"

    def test_failed_step_stores_error(self):
        """Failed step stores error message for debugging."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
            status="failed",
            error_message="Connection reset by peer",
        )
        assert step.status == "failed"
        assert "reset" in step.error_message

    def test_skipped_step_zero_cost(self):
        """Skipped step (phase1 reused) has zero cost and skipped status."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="update",
            phase1_reused=True,
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
            status="skipped",
            cost_input=Decimal("0.00"),
            cost_output=Decimal("0.00"),
            cost_total=Decimal("0.00"),
        )
        assert step.status == "skipped"
        assert step.cost_total == Decimal("0.00")

    def test_relation_pipeline_run_to_steps(self):
        """Pipeline run can have multiple step runs, accessed via related name."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
        )
        SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase2_render",
        )
        steps = run.step_runs.all()
        assert steps.count() == 2
        step_types = {s.step_type for s in steps}
        assert step_types == {"phase1_canonical", "phase2_render"}

    def test_step_ordering_by_started_at(self):
        """Step runs ordered by started_at ascending."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        t1 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 15, 10, 1, 0, tzinfo=timezone.utc)

        SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase2_render",
            started_at=t2,
        )
        SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
            started_at=t1,
        )
        steps = list(run.step_runs.all())
        assert len(steps) == 2
        assert steps[0].started_at <= steps[1].started_at

    def test_cached_tokens_default_zero(self):
        """cached_tokens defaults to 0 when not provided."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase2_render",
        )
        assert step.cached_tokens == 0

    def test_request_response_payloads_stored_as_json(self):
        """Request and response payloads persisted as JSON objects."""
        from apps.summaries.models import SummaryPipelineRun, SummaryPipelineStepRun

        admission = _make_admission()
        run = SummaryPipelineRun.objects.create(
            admission=admission,
            mode="generate",
        )
        request_payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are..."},
                {"role": "user", "content": "Summarize: ..."},
            ],
            "temperature": 0.3,
        }
        response_payload = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [{"message": {"content": "Summary here"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        step = SummaryPipelineStepRun.objects.create(
            pipeline_run=run,
            step_type="phase1_canonical",
            request_payload_json=request_payload,
            response_payload_json=response_payload,
        )
        assert step.request_payload_json["model"] == "gpt-4o"
        assert len(step.request_payload_json["messages"]) == 2
        assert step.response_payload_json["id"] == "chatcmpl-123"
        assert "usage" in step.response_payload_json
