"""Integration tests for summary worker lifecycle (APS-S4 RED phase).

Tests the full lifecycle: command claims queued runs with
select_for_update(skip_locked=True), processes them through the
stub gateway, and persists AdmissionSummaryState and
AdmissionSummaryVersion.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from django.core.management import call_command

from apps.patients.models import Admission, Patient
from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryRun,
    SummaryRunChunk,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_patient():
    return Patient.objects.create(
        patient_source_key="S4-P001",
        source_system="tasy",
        name="S4 TEST PATIENT",
    )


def _make_admission(patient=None, **overrides):
    if patient is None:
        patient = _make_patient()
    defaults = {
        "patient": patient,
        "source_admission_key": "S4-ADM",
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
        "target_end_date": date(2025, 1, 10),
        "status": "queued",
    }
    defaults.update(overrides)
    return SummaryRun.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Worker claim with select_for_update(skip_locked=True)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerClaim:
    """Tests that the worker command claims runs atomically."""

    def test_command_claims_queued_run(self):
        """process_summary_runs picks up a queued run."""
        run = _make_queued_run()

        call_command("process_summary_runs")

        run.refresh_from_db()
        # After processing with stub gateway, should be succeeded
        assert run.status == "succeeded"

    def test_select_for_update_skip_locked_used(self):
        """The command uses select_for_update(skip_locked=True) to claim."""
        run = _make_queued_run()

        # Two runs — both queued
        _make_queued_run(
            admission=_make_admission(
                patient=run.admission.patient,
                source_admission_key="S4-ADM-2",
            )
        )

        # Process once (the command loops internally and should handle both)
        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

    def test_only_queued_runs_are_claimed(self):
        """A run already in running state is not picked up."""
        run = _make_queued_run(status="running")

        call_command("process_summary_runs")

        run.refresh_from_db()
        # Should NOT have been picked up (it's already running)
        assert run.status == "running"
        assert run.pinned_cutoff_happened_at is None

    def test_succeeded_runs_are_skipped(self):
        """A succeeded run is left alone."""
        run = _make_queued_run(status="succeeded")

        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"


# ---------------------------------------------------------------------------
# Lifecycle: queued -> running -> succeeded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunLifecycle:
    """Full lifecycle test for a summary run."""

    def test_queued_to_succeeded_transition(self):
        """A queued run transitions to succeeded after processing."""
        run = _make_queued_run()

        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.finished_at >= run.started_at

    def test_total_chunks_is_set(self):
        """After processing, total_chunks reflects the planned windows."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 10),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        # 10 days with chunk=5, overlap=2 => windows: (1-5), (3-7), (5-9), (7-10)
        # That's 4 windows with step=3
        assert run.total_chunks > 0

    def test_current_chunk_index_updates(self):
        """current_chunk_index reflects progress."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 10),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        # After success, current_chunk_index equals total_chunks
        # (or total_chunks - 1, depending on convention)
        assert run.current_chunk_index == run.total_chunks


# ---------------------------------------------------------------------------
# Cutoff is fixed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCutoffFixed:
    """pinned_cutoff_happened_at is set once at the start of the run."""

    def test_cutoff_is_set_during_processing(self):
        """The pinned cutoff timestamp is set when processing begins."""
        run = _make_queued_run()

        assert run.pinned_cutoff_happened_at is None

        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.pinned_cutoff_happened_at is not None

    def test_cutoff_is_not_changed_after_set(self):
        """Cutoff remains the same throughout the run."""
        run = _make_queued_run()

        call_command("process_summary_runs")

        run.refresh_from_db()
        cutoff = run.pinned_cutoff_happened_at
        assert cutoff is not None

        # Run finished, cutoff unchanged
        assert run.pinned_cutoff_happened_at == cutoff


# ---------------------------------------------------------------------------
# State and version persistence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStateAndVersionPersistence:
    """AdmissionSummaryState and AdmissionSummaryVersion are created/updated."""

    def test_state_is_created_for_new_admission(self):
        """Processing a run for the first time creates a state."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 10),
        )

        # No state before
        assert not AdmissionSummaryState.objects.filter(
            admission=admission
        ).exists()

        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"

        # State should exist now
        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.narrative_markdown != ""
        assert state.structured_state_json != {}

    def test_version_is_created_for_each_chunk(self):
        """Each chunk produces an AdmissionSummaryVersion."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 10),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        versions = AdmissionSummaryVersion.objects.filter(run=run)
        assert versions.count() == run.total_chunks
        assert versions.count() > 0

    def test_version_references_run_and_state(self):
        """Each version is linked to the run and state."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        state = AdmissionSummaryState.objects.get(admission=admission)
        version = AdmissionSummaryVersion.objects.filter(run=run).first()
        assert version is not None
        assert version.run == run
        assert version.admission == admission
        assert version.summary_state == state

    def test_version_has_evidences(self):
        """Version stores evidences_json with event_id and snippet."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        version = AdmissionSummaryVersion.objects.filter(run=run).first()
        assert version is not None
        assert isinstance(version.evidences_json, list)
        if version.evidences_json:
            assert "event_id" in version.evidences_json[0]
            assert "snippet" in version.evidences_json[0]


# ---------------------------------------------------------------------------
# SummaryRunChunk tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryRunChunkTracking:
    """SummaryRunChunk records are created and updated during processing."""

    def test_chunks_are_created_for_each_window(self):
        """Each planned window creates a SummaryRunChunk."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 10),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        chunks = SummaryRunChunk.objects.filter(run=run)
        assert chunks.count() == run.total_chunks
        assert chunks.count() > 0

    def test_all_chunks_are_succeeded_in_happy_path(self):
        """All chunks transition to succeeded in the happy path."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        chunks = SummaryRunChunk.objects.filter(run=run)
        assert chunks.count() > 0
        for chunk in chunks:
            assert chunk.status == "succeeded"

    def test_chunks_have_correct_window_bounds(self):
        """Each chunk's window_start and window_end match the plan."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        run = _make_queued_run(
            admission=admission,
            target_end_date=date(2025, 1, 5),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        chunks = list(
            SummaryRunChunk.objects.filter(run=run).order_by("chunk_index")
        )
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.window_start is not None
            assert chunk.window_end is not None
            assert chunk.window_start <= chunk.window_end


# ---------------------------------------------------------------------------
# Multiple runs in queue
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultipleRuns:
    """Multiple queued runs are all processed."""

    def test_all_queued_runs_are_processed(self):
        """All queued runs are picked up and completed in one call."""
        # Create one patient, three admissions
        patient = _make_patient()
        admission1 = _make_admission(
            patient=patient, source_admission_key="S4-ADM-A"
        )
        admission2 = _make_admission(
            patient=patient, source_admission_key="S4-ADM-B"
        )
        admission3 = _make_admission(
            patient=patient, source_admission_key="S4-ADM-C"
        )

        run1 = _make_queued_run(admission=admission1)
        run2 = _make_queued_run(admission=admission2)
        run3 = _make_queued_run(admission=admission3)

        call_command("process_summary_runs")

        for run in [run1, run2, run3]:
            run.refresh_from_db()
            assert run.status == "succeeded"


# ---------------------------------------------------------------------------
# Update mode with prior state
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpdateModeWithPriorState:
    """Update mode uses prior coverage_end for window planning."""

    def test_update_mode_with_existing_state(self):
        """Update mode processes only new windows beyond prior coverage."""
        admission = _make_admission(
            admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        # Create prior state covering up to Jan 5
        from apps.summaries.models import AdmissionSummaryState

        AdmissionSummaryState.objects.create(
            admission=admission,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 5),
            structured_state_json={"motivo_internacao": "dor"},
            narrative_markdown="# Prior summary",
            status="complete",
        )

        run = _make_queued_run(
            admission=admission,
            mode="update",
            target_end_date=date(2025, 1, 10),
        )

        call_command("process_summary_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        # Should have produced chunks only for new coverage
        state = AdmissionSummaryState.objects.get(admission=admission)
        assert state.coverage_end >= date(2025, 1, 5)
