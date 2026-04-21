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
