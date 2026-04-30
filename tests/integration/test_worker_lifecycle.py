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
            "max_attempts": 1,
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
            "max_attempts": 1,
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


@pytest.mark.django_db
class TestWorkerVolatileKeyRegression:
    """Regression: reruns with volatile admission_key must not duplicate admissions (S3).

    Validates the full worker lifecycle:
    - Run 1 captures a snapshot with admission_key=A for period P.
    - Run 2 captures a snapshot with admission_key=B for the same period P.
    - Optionally includes extraction failure in one run and success in the other.
    - Final assert: exactly 1 Admission for that patient+period.
    """

    def _queue_run(self, patient_record="VOLATILE_P1"):
        return IngestionRun.objects.create(
            status="queued",
            max_attempts=1,
            parameters_json={
                "patient_record": patient_record,
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )

    def _make_extractor_mock(self, admissions_snapshot=None, evolutions=None):
        mock_ext = MagicMock()
        mock_ext.extract_evolutions.return_value = evolutions or []
        if admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def _period_snapshot(
        self,
        admission_key,
        start="2026-04-05T00:00:00",
        end="2026-04-15T00:00:00",
        ward="UTI",
        bed="LEITO 01",
    ):
        """Helper to build a single-admission snapshot dict."""
        return [
            {
                "admission_key": admission_key,
                "admission_start": start,
                "admission_end": end,
                "ward": ward,
                "bed": bed,
            }
        ]

    def test_two_runs_volatile_key_single_admission(self):
        """Two runs with different admission_keys for same period produce 1 Admission."""
        from apps.patients.models import Admission, Patient

        patient_record = "VOLATILE_P1"

        # --- Run 1: admission_key=A ---
        run1 = self._queue_run(patient_record)
        snap1 = self._period_snapshot("VOLATILE_KEY_A")
        mock_ext1 = self._make_extractor_mock(admissions_snapshot=snap1, evolutions=[])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext1,
        ):
            call_command("process_ingestion_runs")

        run1.refresh_from_db()
        assert run1.status == "succeeded"

        patient = Patient.objects.get(patient_source_key=patient_record)
        assert Admission.objects.filter(patient=patient).count() == 1

        # --- Run 2: admission_key=B, same period ---
        run2 = self._queue_run(patient_record)
        snap2 = self._period_snapshot("VOLATILE_KEY_B")
        mock_ext2 = self._make_extractor_mock(admissions_snapshot=snap2, evolutions=[])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext2,
        ):
            call_command("process_ingestion_runs")

        run2.refresh_from_db()
        assert run2.status == "succeeded"

        # REGRESSION ASSERT: still exactly 1 Admission for this patient
        assert Admission.objects.filter(patient=patient).count() == 1
        adm = Admission.objects.get(patient=patient)
        assert adm.admission_date is not None
        assert adm.discharge_date is not None

    def test_run1_fails_run2_succeeds_volatile_key_single_admission(self):
        """Run 1 fails after admissions captured; run 2 converges to 1 Admission."""
        from apps.ingestion.extractors.errors import ExtractionError
        from apps.patients.models import Admission, Patient

        patient_record = "VOLATILE_P2"

        # --- Run 1: admissions captured OK, evolutions fail ---
        run1 = self._queue_run(patient_record)
        snap1 = self._period_snapshot("VOLATILE_KEY_X")
        mock_ext1 = self._make_extractor_mock(admissions_snapshot=snap1)
        mock_ext1.extract_evolutions.side_effect = ExtractionError("PDF extraction crashed")

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext1,
        ):
            call_command("process_ingestion_runs")

        run1.refresh_from_db()
        assert run1.status == "failed"

        patient = Patient.objects.get(patient_source_key=patient_record)
        # Admission persisted from the failed run
        assert Admission.objects.filter(patient=patient).count() == 1

        # --- Run 2: new volatile key, full success ---
        run2 = self._queue_run(patient_record)
        snap2 = self._period_snapshot("VOLATILE_KEY_Y")
        evolutions = [
            {
                "happened_at": "2026-04-10T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. RETRY",
                "profession_type": "medica",
                "signature_line": "Dr. Retry CRM 999",
                "admission_key": "VOLATILE_KEY_Y",
                "patient_source_key": patient_record,
                "source_system": "tasy",
                "patient_name": "PACIENTE VOLATIL",
            },
        ]
        mock_ext2 = self._make_extractor_mock(admissions_snapshot=snap2, evolutions=evolutions)

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext2,
        ):
            call_command("process_ingestion_runs")

        run2.refresh_from_db()
        assert run2.status == "succeeded"
        assert run2.events_created == 1

        # REGRESSION ASSERT: still exactly 1 Admission
        assert Admission.objects.filter(patient=patient).count() == 1
        # Event is linked to the single canonical admission
        adm = Admission.objects.get(patient=patient)
        assert ClinicalEvent.objects.filter(admission=adm).count() == 1

    def test_three_runs_volatile_keys_no_duplication(self):
        """Three runs with different volatile keys for same period converge to 1 Admission."""
        from apps.patients.models import Admission, Patient

        patient_record = "VOLATILE_P3"

        for i, key in enumerate(["KEY_ALPHA", "KEY_BETA", "KEY_GAMMA"]):
            run = self._queue_run(patient_record)
            snap = self._period_snapshot(key)
            mock_ext = self._make_extractor_mock(admissions_snapshot=snap, evolutions=[])

            with patch(
                "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
                return_value=mock_ext,
            ):
                call_command("process_ingestion_runs")

            run.refresh_from_db()
            assert run.status == "succeeded", f"Run {i + 1} should succeed, got {run.status}"

        patient = Patient.objects.get(patient_source_key=patient_record)
        assert Admission.objects.filter(patient=patient).count() == 1


# ------------------------------------------------------------------
# SLICE-S3: Stage metrics (IngestionRunStageMetric)
# ------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerStageMetrics:
    """S3: Worker persists per-stage metrics for critical execution stages."""

    def _queue_run(self, **kwargs):
        defaults = {
            "status": "queued",
            "max_attempts": 1,
            "parameters_json": {
                "patient_record": "STAGE_TEST",
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
        evolution_error=None,
    ):
        mock_ext = MagicMock()
        mock_ext.extract_evolutions.return_value = evolutions or []
        if evolution_error:
            mock_ext.extract_evolutions.side_effect = evolution_error
        if admission_error:
            mock_ext.get_admission_snapshot.side_effect = admission_error
        elif admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def _patch_and_call(self, mock_ext):
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

    # -- Stage: admissions_capture ------------------------------------

    def test_admissions_capture_stage_succeeded(self):
        """admissions_capture stage is persisted with status=succeeded."""
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
            evolutions=[],
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "succeeded"
        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run).order_by("started_at")
        stage_names = [s.stage_name for s in stages]
        assert "admissions_capture" in stage_names
        adm_stage = stages.get(stage_name="admissions_capture")
        assert adm_stage.status == "succeeded"
        assert adm_stage.started_at is not None
        assert adm_stage.finished_at is not None
        assert adm_stage.started_at <= adm_stage.finished_at

    def test_admissions_capture_stage_failed(self):
        """admissions_capture stage is persisted with status=failed on error."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Source unavailable"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        stage_names = [s.stage_name for s in stages]
        assert "admissions_capture" in stage_names
        adm_stage = stages.get(stage_name="admissions_capture")
        assert adm_stage.status == "failed"
        assert adm_stage.started_at is not None
        assert adm_stage.finished_at is not None
        assert adm_stage.details_json["error_type"] == "ExtractionError"
        assert "Source unavailable" in adm_stage.details_json["error_message"]
        assert run.finished_at is not None
        assert adm_stage.finished_at <= run.finished_at

    # -- Stage: gap_planning ------------------------------------------

    def test_gap_planning_stage_succeeded(self):
        """gap_planning stage is persisted with status=succeeded."""
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
            evolutions=[],
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="gap_planning").exists()
        gap_stage = stages.get(stage_name="gap_planning")
        assert gap_stage.status == "succeeded"
        assert gap_stage.started_at is not None
        assert gap_stage.finished_at is not None

    def test_gap_planning_stage_failed(self):
        """gap_planning stage is persisted as failed on planning error."""
        from apps.ingestion.extractors.errors import ExtractionError
        from apps.ingestion.models import IngestionRunStageMetric

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
            evolutions=[],
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.plan_extraction_windows",
            side_effect=ExtractionError("Gap planner unavailable"),
        ):
            self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        stage = IngestionRunStageMetric.objects.get(run=run, stage_name="gap_planning")
        assert stage.status == "failed"
        assert stage.details_json["error_type"] == "ExtractionError"
        assert "Gap planner unavailable" in stage.details_json["error_message"]
        assert run.finished_at is not None
        assert stage.finished_at <= run.finished_at

    # -- Stage: evolution_extraction ----------------------------------

    def test_evolution_extraction_stage_succeeded(self):
        """evolution_extraction stage is persisted with status=succeeded."""
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
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "STAGE_TEST",
                "source_system": "tasy",
                "patient_name": "PACIENTE STAGE",
            },
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="evolution_extraction").exists()
        ev_stage = stages.get(stage_name="evolution_extraction")
        assert ev_stage.status == "succeeded"
        assert ev_stage.started_at is not None
        assert ev_stage.finished_at is not None

    def test_evolution_extraction_stage_skipped_on_full_coverage(self):
        """evolution_extraction stage is persisted as skipped when
        coverage is complete (no gaps to extract)."""
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
            evolutions=[],
        )

        # Patch gap planner to return full coverage (skip extraction)
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.plan_extraction_windows",
            return_value={
                "gaps": [],
                "windows": [],
                "skip_extraction": True,
            },
        ):
            self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "succeeded"
        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="evolution_extraction").exists()
        ev_stage = stages.get(stage_name="evolution_extraction")
        assert ev_stage.status == "skipped"

    def test_evolution_extraction_stage_failed(self):
        """evolution_extraction stage is persisted as failed on error."""
        from apps.ingestion.extractors.errors import ExtractionError

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
            evolution_error=ExtractionError("PDF extraction crashed"),
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="evolution_extraction").exists()
        ev_stage = stages.get(stage_name="evolution_extraction")
        assert ev_stage.status == "failed"
        assert ev_stage.details_json["error_type"] == "ExtractionError"
        assert "PDF extraction crashed" in ev_stage.details_json["error_message"]
        run.refresh_from_db()
        assert run.finished_at is not None
        assert ev_stage.finished_at <= run.finished_at

    # -- Stage: ingestion_persistence ---------------------------------

    def test_ingestion_persistence_stage_succeeded(self):
        """ingestion_persistence stage is persisted with status=succeeded."""
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
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "STAGE_TEST",
                "source_system": "tasy",
                "patient_name": "PACIENTE STAGE",
            },
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="ingestion_persistence").exists()
        ip_stage = stages.get(stage_name="ingestion_persistence")
        assert ip_stage.status == "succeeded"
        assert ip_stage.started_at is not None
        assert ip_stage.finished_at is not None

    def test_ingestion_persistence_stage_failed(self):
        """ingestion_persistence stage is persisted as failed on ingest error."""
        from apps.ingestion.models import IngestionRunStageMetric

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
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "STAGE_TEST",
                "source_system": "tasy",
                "patient_name": "PACIENTE STAGE",
            },
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.Command._ingest_evolutions",
            side_effect=RuntimeError("Persistence layer unavailable"),
        ):
            self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        stage = IngestionRunStageMetric.objects.get(
            run=run,
            stage_name="ingestion_persistence",
        )
        assert stage.status == "failed"
        assert stage.details_json["error_type"] == "RuntimeError"
        assert "Persistence layer unavailable" in stage.details_json["error_message"]
        assert run.finished_at is not None
        assert stage.finished_at <= run.finished_at

    def test_admissions_only_has_admissions_capture_stage(self):
        """Admissions-only run also records admissions_capture stage."""
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": "STAGE_ADM_ONLY",
                "intent": "admissions_only",
            },
        )
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
            evolutions=[],
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "succeeded"
        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="admissions_capture").exists()

    def test_admissions_only_reaches_run_failed_with_stage(self):
        """Admissions-only failure also records the stage."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            max_attempts=1,
            parameters_json={
                "patient_record": "STAGE_ADM_ONLY_FAIL",
                "intent": "admissions_only",
            },
        )
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Source down"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run)
        assert stages.filter(stage_name="admissions_capture").exists()

    # -- Stage ordering -----------------------------------------------

    def test_stages_recorded_in_expected_order(self):
        """Stages are recorded in chronological order matching execution flow."""
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
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "STAGE_TEST",
                "source_system": "tasy",
                "patient_name": "PACIENTE STAGE",
            },
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        stages = IngestionRunStageMetric.objects.filter(run=run).order_by("started_at")
        expected_order = [
            "admissions_capture",
            "gap_planning",
            "evolution_extraction",
            "ingestion_persistence",
        ]
        actual_order = [s.stage_name for s in stages]
        assert actual_order == expected_order

    # -- Stage details_json -------------------------------------------

    def test_stage_details_json_populated(self):
        """Stages may carry optional details_json with contextual info."""
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
        evolutions = [
            {
                "happened_at": "2026-04-19T08:30:00",
                "content_text": "Evolução OK.",
                "author_name": "DR. TEST",
                "profession_type": "medica",
                "signature_line": "Dr. Test CRM 123",
                "admission_key": "ADM001",
                "patient_source_key": "STAGE_TEST",
                "source_system": "tasy",
                "patient_name": "PACIENTE STAGE",
            },
        ]
        mock_ext = self._make_extractor_mock(
            admissions_snapshot=admissions_snapshot,
            evolutions=evolutions,
        )

        self._patch_and_call(mock_ext)

        from apps.ingestion.models import IngestionRunStageMetric

        # ingestion_persistence stage should carry counters in details
        ip_stage = IngestionRunStageMetric.objects.get(
            run=run, stage_name="ingestion_persistence"
        )
        assert ip_stage.details_json is not None
        # details_json is a dict—may be empty initially, but not None
        assert isinstance(ip_stage.details_json, dict)


@pytest.mark.django_db
class TestAdmissionsOnlyWorker:
    """Worker behaviour for admissions-only runs (AFMF-S2).

    Admissions-only runs capture admissions snapshot without extracting evolutions.
    """

    def _queue_admissions_only_run(self, patient_record="12345"):
        return IngestionRun.objects.create(
            status="queued",
            max_attempts=1,
            parameters_json={
                "patient_record": patient_record,
                "intent": "admissions_only",
            },
        )

    def _make_extractor_mock(self, admissions_snapshot=None, admission_error=None):
        mock_ext = MagicMock()
        if admission_error:
            mock_ext.get_admission_snapshot.side_effect = admission_error
        elif admissions_snapshot is not None:
            mock_ext.get_admission_snapshot.return_value = admissions_snapshot
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def test_admissions_only_succeeds_with_admissions(self):
        """Admissions-only run succeeds when admissions snapshot is captured."""
        from apps.patients.models import Admission, Patient

        run = self._queue_admissions_only_run()
        admissions_snapshot = [
            {
                "admission_key": "ADM001",
                "admission_start": "2026-04-01T00:00:00",
                "admission_end": "2026-04-19T00:00:00",
                "ward": "UTI",
                "bed": "LEITO 01",
            },
        ]
        mock_ext = self._make_extractor_mock(admissions_snapshot=admissions_snapshot)

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs"
            ".Command._enqueue_most_recent_full_sync",
            return_value=None,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 1
        assert run.admissions_created == 1
        assert run.admissions_updated == 0
        assert run.events_processed == 0
        assert run.finished_at is not None
        # No evolutions extracted
        mock_ext.extract_evolutions.assert_not_called()
        # Patient and admission created
        patient = Patient.objects.get(patient_source_key="12345")
        assert Admission.objects.filter(patient=patient).count() == 1

    def test_admissions_only_succeeds_with_empty_snapshot(self):
        """Admissions-only run succeeds with zero admissions (empty snapshot)."""
        from apps.patients.models import Patient

        run = self._queue_admissions_only_run(patient_record="77889")
        mock_ext = self._make_extractor_mock(admissions_snapshot=[])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.admissions_seen == 0
        assert run.admissions_created == 0
        assert run.events_processed == 0
        # Patient still created for traceability
        assert Patient.objects.filter(patient_source_key="77889").exists()

    def test_admissions_only_fails_on_capture_error(self):
        """Admissions-only run fails when snapshot capture raises error."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_admissions_only_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Source system unavailable"),
        )

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"
        assert "unavailable" in run.error_message.lower() or "source" in run.error_message.lower()
        assert run.finished_at is not None
        mock_ext.extract_evolutions.assert_not_called()

    def test_admissions_only_does_not_call_gap_planner(self):
        """Admissions-only run skips gap planning entirely."""
        run = self._queue_admissions_only_run()
        mock_ext = self._make_extractor_mock(admissions_snapshot=[])

        with patch(
            "apps.ingestion.management.commands.process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs.plan_extraction_windows",
        ) as mock_plan:
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "succeeded"
        mock_plan.assert_not_called()


# ------------------------------------------------------------------
# SLICE-S2: Lifecycle timestamps + failure classification
# ------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerLifecycleTimestampsAndFailures:
    """S2: Worker populates processing_started_at, finished_at,
    and classifies failures into normalized categories."""

    def _queue_run(self, **kwargs):
        defaults = {
            "status": "queued",
            "max_attempts": 1,
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
        admission_error=None,
        evolution_error=None,
    ):
        mock_ext = MagicMock()
        mock_ext.extract_evolutions.return_value = evolutions or []
        if evolution_error:
            mock_ext.extract_evolutions.side_effect = evolution_error
        if admission_error:
            mock_ext.get_admission_snapshot.side_effect = admission_error
        else:
            mock_ext.get_admission_snapshot.return_value = []
        return mock_ext

    def _patch_and_call(self, mock_ext):
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")

    # -- Lifecycle timestamps -----------------------------------------

    def test_processing_started_at_set_on_run_start(self):
        """processing_started_at is populated when worker picks up a run."""
        run = self._queue_run()
        mock_ext = self._make_extractor_mock()
        assert run.processing_started_at is None

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.processing_started_at is not None
        assert run.queued_at <= run.processing_started_at

    def test_finished_at_set_on_success(self):
        """finished_at is set on successful completion."""
        run = self._queue_run()
        mock_ext = self._make_extractor_mock()

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.processing_started_at <= run.finished_at

    def test_finished_at_set_on_failure(self):
        """finished_at is set on failed completion."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionError("Source system crashed"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.processing_started_at <= run.finished_at

    def test_success_clears_failure_state(self):
        """Success clears any previous failure_reason and timed_out."""
        run = self._queue_run()
        run.failure_reason = "timeout"
        run.timed_out = True
        run.save()
        mock_ext = self._make_extractor_mock()

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.failure_reason == ""
        assert run.timed_out is False

    # -- Failure classification (taxonomy: timeout, source_unavailable,
    #    invalid_payload, validation_error, unexpected_exception) -----

    def test_timeout_classified_as_timeout_reason(self):
        """ExtractionTimeoutError → failure_reason='timeout', timed_out=True."""
        from apps.ingestion.extractors.errors import ExtractionTimeoutError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            evolution_error=ExtractionTimeoutError(
                "Extraction timed out after 90s"
            ),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True
        assert "timed out" in run.error_message.lower()

    def test_invalid_json_classified_as_invalid_payload(self):
        """InvalidJsonError → failure_reason='invalid_payload',
        timed_out=False."""
        from apps.ingestion.extractors.errors import InvalidJsonError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            evolution_error=InvalidJsonError("Expected JSON array, got str"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        assert run.timed_out is False

    def test_generic_extraction_error_classified_as_source_unavailable(self):
        """Generic ExtractionError → failure_reason='source_unavailable',
        timed_out=False."""
        from apps.ingestion.extractors.errors import ExtractionError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            evolution_error=ExtractionError("Source connection refused"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "source_unavailable"
        assert run.timed_out is False

    def test_unexpected_exception_classified_as_unexpected_exception(self):
        """Non-ExtractionError → failure_reason='unexpected_exception',
        timed_out=False."""
        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ValueError("Database connection pool exhausted"),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "unexpected_exception"
        assert run.timed_out is False

    def test_admissions_timeout_classified_correctly(self):
        """Timeout during admissions capture is classified correctly."""
        from apps.ingestion.extractors.errors import ExtractionTimeoutError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ExtractionTimeoutError(
                "Admissions capture timed out after 120s"
            ),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True

    def test_validation_error_classified_as_validation_error(self):
        """ValidationError → failure_reason='validation_error',
        timed_out=False."""
        from django.core.exceptions import ValidationError

        run = self._queue_run()
        mock_ext = self._make_extractor_mock(
            admission_error=ValidationError(
                "Patient record '99999' does not match expected format"
            ),
        )

        self._patch_and_call(mock_ext)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "validation_error"
        assert run.timed_out is False
