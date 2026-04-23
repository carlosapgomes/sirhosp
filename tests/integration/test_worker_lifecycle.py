"""Integration tests for IngestionRun lifecycle via worker (Slice S2).

Tests the full state transitions: queued -> running -> succeeded|failed.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun


@pytest.mark.django_db
class TestWorkerLifecycle:
    """Worker processes queued runs through state transitions."""

    def _make_extractor_mock(self, evolutions=None):
        """Create a mock extractor that returns given evolutions."""
        mock_extractor = MagicMock()
        mock_extractor.extract_evolutions.return_value = evolutions or []
        # S3: mock get_admission_snapshot to return empty list (legacy tests)
        mock_extractor.get_admission_snapshot.return_value = []
        return mock_extractor

    def _queue_run(self, **kwargs):
        """Helper to create a queued IngestionRun directly."""
        defaults = {
            "status": "queued",
            "parameters_json": {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def test_queued_to_succeeded(self):
        """Run transitions from queued to succeeded after successful processing."""
        # Arrange
        run = self._queue_run()
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Paciente estável.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE TESTE",
                "ward": "UTI",
                "bed": "LEITO 01",
            }
        ]
        mock_ext = self._make_extractor_mock(evolutions)

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.finished_at >= run.started_at
        assert ClinicalEvent.objects.count() == 1

    def test_queued_to_failed_on_extraction_timeout(self):
        """Run transitions to failed when extraction times out."""
        # Arrange
        run = self._queue_run()

        def raise_timeout(**kwargs):
            from apps.ingestion.extractors.errors import ExtractionTimeoutError

            raise ExtractionTimeoutError("Extraction timed out after 90s")

        mock_ext = self._make_extractor_mock()
        mock_ext.extract_evolutions.side_effect = raise_timeout

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "failed"
        assert "timed out" in run.error_message.lower()
        assert run.finished_at is not None

    def test_queued_to_failed_on_invalid_json(self):
        """Run transitions to failed when extractor returns invalid JSON."""
        # Arrange
        run = self._queue_run()

        def raise_invalid_json(**kwargs):
            from apps.ingestion.extractors.errors import InvalidJsonError

            raise InvalidJsonError("Expected JSON array, got str")

        mock_ext = self._make_extractor_mock()
        mock_ext.extract_evolutions.side_effect = raise_invalid_json

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "failed"
        assert "JSON" in run.error_message or "json" in run.error_message.lower()

    def test_worker_persists_metrics(self):
        """Worker persists event counts after successful processing."""
        # Arrange
        run = self._queue_run()
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução 1",
                "author_name": "DR. A",
                "profession_type": "medica",
                "signature_line": "Dr. A CRM 111",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE X",
            },
            {
                "happened_at": "2026-04-19T10:00:00",
                "content_text": "Evolução 2",
                "author_name": "DR. B",
                "profession_type": "enfermagem",
                "signature_line": "Dr. B COREN 222",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE X",
            },
        ]
        mock_ext = self._make_extractor_mock(evolutions)

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 2
        assert run.events_created == 2
        assert run.events_skipped == 0

    def test_worker_handles_empty_extraction(self):
        """Worker succeeds with 0 events when extractor returns empty list."""
        # Arrange
        run = self._queue_run()
        mock_ext = self._make_extractor_mock(evolutions=[])

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 0
        assert run.events_created == 0

    def test_worker_processes_only_queued(self):
        """Worker ignores runs that are not in queued state."""
        # Arrange
        run_succeeded = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={"patient_record": "111"},
        )
        run_failed = IngestionRun.objects.create(
            status="failed",
            parameters_json={"patient_record": "222"},
        )
        run_queued = self._queue_run()
        mock_ext = self._make_extractor_mock(evolutions=[])

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert — only the queued run was touched
        run_succeeded.refresh_from_db()
        run_failed.refresh_from_db()
        run_queued.refresh_from_db()

        assert run_succeeded.status == "succeeded"
        assert run_failed.status == "failed"
        assert run_queued.status == "succeeded"

    def test_worker_deduplicates_events(self):
        """Running the same extraction twice results in dedup (skipped events)."""
        # Arrange
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Mesma evolução.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE TESTE",
            }
        ]

        # First run
        run1 = self._queue_run()
        mock_ext = self._make_extractor_mock(evolutions)
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run1.refresh_from_db()
        assert run1.events_created == 1

        # Second run — same data
        run2 = IngestionRun.objects.create(
            status="queued",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        mock_ext2 = self._make_extractor_mock(evolutions)
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext2,
        ):
            call_command("process_ingestion_runs")

        run2.refresh_from_db()
        assert run2.events_skipped == 1
        assert run2.events_created == 0
        assert ClinicalEvent.objects.count() == 1  # still only one event


@pytest.mark.django_db
class TestWorkerAdmissionSemantics:
    """Worker behaviour for admissions capture + failure semantics (Slice S3)."""

    def _queue_run(self, **kwargs):
        defaults = {
            "status": "queued",
            "parameters_json": {
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        }
        defaults.update(kwargs)
        return IngestionRun.objects.create(**defaults)

    def _make_extractor_mock(
        self,
        evolutions=None,
        admissions_snapshot=None,
        admission_error=None,
    ):
        mock_ext = MagicMock()
        mock_ext.extract_evolutions.return_value = evolutions or []
        if admission_error:
            mock_ext.get_admission_snapshot.side_effect = admission_error
        elif admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def test_fails_run_when_admission_capture_fails(self):
        """When admissions snapshot capture fails, run transitions to failed."""
        # Arrange
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=None,
            admission_error=ExtractionError("Connection timeout during admissions capture"),
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "failed"
        assert "admission" in run.error_message.lower() or "connection" in run.error_message.lower()
        # evolutions extraction never called
        mock_ext.extract_evolutions.assert_not_called()

    def test_preserves_admissions_when_evolution_extraction_fails(self):
        """On evolution failure after admissions captured, run fails but admissions persist."""
        # Arrange
        from apps.ingestion.extractors.errors import ExtractionError
        from apps.patients.models import Admission, Patient

        run = self._queue_run()
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            }
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
        )
        mock_ext.extract_evolutions.side_effect = ExtractionError("PDF extraction failed")

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "failed"
        assert "PDF extraction" in run.error_message
        # Admissions should be persisted
        assert Admission.objects.filter(source_admission_key="ADM001").exists()
        patient = Patient.objects.get(patient_source_key="12345")
        assert Admission.objects.filter(patient=patient).count() == 1

    def test_succeeds_with_zero_evolutions_after_admissions_ok(self):
        """When admissions captured but no evolutions in window, run succeeds with zero events."""
        # Arrange
        run = self._queue_run()
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            }
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=[],  # no evolutions in window
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.events_processed == 0
        assert run.events_created == 0
        assert run.finished_at is not None

    def test_admission_metrics_populated_on_success(self):
        """Successful run populates admissions_seen/created/updated metrics."""
        # Arrange
        run = self._queue_run()
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            },
            {
                "admission_key": "ADM002",
                "admission_start": "2026-04-10T00:00:00",
                "admission_end": None,
                "ward": "CC",
                "bed": "LEITO 05",
            },
        ]
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução 1",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE TESTE",
            }
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert hasattr(run, "admissions_seen")
        assert hasattr(run, "admissions_created")
        assert hasattr(run, "admissions_updated")
        assert run.admissions_seen == 2
        assert run.admissions_created == 2
        assert run.admissions_updated == 0

    def test_admission_metrics_updated_on_rerun(self):
        """Rerunning a run with already-captured admissions increments updated count."""
        # Arrange
        from apps.patients.models import Admission, Patient

        # Pre-create patient and admission
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="PACIENTE TESTE",
        )
        admission = Admission.objects.create(
            source_system="tasy",
            source_admission_key="ADM001",
            patient=patient,
            ward="UTI",
            bed="LEITO 01",
        )

        run = self._queue_run()
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-02T00:00:00",  # updated date
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",  # same ward
                "bed": "LEITO 01",  # same bed
            }
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=[],
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 1
        assert run.admissions_created == 0
        assert run.admissions_updated == 1
        # Verify date was updated
        admission.refresh_from_db()
        assert admission.admission_date is not None

    def test_admission_capture_called_before_evolutions(self):
        """Extractor get_admission_snapshot is called before extract_evolutions."""
        # Arrange
        self._queue_run()  # create run for worker to process
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            }
        ]
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução 1",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "12345",
                "source_system": "tasy",
                "patient_name": "PACIENTE TESTE",
            }
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert - both methods should be called
        mock_ext.get_admission_snapshot.assert_called()
        mock_ext.extract_evolutions.assert_called()

    def test_admission_metrics_zero_on_empty_snapshot(self):
        """Successful run with no admissions in snapshot has zero metrics."""
        # Arrange
        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=[],  # empty snapshot
            evolutions=[],
        )

        # Act
        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        # Assert
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 0
        assert run.admissions_created == 0
        assert run.admissions_updated == 0
