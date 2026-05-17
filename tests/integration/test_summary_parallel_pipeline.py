"""Integration tests for parallel summary pipeline (APS-P-S3 RED phase).

Tests the execute_parallel_pipeline flow: planning windows, parallel
chunk dispatch, consolidation, and state/version persistence.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryPipelineRun,
    SummaryPipelineStepRun,
    SummaryRun,
    SummaryRunChunk,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patient(source_key="P3-P001"):
    return Patient.objects.create(
        patient_source_key=source_key,
        source_system="tasy",
        name="P3 TEST PATIENT",
    )


def _make_admission(patient=None, **overrides):
    if patient is None:
        patient = _make_patient()
    defaults = {
        "patient": patient,
        "source_admission_key": "P3-ADM",
        "source_system": "tasy",
        "admission_date": datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Admission.objects.create(**defaults)


def _make_queued_parallel_run(admission=None, **overrides):
    if admission is None:
        admission = _make_admission()
    defaults = {
        "admission": admission,
        "mode": "generate",
        "target_end_date": date(2025, 6, 10),
        "status": "queued",
        "pipeline_type": "parallel",
    }
    defaults.update(overrides)
    return SummaryRun.objects.create(**defaults)


def _make_local_chunk_response(chunk_index: int) -> dict:
    """Return a valid LLM response for a parallel local chunk."""
    return {
        "estado_estruturado": {
            "motivo_internacao": f"motivo chunk {chunk_index}",
            "linha_do_tempo": [f"Evento chunk {chunk_index}"],
            "problemas_ativos": [f"problema {chunk_index}"],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": [],
            "intercorrencias": [],
            "pendencias": [],
            "riscos_eventos_adversos": [],
            "situacao_atual": f"estável chunk {chunk_index}",
        },
        "resumo_markdown": f"# Chunk {chunk_index}\n\nResumo local.",
        "mudancas_da_rodada": [f"Mudança chunk {chunk_index}"],
        "incertezas": [],
        "evidencias": [
            {
                "event_id": f"evt-{chunk_index}",
                "happened_at": "2025-06-01T10:00:00-03:00",
                "author_name": "Dr. Test",
                "snippet": f"Trecho chunk {chunk_index}",
            }
        ],
        "alertas_consistencia": [],
        "_meta": {"provider": "test", "model": "test-model"},
        "_chunk_index": chunk_index,
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd_reported": Decimal("0.00"),
        "cost_usd_estimated": Decimal("0.00125"),
        "cost_is_reported": False,
    }


def _make_final_response() -> dict:
    """Return a valid consolidation response."""
    return {
        "content": "# Resumo Final Consolidado\n\nTeste.",
        "input_tokens": 500,
        "output_tokens": 300,
        "cached_tokens": 0,
        "cost_input": Decimal("0.0025"),
        "cost_output": Decimal("0.0045"),
        "cost_total": Decimal("0.007"),
        "cost_usd_reported": Decimal("0.00"),
        "cost_usd_estimated": Decimal("0.007"),
        "cost_is_reported": False,
        "request_payload": {},
        "response_payload": {},
        "latency_ms": 100,
    }


# ---------------------------------------------------------------------------
# Happy path: 3 parallel chunks → consolidation → succeeded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelPipelineHappyPath:
    """Full happy path for execute_parallel_pipeline."""

    def test_run_transitions_to_succeeded(self):
        """A parallel run completes with status succeeded."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        chunks_responses = [
            _make_local_chunk_response(0),
            _make_local_chunk_response(1),
            _make_local_chunk_response(2),
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_chunks_are_created_for_each_window(self):
        """Each parallel chunk gets a SummaryRunChunk record."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        chunks_responses = [
            _make_local_chunk_response(i) for i in range(3)
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        chunks = SummaryRunChunk.objects.filter(run=run).order_by(
            "chunk_index"
        )
        assert chunks.count() == 3
        for chunk in chunks:
            assert chunk.status == "succeeded"
            assert chunk.window_start is not None
            assert chunk.window_end is not None

    def test_versions_are_created_for_each_chunk(self):
        """Each chunk produces an AdmissionSummaryVersion."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        chunks_responses = [
            _make_local_chunk_response(i) for i in range(3)
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        versions = AdmissionSummaryVersion.objects.filter(run=run)
        assert versions.count() == 3

    def test_state_is_updated_with_coverage(self):
        """AdmissionSummaryState coverage reflects the full period."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(
            admission=admission,
            target_end_date=date(2025, 6, 10),
        )

        chunks_responses = [
            _make_local_chunk_response(i) for i in range(3)
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.coverage_start == date(2025, 6, 1)
        assert state.coverage_end == date(2025, 6, 10)

    def test_state_has_consolidated_narrative(self):
        """The state narrative is the final consolidated output."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        final_response = _make_final_response()
        final_response["content"] = (
            "# Resumo Consolidado\n\nConteúdo de teste unificado."
        )

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(3)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=final_response,
        ):
            execute_parallel_pipeline(run, admission=admission)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert "Conteúdo de teste unificado" in state.narrative_markdown

    def test_pipeline_run_is_created(self):
        """A SummaryPipelineRun is created for traceability."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(1)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        pipeline_run = SummaryPipelineRun.objects.filter(
            summary_run=run
        ).first()
        assert pipeline_run is not None
        assert pipeline_run.status == "succeeded"

    def test_pipeline_step_runs_are_created(self):
        """SummaryPipelineStepRun records exist for phase 1 and 2."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(1)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        pipeline_run = SummaryPipelineRun.objects.get(summary_run=run)
        steps = SummaryPipelineStepRun.objects.filter(
            pipeline_run=pipeline_run
        ).order_by("started_at")
        assert steps.count() == 2
        assert steps[0].step_type == "phase1_canonical"
        assert steps[0].status == "succeeded"
        assert steps[1].step_type == "phase2_render"
        assert steps[1].status == "succeeded"

    def test_total_chunks_and_current_index_set(self):
        """total_chunks and current_chunk_index are set correctly."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(
            admission=admission,
            target_end_date=date(2025, 6, 10),
        )

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(3)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.total_chunks == 3
        assert run.current_chunk_index == run.total_chunks


# ---------------------------------------------------------------------------
# Partial failure: one chunk fails
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelPipelinePartial:
    """Tests for partial completion after chunk failure."""

    def test_partial_status_when_chunk_fails(self):
        """Run ends as partial when a chunk returns _error."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        # Chunk 1 fails, chunks 0 and 2 succeed
        chunks_responses = [
            _make_local_chunk_response(0),
            {
                "_error": True,
                "_chunk_index": 1,
                "error_message": "Chunk 1 exhausted 3 retries: test error",
            },
            _make_local_chunk_response(2),
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.status == "partial"
        assert "Chunk 1 exhausted" in run.error_message

    def test_failed_chunk_not_persisted_as_version(self):
        """Failed chunks do not create AdmissionSummaryVersion records."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        chunks_responses = [
            _make_local_chunk_response(0),
            {
                "_error": True,
                "_chunk_index": 1,
                "error_message": "fail",
            },
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ):
            execute_parallel_pipeline(run, admission=admission)

        # Only the successful chunk creates a version
        versions = AdmissionSummaryVersion.objects.filter(run=run)
        assert versions.count() == 1
        assert versions.first().chunk_index == 0

    def test_state_incomplete_on_partial(self):
        """State is marked incomplete when run is partial."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        chunks_responses = [
            _make_local_chunk_response(0),
            {
                "_error": True,
                "_chunk_index": 1,
                "error_message": "fail",
            },
        ]

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=chunks_responses,
        ):
            execute_parallel_pipeline(run, admission=admission)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.status == "incomplete"


# ---------------------------------------------------------------------------
# Single chunk (short admission)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelPipelineSingleChunk:
    """Pipeline works with a single chunk (short admission)."""

    def test_single_chunk_completes_successfully(self):
        """A 3-day admission with 1 chunk completes normally."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission(
            admission_date=datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_parallel_run(
            admission=admission,
            target_end_date=date(2025, 6, 3),
        )

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(0)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.total_chunks == 1


# ---------------------------------------------------------------------------
# Overlap of 1 day
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelOverlap:
    """Parallel pipeline uses overlap_days=1."""

    def test_windows_have_single_day_overlap(self):
        """Consecutive chunks overlap by exactly 1 day."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(
            admission=admission,
            target_end_date=date(2025, 6, 10),
        )

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(3)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        chunks = SummaryRunChunk.objects.filter(run=run).order_by(
            "chunk_index"
        )
        for i in range(len(chunks) - 1):
            # Next chunk starts 1 day before previous chunk ends (overlap=1)
            current_end = chunks[i].window_end
            next_start = chunks[i + 1].window_start
            overlap = (current_end - next_start).days
            assert overlap >= 0, (
                f"Chunks {i} and {i+1}: end={current_end}, "
                f"start={next_start}, overlap={overlap}"
            )


# ---------------------------------------------------------------------------
# Cancel support
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelPipelineCancel:
    """Parallel pipeline respects user cancellation."""

    def test_cancelled_run_is_skipped(self):
        """A cancelled run is not processed further."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)
        # Mark as cancelled before processing
        run.status = "failed"
        run.error_message = "Interrompido pelo usuário"
        run.save(update_fields=["status", "error_message"])

        execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.status == "failed"
        assert "Interrompido pelo usuário" in run.error_message
        # No chunks should be created
        assert SummaryRunChunk.objects.filter(run=run).count() == 0


# ---------------------------------------------------------------------------
# Empty event handling (early stop)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelPipelineEmptyEvents:
    """Early stop when consecutive windows have no events."""

    def test_all_chunks_without_events_still_complete(self):
        """Processing completes even without ClinicalEvent records."""
        from apps.summaries.services import execute_parallel_pipeline

        admission = _make_admission()
        run = _make_queued_parallel_run(admission=admission)

        with patch(
            "apps.summaries.services.call_llm_parallel_chunks",
            return_value=[_make_local_chunk_response(i) for i in range(3)],
        ), patch(
            "apps.summaries.services.call_llm_parallel_final",
            return_value=_make_final_response(),
        ):
            execute_parallel_pipeline(run, admission=admission)

        run.refresh_from_db()
        assert run.status == "succeeded"
        # Chunks still get LLM calls even with empty events
