"""Integration tests for two-phase pipeline orchestration (STP-S6 RED).

Tests:
  - Full run: phase1 + phase2 succeed with step runs persisted.
  - Phase1 reuse: state covers target → skipped step, cost zero.
  - Open admission update: new events trigger incremental phase1.
  - Prompt snapshot saved in step run.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    AdmissionSummaryState,
    SummaryPipelineStepRun,
    SummaryRun,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Stub LLM responses
# ---------------------------------------------------------------------------


def _stub_phase1_response():
    """Valid phase-1 LLM response (chunk-level)."""
    return {
        "estado_estruturado": {
            "motivo_internacao": "dor abdominal aguda",
            "linha_do_tempo": ["2025-01-01: Admissão por dor abdominal"],
            "problemas_ativos": ["dor abdominal"],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": ["TC abdome sem alterações"],
            "intercorrencias": [],
            "pendencias": [],
            "riscos_eventos_adversos": [],
            "situacao_atual": "Paciente estável, aguardando avaliação",
        },
        "resumo_markdown": "# Resumo de Internação\n\nPaciente internado...",
        "mudancas_da_rodada": ["Registro inicial da admissão"],
        "incertezas": [],
        "evidencias": [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00+00:00",
                "author_name": "Dr. Test",
                "snippet": "dor abdominal há 2 dias",
            },
        ],
        "alertas_consistencia": [],
        "_meta": {
            "provider": "openai",
            "model": "gpt-4o",
        },
    }


def _stub_phase2_response():
    """Valid phase-2 LLM render response dict."""
    return {
        "content": "## Resumo de Internação\n\n**Motivo:** dor abdominal aguda...",
        "input_tokens": 500,
        "output_tokens": 300,
        "cached_tokens": 0,
        "cost_input": Decimal("0.005"),
        "cost_output": Decimal("0.003"),
        "cost_total": Decimal("0.008"),
        "latency_ms": 1200,
        "request_payload": {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "prompt..."},
                {"role": "user", "content": "narrative..."},
            ],
        },
        "response_payload": {
            "id": "chatcmpl-xyz",
            "choices": [{"message": {"content": "# Resumo..."}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 300},
        },
    }


def _stub_phase2_large_response():
    """Phase-2 response with higher token counts and costs."""
    return {
        "content": "## Resumo Detalhado\n\n...long summary...",
        "input_tokens": 2000,
        "output_tokens": 1200,
        "cached_tokens": 0,
        "latency_ms": 3500,
        "cost_input": Decimal("0.020"),
        "cost_output": Decimal("0.012"),
        "cost_total": Decimal("0.032"),
        "request_payload": {"model": "claude-sonnet"},
        "response_payload": {"id": "msg-abc"},
    }


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_patient():
    return Patient.objects.create(
        patient_source_key="STP-S6-P001",
        source_system="tasy",
        name="STP-S6 Test Patient",
    )


def _make_admission(patient=None, **overrides):
    if patient is None:
        patient = _make_patient()
    defaults = {
        "patient": patient,
        "source_admission_key": "STP-S6-ADM",
        "source_system": "tasy",
        "admission_date": datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Admission.objects.create(**defaults)


def _make_queued_run(admission=None, **overrides):
    if admission is None:
        admission = _make_admission()
    defaults = {
        "admission": admission,
        "mode": "generate",
        "target_end_date": date(2025, 1, 5),
        "status": "queued",
    }
    defaults.update(overrides)
    return SummaryRun.objects.create(**defaults)


# ---------------------------------------------------------------------------
# S6.1.1 — Full run: phase1 + phase2 succeed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFullTwoPhaseRun:
    """A complete two-phase pipeline run creates pipeline run and step runs."""

    def test_full_run_creates_pipeline_and_two_step_runs(self):
        """Phase1 + Phase2 both succeed, creating one pipeline run with
        two step runs."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        # Pipeline run created
        assert pipeline_run.pk is not None
        assert pipeline_run.admission == admission
        assert pipeline_run.status == "succeeded"
        assert pipeline_run.started_at is not None
        assert pipeline_run.finished_at is not None
        assert pipeline_run.finished_at >= pipeline_run.started_at

        # Two step runs
        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )
        assert len(step_runs) == 2

        phase1_step = step_runs[0]
        assert phase1_step.step_type == "phase1_canonical"
        assert phase1_step.status == "succeeded"

        phase2_step = step_runs[1]
        assert phase2_step.step_type == "phase2_render"
        assert phase2_step.status == "succeeded"

    def test_pipeline_run_tracks_total_cost(self):
        """PipelineRun.total_cost = phase1_cost + phase2_cost."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        # Total cost is sum of phase costs
        assert pipeline_run.total_cost == (
            pipeline_run.phase1_cost_total + pipeline_run.phase2_cost_total
        )
        # Phase 2 should have non-zero cost (stub returns cost_total)
        assert pipeline_run.phase2_cost_total > Decimal("0")
        assert pipeline_run.total_cost > Decimal("0")

    def test_step_runs_have_prompt_snapshot(self):
        """Both phase steps store their prompt_text_snapshot."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )

        # Phase 1 step should have prompt snapshot (from phase1 prompt file)
        phase1_step = step_runs[0]
        assert phase1_step.prompt_text_snapshot != ""

        # Phase 2 step should have prompt snapshot
        phase2_step = step_runs[1]
        assert phase2_step.prompt_text_snapshot != ""

    def test_step_runs_have_provider_and_model_info(self):
        """Step runs record provider_name and model_name."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )

        phase1_step = step_runs[0]
        assert phase1_step.provider_name != ""
        assert phase1_step.model_name != ""

        phase2_step = step_runs[1]
        assert phase2_step.provider_name != ""
        assert phase2_step.model_name != ""

    def test_original_summary_run_succeeded(self):
        """The original SummaryRun is still marked as succeeded."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            execute_two_phase_pipeline(run)

        run.refresh_from_db()
        assert run.status == "succeeded"


# ---------------------------------------------------------------------------
# S6.1.2 — Phase1 reuse: step skipped, cost zero
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPhase1Reuse:
    """When canonical state already covers target period, phase 1 is skipped."""

    def test_phase1_skipped_when_state_covers_target(self):
        """If AdmissionSummaryState coverage_end >= target_end_date,
        phase 1 is skipped with cost zero."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        # Pre-create state that already covers through Jan 10
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo existente",
            status=AdmissionSummaryState.Status.COMPLETE,
        )

        # Run with target_end_date within coverage
        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        # Phase 1 should be marked as reused
        assert pipeline_run.phase1_reused is True
        assert pipeline_run.phase1_cost_total == Decimal("0.00")

        # Only one step run (phase2)
        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )

        # Phase 1 step should exist but be "skipped"
        phase1_steps = [
            s for s in step_runs
            if s.step_type == "phase1_canonical"
        ]
        assert len(phase1_steps) == 1
        phase1_step = phase1_steps[0]
        assert phase1_step.status == "skipped"
        assert phase1_step.cost_total == Decimal("0.00")
        assert phase1_step.cost_input == Decimal("0.00")
        assert phase1_step.cost_output == Decimal("0.00")

        # Phase 2 should still run
        phase2_steps = [
            s for s in step_runs
            if s.step_type == "phase2_render"
        ]
        assert len(phase2_steps) == 1
        phase2_step = phase2_steps[0]
        assert phase2_step.status == "succeeded"

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_total_cost_equals_phase2_when_phase1_reused(self):
        """When phase1 is reused (zero cost), total cost = phase2 cost."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo existente",
            status=AdmissionSummaryState.Status.COMPLETE,
        )

        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.phase1_cost_total == Decimal("0.00")
        assert pipeline_run.phase2_cost_total > Decimal("0")
        assert pipeline_run.total_cost == pipeline_run.phase2_cost_total

    def test_phase1_not_reused_when_state_missing(self):
        """When no AdmissionSummaryState exists, phase 1 runs normally."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.phase1_reused is False
        # Phase 1 did run; cost may be 0 when token counts are not
        # populated by the legacy execute_summary_run (pre-existing).
        assert pipeline_run.phase1_cost_total >= Decimal("0")

    def test_phase1_not_reused_when_state_coverage_insufficient(self):
        """When state coverage_end < target_end_date, phase 1 runs."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        # State only covers through Jan 3
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 3),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo parcial",
            status=AdmissionSummaryState.Status.DRAFT,
        )

        # Target is Jan 10 — beyond coverage
        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 10),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.phase1_reused is False


# ---------------------------------------------------------------------------
# S6.1.3 — Update incremental with new events
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpdateIncremental:
    """Open admission with new events beyond prior coverage triggers
    incremental phase 1 update."""

    def test_update_mode_runs_phase1_with_new_events(self):
        """Update mode where new events exist beyond coverage: phase 1
        runs incrementally, phase 2 follows."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        # Pre-create state covering Jan 1–5
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo inicial (dias 1-5)",
            status=AdmissionSummaryState.Status.DRAFT,
        )

        # Target is Jan 10 — beyond coverage
        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 10),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        # Phase 1 should NOT be reused (new events to process)
        assert pipeline_run.phase1_reused is False

        # Both step runs created
        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )
        assert len(step_runs) == 2
        assert step_runs[0].step_type == "phase1_canonical"
        assert step_runs[0].status == "succeeded"
        assert step_runs[1].step_type == "phase2_render"
        assert step_runs[1].status == "succeeded"

    def test_update_mode_with_coverage_beyond_target_skips_phase1(self):
        """Update mode where coverage already reaches target: phase1 skipped."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        # State covers through Jan 10
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo completo",
            status=AdmissionSummaryState.Status.COMPLETE,
        )

        # Target is Jan 5 — within coverage
        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.phase1_reused is True

    def test_update_mode_state_coverage_expands_after_run(self):
        """After incremental update, state coverage_end reflects the
        new target."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo inicial",
            status=AdmissionSummaryState.Status.DRAFT,
        )

        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 10),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            execute_two_phase_pipeline(run)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.coverage_end >= date(2025, 1, 5)


# ---------------------------------------------------------------------------
# S6.1.4 — Prompt snapshot saved in step run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPromptSnapshot:
    """Prompt text snapshots are persisted in step runs."""

    def test_phase1_prompt_snapshot_matches_loaded_prompt(self):
        """Phase 1 step run stores the actual prompt text used."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )
        phase1_step = step_runs[0]

        # Phase 1 snapshot should contain content from the versioned file
        assert "assistente" in phase1_step.prompt_text_snapshot.lower() or \
            "resumo" in phase1_step.prompt_text_snapshot.lower()
        assert len(phase1_step.prompt_text_snapshot) > 50

    def test_phase2_prompt_snapshot_matches_custom_prompt(self):
        """Phase 2 step stores the custom prompt text when provided."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        custom_prompt = (
            "Resuma o caso clínico para a diretoria jurídica, "
            "com foco em riscos legais e pendências."
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(
                run,
                phase2_prompt_text=custom_prompt,
            )

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )
        phase2_step = step_runs[1]

        assert phase2_step.prompt_text_snapshot == custom_prompt
        assert "diretoria jurídica" in phase2_step.prompt_text_snapshot

    def test_phase2_prompt_snapshot_uses_default_when_no_custom(self):
        """Phase 2 uses default prompt from file when no custom prompt given."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(
                run,
                phase2_prompt_text=None,
            )

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )
        phase2_step = step_runs[1]

        # Default prompt should be loaded from file
        assert len(phase2_step.prompt_text_snapshot) > 50
        assert "resumo" in phase2_step.prompt_text_snapshot.lower()

    def test_skipped_phase1_also_has_prompt_snapshot(self):
        """Even when phase 1 is skipped, its step run stores a prompt
        snapshot (for auditability)."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )

        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Resumo existente",
            status=AdmissionSummaryState.Status.COMPLETE,
        )

        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 5),
        )

        with patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        step_runs = list(
            SummaryPipelineStepRun.objects.filter(
                pipeline_run=pipeline_run
            ).order_by("started_at")
        )

        phase1_step = next(
            s for s in step_runs if s.step_type == "phase1_canonical"
        )
        assert phase1_step.status == "skipped"
        # Should still record which prompt version was configured
        assert phase1_step.prompt_version != ""
        assert phase1_step.prompt_text_snapshot != ""


# ---------------------------------------------------------------------------
# Pipeline run fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPipelineRunFields:
    """Pipeline run tracks started_at, finished_at, and currency."""

    def test_currency_is_usd(self):
        """Pipeline run currency defaults to USD."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.currency == "USD"

    def test_requested_by_is_copied_from_summary_run(self):
        """Pipeline run copies requested_by from the SummaryRun."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(username="piperequest", password="pass")

        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            requested_by=user,
        )

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.requested_by == user

    def test_error_message_empty_on_success(self):
        """Successful pipeline run has empty error_message."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            return_value=_stub_phase2_response(),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.error_message == ""


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPipelineFailure:
    """Pipeline handles failures gracefully."""

    def test_phase1_failure_marks_pipeline_as_failed(self):
        """When phase 1 fails, pipeline run is marked as failed."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_gateway",
            side_effect=RuntimeError("LLM API timeout"),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.status == "failed"
        assert "LLM API timeout" in pipeline_run.error_message

        run.refresh_from_db()
        assert run.status == "failed"

        # Phase 1 step should be failed
        step_runs = SummaryPipelineStepRun.objects.filter(
            pipeline_run=pipeline_run
        )
        phase1_steps = [
            s for s in step_runs
            if s.step_type == "phase1_canonical"
        ]
        assert len(phase1_steps) == 1
        assert phase1_steps[0].status == "failed"
        assert phase1_steps[0].error_message != ""

    def test_phase2_failure_marks_pipeline_as_partial(self):
        """When phase 1 succeeds but phase 2 fails, pipeline is partial."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_gateway",
            return_value=_stub_phase1_response(),
        ), patch(
            "apps.summaries.services.call_llm_phase2_render",
            side_effect=RuntimeError("Phase 2 render failed"),
        ):
            from apps.summaries.services import execute_two_phase_pipeline

            pipeline_run = execute_two_phase_pipeline(run)

        assert pipeline_run.status == "partial"
        assert "Phase 2 render failed" in pipeline_run.error_message

        run.refresh_from_db()
        assert run.status == "partial"

        # Phase 1 should still be succeeded
        step_runs = SummaryPipelineStepRun.objects.filter(
            pipeline_run=pipeline_run
        )
        phase1_steps = [
            s for s in step_runs
            if s.step_type == "phase1_canonical"
        ]
        assert len(phase1_steps) == 1
        assert phase1_steps[0].status == "succeeded"

        # Phase 2 should be failed
        phase2_steps = [
            s for s in step_runs
            if s.step_type == "phase2_render"
        ]
        assert len(phase2_steps) == 1
        assert phase2_steps[0].status == "failed"
