"""Integration tests for worker with cache-first gap planning (Slice S3).

Tests that the worker uses gap planning to avoid redundant extractions:
- Full coverage: extractor is never called.
- Partial coverage: extractor is called only for gap windows.
- No coverage: extractor is called for the full window.
"""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import compute_content_hash, compute_event_identity_key
from apps.patients.models import Admission, Patient

TZ_INST = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_patient_and_admission(
    *,
    patient_source_key: str = "12345",
    admission_key: str = "ADM001",
) -> tuple[Patient, Admission]:
    patient = Patient.objects.create(
        source_system="tasy",
        patient_source_key=patient_source_key,
        name="PACIENTE TESTE",
    )
    admission = Admission.objects.create(
        source_system="tasy",
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
) -> ClinicalEvent:
    from datetime import datetime

    evo_dict = {
        "admission_key": admission.source_admission_key,
        "happened_at": happened_at_str,
        "author_name": "DR. TEST",
        "source_system": "tasy",
    }
    identity_key = compute_event_identity_key(evo_dict)
    content = f"Event at {happened_at_str}"
    dt = datetime.strptime(happened_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_INST)

    return ClinicalEvent.objects.create(
        admission=admission,
        patient=patient,
        event_identity_key=identity_key,
        content_hash=compute_content_hash(content),
        happened_at=dt,
        author_name="DR. TEST",
        profession_type="medica",
        content_text=content,
        signature_line="Dr. Test CRM 123",
    )


def _queue_run(
    *,
    patient_record: str = "12345",
    start_date: str = "2026-04-10",
    end_date: str = "2026-04-12",
) -> IngestionRun:
    return IngestionRun.objects.create(
        status="queued",
        parameters_json={
            "patient_record": patient_record,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def _make_extractor_mock(evolutions=None):
    mock = MagicMock()
    mock.extract_evolutions.return_value = evolutions or []
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerGapPlanning:
    """Worker uses gap planning to skip redundant extractions."""

    def test_full_coverage_skips_extraction(self):
        """When all days in the window have events, extractor is NOT called."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-11 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-12 08:00:00")

        run = _queue_run(start_date="2026-04-10", end_date="2026-04-12")
        mock_ext = _make_extractor_mock()

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 0
        assert run.events_created == 0
        mock_ext.extract_evolutions.assert_not_called()
        assert run.gaps_json == []

    def test_no_coverage_extracts_full_window(self):
        """When no events exist, extractor is called for the full window."""
        run = _queue_run(patient_record="99999", start_date="2026-04-10", end_date="2026-04-12")
        evolutions = [
            {
                "happened_at": "2026-04-10T08:00:00",
                "content_text": "Nova evolução.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "99999",
                "source_system": "tasy",
                "patient_name": "PACIENTE SEM COBERTURA",
            }
        ]
        mock_ext = _make_extractor_mock(evolutions)

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_created == 1
        mock_ext.extract_evolutions.assert_called_once()
        call_args = mock_ext.extract_evolutions.call_args
        assert call_args.kwargs["start_date"] == "2026-04-10"
        assert call_args.kwargs["end_date"] == "2026-04-12"
        assert len(run.gaps_json) == 1
        assert run.gaps_json[0] == {"start_date": "2026-04-10", "end_date": "2026-04-12"}

    def test_partial_coverage_extracts_only_gaps(self):
        """When some days have events, extractor is called only for gap windows."""
        patient, admission = _create_patient_and_admission()
        # Event only on 2026-04-10 — days 11 and 12 are gaps
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")

        run = _queue_run(start_date="2026-04-10", end_date="2026-04-12")
        evolutions = [
            {
                "happened_at": "2026-04-11T09:00:00",
                "content_text": "Evolução do gap.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE TESTE",
            }
        ]
        mock_ext = _make_extractor_mock(evolutions)

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_created == 1
        mock_ext.extract_evolutions.assert_called_once()
        call_args = mock_ext.extract_evolutions.call_args
        # Should only extract the gap (2026-04-11 to 2026-04-12)
        assert call_args.kwargs["start_date"] == "2026-04-11"
        assert call_args.kwargs["end_date"] == "2026-04-12"
        assert len(run.gaps_json) == 1
        assert run.gaps_json[0] == {"start_date": "2026-04-11", "end_date": "2026-04-12"}

    def test_gaps_persisted_on_run(self):
        """Gap information is persisted on the IngestionRun for audit."""
        patient, admission = _create_patient_and_admission()
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-15 08:00:00")

        run = _queue_run(start_date="2026-04-10", end_date="2026-04-15")
        mock_ext = _make_extractor_mock([])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.gaps_json == [{"start_date": "2026-04-11", "end_date": "2026-04-14"}]

    def test_multiple_gap_windows(self):
        """Worker handles multiple non-contiguous gap windows."""
        patient, admission = _create_patient_and_admission()
        # Events on day 10 and 15 only → gaps on 11-12 and 13-14
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-10 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-13 08:00:00")
        _create_event(patient=patient, admission=admission, happened_at_str="2026-04-15 08:00:00")

        run = _queue_run(start_date="2026-04-10", end_date="2026-04-15")
        mock_ext = _make_extractor_mock([])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        # Two gap windows: 11-12 and 14-14
        assert len(run.gaps_json) == 2
        assert run.gaps_json[0] == {"start_date": "2026-04-11", "end_date": "2026-04-12"}
        assert run.gaps_json[1] == {"start_date": "2026-04-14", "end_date": "2026-04-14"}
        # Extractor called twice (once per gap)
        assert mock_ext.extract_evolutions.call_count == 2
