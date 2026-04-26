"""Tests for summary domain models (APS-S1 RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

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
# AdmissionSummaryState
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdmissionSummaryState:
    def test_create_state_for_admission(self):
        """State can be created linked to an admission."""
        from apps.summaries.models import AdmissionSummaryState

        admission = _make_admission()
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={"motivo_internacao": "dor abdominal"},
            narrative_markdown="# Resumo\n\nPaciente internado...",
            status="draft",
        )
        assert state.pk is not None
        assert state.admission == admission
        assert state.status == "draft"
        assert state.created_at is not None
        assert state.updated_at is not None

    def test_one_to_one_per_admission(self):
        """Each admission can have at most one AdmissionSummaryState."""
        from apps.summaries.models import AdmissionSummaryState

        admission = _make_admission()
        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# State 1",
            status="draft",
        )
        with pytest.raises(IntegrityError):
            AdmissionSummaryState.objects.create(
                admission=admission,
                coverage_start=date(2025, 1, 1),
                coverage_end=date(2025, 1, 10),
                structured_state_json={},
                narrative_markdown="# State 2",
                status="draft",
            )

    def test_default_status_is_draft(self):
        """Default status is draft."""
        from apps.summaries.models import AdmissionSummaryState

        admission = _make_admission()
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# Draft",
        )
        assert state.status == "draft"

    def test_status_choices_constrained(self):
        """Status must be one of draft, complete, incomplete."""
        from apps.summaries.models import AdmissionSummaryState

        admission = _make_admission()
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# Test",
            status="complete",
        )
        assert state.status == "complete"
        state.status = "incomplete"
        state.save()
        state.refresh_from_db()
        assert state.status == "incomplete"

    def test_last_source_event_happened_at_optional(self):
        """last_source_event_happened_at can be null."""
        from apps.summaries.models import AdmissionSummaryState

        admission = _make_admission()
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# Test",
        )
        assert state.last_source_event_happened_at is None


# ---------------------------------------------------------------------------
# AdmissionSummaryVersion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdmissionSummaryVersion:
    def test_create_version_with_evidences(self):
        """Version stores immutable snapshot with evidence links."""
        from apps.summaries.models import (
            AdmissionSummaryState,
            AdmissionSummaryVersion,
            SummaryRun,
        )

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# State",
        )
        version = AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=0,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={"motivo": "dor"},
            narrative_markdown="# Chunk 0",
            changes_json={"added": ["motivo"]},
            uncertainties_json={},
            evidences_json=[
                {"event_id": "evt-001", "snippet": "Paciente refere dor..."},
            ],
            llm_provider="openai",
            llm_model="gpt-4o",
            prompt_version="v1",
            input_tokens=100,
            output_tokens=50,
        )
        assert version.pk is not None
        assert version.chunk_index == 0
        assert len(version.evidences_json) == 1
        assert version.evidences_json[0]["event_id"] == "evt-001"
        assert version.llm_provider == "openai"

    def test_version_relation_to_run(self):
        """Version is linked to its parent SummaryRun."""
        from apps.summaries.models import (
            AdmissionSummaryState,
            AdmissionSummaryVersion,
            SummaryRun,
        )

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# State",
        )
        v1 = AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=0,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={},
            narrative_markdown="# V1",
            changes_json={},
            uncertainties_json={},
            evidences_json=[],
        )
        v2 = AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=1,
            coverage_start=date(2025, 1, 3),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# V2",
            changes_json={},
            uncertainties_json={},
            evidences_json=[],
        )
        assert v1.run == run
        assert v2.run == run
        assert v1.chunk_index == 0
        assert v2.chunk_index == 1

    def test_version_ordering_by_created_at(self):
        """Versions are ordered by creation time."""
        from apps.summaries.models import (
            AdmissionSummaryState,
            AdmissionSummaryVersion,
            SummaryRun,
        )

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        state = AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# State",
        )
        v1 = AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=0,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={},
            narrative_markdown="# V1",
            changes_json={},
            uncertainties_json={},
            evidences_json=[],
        )
        v2 = AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=1,
            coverage_start=date(2025, 1, 3),
            coverage_end=date(2025, 1, 10),
            structured_state_json={},
            narrative_markdown="# V2",
            changes_json={},
            uncertainties_json={},
            evidences_json=[],
        )
        versions = list(AdmissionSummaryVersion.objects.all())
        assert versions[0] == v1
        assert versions[1] == v2


# ---------------------------------------------------------------------------
# SummaryRun
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryRun:
    def test_create_run_with_minimum_fields(self):
        """SummaryRun can be created with required fields."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        assert run.pk is not None
        assert run.status == "queued"
        assert run.admission == admission
        assert run.requested_by == user
        assert run.mode == "generate"

    def test_default_status_is_queued(self):
        """Default status for a new run is queued."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="update",
            target_end_date=date(2025, 1, 10),
        )
        assert run.status == "queued"

    def test_valid_status_transitions(self):
        """Run transitions through queued → running → succeeded."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        assert run.status == "queued"

        run.status = "running"
        run.started_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        run.save()
        run.refresh_from_db()
        assert run.status == "running"
        assert run.started_at is not None

        run.status = "succeeded"
        run.finished_at = datetime(2025, 1, 1, 12, 5, tzinfo=timezone.utc)
        run.save()
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.finished_at is not None

    def test_partial_status_preserves_error_message(self):
        """Partial run stores error message for observability."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
            status="partial",
            error_message="Chunk 3 failed after 3 retries",
        )
        assert run.status == "partial"
        assert "Chunk 3" in run.error_message

    def test_failed_status_with_error(self):
        """Failed run stores error for debugging."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="regenerate",
            target_end_date=date(2025, 1, 10),
            status="failed",
            error_message="LLM provider timeout",
        )
        assert run.status == "failed"
        assert run.error_message == "LLM provider timeout"

    def test_run_mode_choices(self):
        """Mode is one of generate, update, regenerate."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()

        for mode in ["generate", "update", "regenerate"]:
            run = SummaryRun.objects.create(
                admission=admission,
                requested_by=user,
                mode=mode,
                target_end_date=date(2025, 1, 10),
            )
            assert run.mode == mode

    def test_pinned_cutoff_happened_at_optional(self):
        """pinned_cutoff_happened_at is optional at creation time."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        assert run.pinned_cutoff_happened_at is None

    def test_run_ordering_by_created_at(self):
        """Runs are ordered by creation time (newest first) for operational visibility."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        user = _make_user()
        SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="update",
            target_end_date=date(2025, 1, 15),
        )
        runs = list(SummaryRun.objects.all())
        assert len(runs) == 2
        assert runs[0].created_at >= runs[1].created_at


# ---------------------------------------------------------------------------
# SummaryRunChunk
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryRunChunk:
    def test_create_chunk_for_run(self):
        """Chunk references its parent run with chunk_index."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
            attempt_count=0,
        )
        assert chunk.pk is not None
        assert chunk.run == run
        assert chunk.chunk_index == 0
        assert chunk.status == "queued"

    def test_chunk_default_status_queued(self):
        """Default chunk status is queued."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        assert chunk.status == "queued"

    def test_chunk_transitions_to_succeeded(self):
        """Chunk can transition to succeeded."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        chunk.status = "succeeded"
        chunk.save()
        chunk.refresh_from_db()
        assert chunk.status == "succeeded"

    def test_chunk_records_error_on_failure(self):
        """Failed chunk records error message."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
            status="failed",
            error_message="Connection reset",
            attempt_count=3,
        )
        assert chunk.status == "failed"
        assert chunk.error_message == "Connection reset"
        assert chunk.attempt_count == 3

    def test_chunk_attempt_count_tracks_retries(self):
        """attempt_count increments with each retry."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
            attempt_count=0,
        )
        chunk.attempt_count = 1
        chunk.save()
        chunk.refresh_from_db()
        assert chunk.attempt_count == 1

        chunk.attempt_count = 2
        chunk.save()
        chunk.refresh_from_db()
        assert chunk.attempt_count == 2

    def test_chunk_records_input_event_count(self):
        """Chunk tracks how many ClinicalEvents were used as input."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        chunk = SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
            input_event_count=42,
        )
        assert chunk.input_event_count == 42

    def test_multiple_chunks_per_run(self):
        """A run can have multiple chunks, each with unique chunk_index."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=0,
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 5),
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=1,
            window_start=date(2025, 1, 3),
            window_end=date(2025, 1, 8),
        )
        SummaryRunChunk.objects.create(
            run=run,
            chunk_index=2,
            window_start=date(2025, 1, 6),
            window_end=date(2025, 1, 10),
        )
        assert run.chunks.count() == 3
        assert set(run.chunks.values_list("chunk_index", flat=True)) == {0, 1, 2}

    def test_chunk_ordering(self):
        """Chunks are ordered by chunk_index ascending."""
        from apps.summaries.models import SummaryRun, SummaryRunChunk

        admission = _make_admission()
        user = _make_user()
        run = SummaryRun.objects.create(
            admission=admission,
            requested_by=user,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        SummaryRunChunk.objects.create(
            run=run, chunk_index=2,
            window_start=date(2025, 1, 6), window_end=date(2025, 1, 10),
        )
        SummaryRunChunk.objects.create(
            run=run, chunk_index=0,
            window_start=date(2025, 1, 1), window_end=date(2025, 1, 5),
        )
        SummaryRunChunk.objects.create(
            run=run, chunk_index=1,
            window_start=date(2025, 1, 3), window_end=date(2025, 1, 8),
        )
        indices = list(
            run.chunks.values_list("chunk_index", flat=True)
        )
        assert indices == [0, 1, 2]
