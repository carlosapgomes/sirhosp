"""Tests for temporal coverage and gap planning (Slice S3).

Tests three scenarios:
- Full coverage: existing events cover the entire requested window.
- Partial coverage: some days have events, others don't.
- No coverage: no events exist in the requested window.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.gap_planner import compute_coverage_gaps, plan_extraction_windows
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient

TZ_INST = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_patient_and_admission(
    *,
    source_system: str = "tasy",
    patient_source_key: str = "P001",
    admission_key: str = "ADM001",
) -> tuple[Patient, Admission]:
    patient = Patient.objects.create(
        source_system=source_system,
        patient_source_key=patient_source_key,
        name="Paciente Teste",
    )
    admission = Admission.objects.create(
        source_system=source_system,
        source_admission_key=admission_key,
        patient=patient,
        ward="UTI",
        bed="LEITO 01",
    )
    return patient, admission


def _create_event(
    *,
    patient: Patient,
    admission: Admission,
    happened_at_str: str,
    run: IngestionRun | None = None,
) -> ClinicalEvent:
    """Create a ClinicalEvent with the given happened_at datetime string."""
    from apps.ingestion.services import compute_content_hash, compute_event_identity_key

    evo_dict = {
        "admission_key": admission.source_admission_key,
        "happened_at": happened_at_str,
        "author_name": "DR. TEST",
        "source_system": patient.source_system,
    }
    identity_key = compute_event_identity_key(evo_dict)
    content = f"Event at {happened_at_str}"
    dt = datetime.strptime(happened_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_INST)

    return ClinicalEvent.objects.create(
        admission=admission,
        patient=patient,
        ingestion_run=run,
        event_identity_key=identity_key,
        content_hash=compute_content_hash(content),
        happened_at=dt,
        author_name="DR. TEST",
        profession_type="medica",
        content_text=content,
        signature_line="Dr. Test CRM 123",
    )


# ---------------------------------------------------------------------------
# compute_coverage_gaps
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeCoverageGaps:
    """Calculate which date-ranges within a window have no events."""

    def test_full_coverage_no_gaps(self):
        """Events exist every day in the window → no gaps."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-11 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-12 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert gaps == []

    def test_no_coverage_full_gap(self):
        """No events exist in the window → single gap covering entire window."""
        # No events created
        gaps = compute_coverage_gaps(
            patient_source_key="P999",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-10", "end_date": "2026-04-12"}

    def test_partial_coverage_start_gap(self):
        """Events only at end → gap at the start."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-12 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-10", "end_date": "2026-04-11"}

    def test_partial_coverage_end_gap(self):
        """Events only at start → gap at the end."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-11", "end_date": "2026-04-12"}

    def test_partial_coverage_middle_gap(self):
        """Events at start and end → gap in the middle."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-14 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-14",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-11", "end_date": "2026-04-13"}

    def test_multiple_gaps(self):
        """Events scattered → multiple non-contiguous gaps."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-13 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-15",
        )

        assert len(gaps) == 2
        assert gaps[0] == {"start_date": "2026-04-11", "end_date": "2026-04-12"}
        assert gaps[1] == {"start_date": "2026-04-14", "end_date": "2026-04-15"}

    def test_single_day_window_with_event(self):
        """Single day window with event → no gaps."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")

        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-10",
        )

        assert gaps == []

    def test_single_day_window_without_event(self):
        """Single day window without event → single gap."""
        gaps = compute_coverage_gaps(
            patient_source_key="P999",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-10",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-10", "end_date": "2026-04-10"}

    def test_events_from_other_patient_ignored(self):
        """Events for a different patient don't affect coverage."""
        patient_a, admission_a = _create_patient_and_admission(
            patient_source_key="P001", admission_key="ADM001"
        )
        patient_b, admission_b = _create_patient_and_admission(
            patient_source_key="P002", admission_key="ADM002"
        )
        _create_event(
            patient=patient_a, admission=admission_a,
            happened_at_str="2026-04-10 08:00:00",
        )
        # Only P001 has events; P002 should have no coverage

        gaps = compute_coverage_gaps(
            patient_source_key="P002",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-10", "end_date": "2026-04-12"}

    def test_events_from_other_source_system_ignored(self):
        """Events from a different source_system don't affect coverage."""
        patient, admission = _create_patient_and_admission(
            source_system="tasy", patient_source_key="P001"
        )
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")

        # Query for same patient but different source system
        gaps = compute_coverage_gaps(
            patient_source_key="P001",
            source_system="other_system",
            start_date="2026-04-10",
            end_date="2026-04-12",
        )

        assert len(gaps) == 1
        assert gaps[0] == {"start_date": "2026-04-10", "end_date": "2026-04-12"}


# ---------------------------------------------------------------------------
# plan_extraction_windows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanExtractionWindows:
    """Determine whether to extract and what windows to extract."""

    def test_full_coverage_skips_extraction(self):
        """Full coverage → no windows to extract, skip flag is True."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-11 08:00:00")

        plan = plan_extraction_windows(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-11",
        )

        assert plan["skip_extraction"] is True
        assert plan["windows"] == []
        assert plan["gaps"] == []

    def test_no_coverage_extracts_full_window(self):
        """No coverage → extract the entire requested window."""
        plan = plan_extraction_windows(
            patient_source_key="P999",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-15",
        )

        assert plan["skip_extraction"] is False
        assert len(plan["windows"]) == 1
        assert plan["windows"][0] == {"start_date": "2026-04-10", "end_date": "2026-04-15"}
        assert plan["gaps"] == plan["windows"]

    def test_partial_coverage_extracts_only_gaps(self):
        """Partial coverage → extract only the gap windows."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-15 08:00:00")

        plan = plan_extraction_windows(
            patient_source_key="P001",
            source_system="tasy",
            start_date="2026-04-10",
            end_date="2026-04-15",
        )

        assert plan["skip_extraction"] is False
        assert len(plan["windows"]) == 1
        assert plan["windows"][0] == {"start_date": "2026-04-11", "end_date": "2026-04-14"}
        assert plan["gaps"] == plan["windows"]
