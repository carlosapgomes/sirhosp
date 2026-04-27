"""Unit tests for summary worker execution service (APS-S4).

Tests execute_summary_run() and _load_events_for_window() with
appropriate mocking at the model layer.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_llm_response():
    """Return a valid stub LLM response dict."""
    return {
        "estado_estruturado": {
            "motivo_internacao": "dor abdominal",
            "linha_do_tempo": [],
            "problemas_ativos": [],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": [],
            "intercorrencias": [],
            "pendencias": [],
            "riscos_eventos_adversos": [],
            "situacao_atual": "Paciente estável",
        },
        "resumo_markdown": "# Resumo\n\nPaciente internado...",
        "mudancas_da_rodada": ["Registro inicial"],
        "incertezas": [],
        "evidencias": [
            {"event_id": "evt-001", "snippet": "dor abdominal há 2 dias"},
        ],
    }


def _make_realistic_run():
    """Create a real SummaryRun (not mock) for service tests."""
    from apps.patients.models import Admission, Patient
    from apps.summaries.models import SummaryRun

    patient = Patient.objects.create(
        patient_source_key="S4-U001",
        source_system="tasy",
        name="Unit Test Patient",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_admission_key="S4-U-ADM",
        source_system="tasy",
        admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
    )
    run = SummaryRun.objects.create(
        admission=admission,
        mode="generate",
        target_end_date=date(2025, 1, 5),
        status="queued",
    )
    return run, admission


# ---------------------------------------------------------------------------
# _load_events_for_window
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoadEventsForWindow:
    """Unit tests for _load_events_for_window."""

    def test_returns_empty_list_when_no_events(self):
        """No events in window returns empty list."""
        from apps.summaries.services import _load_events_for_window

        run, admission = _make_realistic_run()
        run.pinned_cutoff_happened_at = datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=UTC
        )
        run.admission_id = admission.pk

        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert events == []

    def test_filters_by_admission(self):
        """Only events for the specified admission are returned."""
        from apps.clinical_docs.models import ClinicalEvent
        from apps.summaries.services import _load_events_for_window

        run, admission = _make_realistic_run()
        run.pinned_cutoff_happened_at = datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=UTC
        )
        run.admission_id = admission.pk

        # Create an event for this admission
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-001",
            content_hash="abc123",
            happened_at=datetime(2025, 1, 3, 14, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Paciente estável",
        )

        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert len(events) == 1
        assert events[0].admission_id == admission.pk

    def test_respects_window_bounds(self):
        """Events outside window date range are excluded."""
        from apps.clinical_docs.models import ClinicalEvent
        from apps.summaries.services import _load_events_for_window

        run, admission = _make_realistic_run()
        run.pinned_cutoff_happened_at = datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=UTC
        )
        run.admission_id = admission.pk

        # Event inside window
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-002",
            content_hash="abc124",
            happened_at=datetime(2025, 1, 3, 14, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Dentro da janela",
        )
        # Event outside window (after)
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-003",
            content_hash="abc125",
            happened_at=datetime(2025, 1, 10, 14, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Fora da janela",
        )

        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert len(events) == 1
        assert "Dentro" in events[0].content_text

    def test_respects_pinned_cutoff(self):
        """Events after the pinned cutoff are excluded."""
        from apps.clinical_docs.models import ClinicalEvent
        from apps.summaries.services import _load_events_for_window

        run, admission = _make_realistic_run()
        # Cutoff is Jan 3 at noon
        run.pinned_cutoff_happened_at = datetime(
            2025, 1, 3, 12, 0, 0, tzinfo=UTC
        )
        run.admission_id = admission.pk

        # Event before cutoff
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-004",
            content_hash="abc126",
            happened_at=datetime(2025, 1, 3, 10, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Antes do cutoff",
        )
        # Event after cutoff
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-005",
            content_hash="abc127",
            happened_at=datetime(2025, 1, 3, 14, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Depois do cutoff",
        )

        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert len(events) == 1
        assert "Antes" in events[0].content_text

    def test_events_ordered_by_happened_at(self):
        """Events are returned in chronological order."""
        from apps.clinical_docs.models import ClinicalEvent
        from apps.summaries.services import _load_events_for_window

        run, admission = _make_realistic_run()
        run.pinned_cutoff_happened_at = datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=UTC
        )
        run.admission_id = admission.pk

        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-006",
            content_hash="h06",
            happened_at=datetime(2025, 1, 5, 10, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Terceiro",
        )
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-007",
            content_hash="h07",
            happened_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Primeiro",
        )
        ClinicalEvent.objects.create(
            admission=admission,
            patient=admission.patient,
            ingestion_run_id=None,
            event_identity_key="evt-s4-008",
            content_hash="h08",
            happened_at=datetime(2025, 1, 3, 10, 0, tzinfo=UTC),
            author_name="Dr. Test",
            profession_type="medica",
            content_text="Segundo",
        )

        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert len(events) == 3
        assert events[0].content_text == "Primeiro"
        assert events[1].content_text == "Segundo"
        assert events[2].content_text == "Terceiro"


# ---------------------------------------------------------------------------
# execute_summary_run lifecycle (unit, using real models)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExecuteSummaryRunLifecycle:
    """Tests for the run lifecycle with stub gateway."""

    def test_run_transitions_to_succeeded(self):
        """Happy path: queued -> succeeded with stub gateway."""
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_pinned_cutoff_is_set_at_start(self):
        """Cutoff timestamp is set when execution begins."""
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()
        assert run.pinned_cutoff_happened_at is None

        execute_summary_run(run)

        run.refresh_from_db()
        assert run.pinned_cutoff_happened_at is not None

    def test_empty_windows_succeeds_immediately(self):
        """When no windows are planned (e.g., target before admission),
        the run succeeds with zero chunks."""
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()
        # Make target_end_date before admission_date => no windows
        run.target_end_date = date(2024, 12, 31)
        run.save(update_fields=["target_end_date"])

        execute_summary_run(run)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.total_chunks == 0

    def test_current_chunk_index_set_after_success(self):
        """After processing, current_chunk_index equals total_chunks."""
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        run.refresh_from_db()
        assert run.current_chunk_index == run.total_chunks
        assert run.total_chunks > 0


# ---------------------------------------------------------------------------
# State and version persistence (unit)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStateAndVersionPersistence:
    """After execution, AdmissionSummaryState and AdmissionSummaryVersion
    are persisted."""

    def test_state_is_created_for_new_admission(self):
        """A new AdmissionSummaryState is created during execution."""
        from apps.summaries.models import AdmissionSummaryState
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        assert not AdmissionSummaryState.objects.filter(
            admission=admission
        ).exists()

        execute_summary_run(run)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.narrative_markdown != ""
        assert state.structured_state_json != {}

    def test_state_updated_with_coverage(self):
        """State coverage reflects the windows processed."""
        from apps.summaries.models import AdmissionSummaryState
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.coverage_start == date(2025, 1, 1)
        assert state.coverage_end == date(2025, 1, 5)

    def test_version_is_created_for_each_chunk(self):
        """Each window produces an AdmissionSummaryVersion."""
        from apps.summaries.models import AdmissionSummaryVersion
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        run.refresh_from_db()
        versions = AdmissionSummaryVersion.objects.filter(run=run)
        assert versions.count() == run.total_chunks
        assert versions.count() > 0

    def test_version_has_evidences(self):
        """Version stores evidences_json from LLM response."""
        from apps.summaries.models import AdmissionSummaryVersion
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        version = AdmissionSummaryVersion.objects.filter(run=run).first()
        assert version is not None
        assert isinstance(version.evidences_json, list)
        if version.evidences_json:
            assert "event_id" in version.evidences_json[0]
            assert "snippet" in version.evidences_json[0]

    def test_version_has_correct_chunk_index(self):
        """Each version records its chunk_index."""
        from apps.summaries.models import AdmissionSummaryVersion
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        versions = list(
            AdmissionSummaryVersion.objects.filter(run=run).order_by(
                "chunk_index"
            )
        )
        for i, version in enumerate(versions):
            assert version.chunk_index == i


# ---------------------------------------------------------------------------
# Chunk tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChunkTracking:
    """SummaryRunChunk records are created correctly."""

    def test_chunks_created_for_each_window(self):
        """Each window gets a SummaryRunChunk."""
        from apps.summaries.models import SummaryRunChunk
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        chunks = SummaryRunChunk.objects.filter(run=run)
        assert chunks.count() == run.total_chunks
        assert chunks.count() > 0

    def test_all_chunks_succeeded(self):
        """In the happy path, all chunks are succeeded."""
        from apps.summaries.models import SummaryRunChunk
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        for chunk in SummaryRunChunk.objects.filter(run=run):
            assert chunk.status == "succeeded"

    def test_chunks_have_window_bounds(self):
        """Each chunk has proper window_start and window_end."""
        from apps.summaries.models import SummaryRunChunk
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        for chunk in SummaryRunChunk.objects.filter(run=run):
            assert chunk.window_start is not None
            assert chunk.window_end is not None
            assert chunk.window_start <= chunk.window_end

    def test_chunk_input_event_count_set(self):
        """Each chunk records input_event_count."""
        from apps.summaries.models import SummaryRunChunk
        from apps.summaries.services import execute_summary_run

        run, admission = _make_realistic_run()

        execute_summary_run(run)

        for chunk in SummaryRunChunk.objects.filter(run=run):
            # With no real events, count should be 0
            assert chunk.input_event_count == 0


# ---------------------------------------------------------------------------
# Correction: type hint fix for requested_by
# ---------------------------------------------------------------------------


class TestQueueSummaryRunTypeHintCorrection:
    """Ensure the requested_by type hint has been corrected to User."""

    def test_requested_by_accepts_user_not_model(self):
        """queue_summary_run should accept User, not models.Model."""
        from apps.summaries.services import queue_summary_run

        sig = inspect.signature(queue_summary_run)
        param = sig.parameters["requested_by"]
        annotation = str(param.annotation)

        # Should reference User, not models.Model
        # With __future__ annotations, 'User | None' is the string form
        assert "User" in annotation
        assert "models.Model" not in annotation
        assert "Model" not in annotation or "models" not in annotation


# ---------------------------------------------------------------------------
# llm_gateway stub tests
# ---------------------------------------------------------------------------


class TestLlmGatewayStub:
    """The stub LLM gateway returns a controlled response for tests."""

    def test_stub_returns_valid_dict(self):
        """Stub gateway returns a dict with required fields."""
        from apps.summaries.llm_gateway import call_llm_gateway

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert isinstance(result, dict)
        assert "estado_estruturado" in result
        assert "resumo_markdown" in result
        assert "mudancas_da_rodada" in result
        assert "incertezas" in result
        assert "evidencias" in result

    def test_stub_passes_schema_validation(self):
        """Stub output passes validate_summary_output."""
        from apps.summaries.llm_gateway import call_llm_gateway
        from apps.summaries.schema import validate_summary_output

        result = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        errors = validate_summary_output(result)
        assert len(errors) == 0

    def test_stub_is_deterministic(self):
        """Stub returns the same structure each time (deterministic)."""
        from apps.summaries.llm_gateway import call_llm_gateway

        r1 = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )
        r2 = call_llm_gateway(
            estado_estruturado_anterior={},
            resumo_markdown_anterior="",
            novas_evolucoes=[],
        )

        assert r1 == r2
