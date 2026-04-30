"""Unit tests for CensusExecutionBatch integration in process_census_snapshot.

CQM-S2: Batch na enfileiração do censo.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import process_census_snapshot
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.patients.models import Patient


@pytest.mark.django_db
class TestProcessCensusSnapshotCreatesBatch:
    """RED tests for batch creation during census snapshot processing."""

    def _create_snapshot_with_patient(
        self, prontuario: str = "14160147", nome: str = "FULANO DE TAL"
    ):
        """Helper to create an occupied census snapshot."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI A",
            leito="UG01A",
            prontuario=prontuario,
            nome=nome,
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

    def test_creates_batch_when_enqueuing_runs(self):
        """process_census_snapshot creates a CensusExecutionBatch(status=running)."""
        self._create_snapshot_with_patient()

        # No batch exists initially
        assert CensusExecutionBatch.objects.count() == 0

        result = process_census_snapshot()

        # A batch was created
        assert CensusExecutionBatch.objects.count() == 1
        batch = CensusExecutionBatch.objects.first()
        assert batch is not None
        assert batch.status == "running"
        assert result["batch_id"] == batch.pk

    def test_runs_enqueued_are_linked_to_batch(self):
        """All runs enqueued by process_census_snapshot have batch_id set."""
        # Share captured_at so both snapshots are picked up by Max("captured_at")
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="UG01A",
            prontuario="11111",
            nome="FULANO UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI B",
            leito="UG01B",
            prontuario="22222",
            nome="FULANO DOIS",
            especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        result = process_census_snapshot()

        batch_id = result["batch_id"]
        assert batch_id is not None

        # All queued runs should be linked to the batch
        runs = IngestionRun.objects.filter(batch_id=batch_id)
        # 2 patients × 2 intents (admissions_only + demographics_only) = 4 runs
        assert runs.count() == 4
        for run in runs:
            assert run.batch_id == batch_id

    def test_result_includes_batch_id(self):
        """Return dict includes batch_id key."""
        self._create_snapshot_with_patient()

        result = process_census_snapshot()

        assert "batch_id" in result
        assert result["batch_id"] is not None
        assert isinstance(result["batch_id"], int)

    def test_enqueue_finished_at_is_set(self):
        """enqueue_finished_at is populated after enqueuing runs."""
        self._create_snapshot_with_patient()

        result = process_census_snapshot()

        batch = CensusExecutionBatch.objects.get(pk=result["batch_id"])
        assert batch.enqueue_finished_at is not None

    def test_batch_notes_include_snapshot_info(self):
        """Batch notes_json includes snapshot count info."""
        self._create_snapshot_with_patient("11111")

        result = process_census_snapshot()
        batch = CensusExecutionBatch.objects.get(pk=result["batch_id"])

        assert "patients_total" in batch.notes_json
        assert "runs_enqueued" in batch.notes_json
        assert batch.notes_json["patients_total"] == 1

    def test_no_batch_when_no_snapshots(self):
        """When no snapshots exist, no batch is created and batch_id is None."""
        result = process_census_snapshot()

        assert CensusExecutionBatch.objects.count() == 0
        assert result["batch_id"] is None

    def test_batch_not_created_when_no_occupied_beds(self):
        """When no occupied beds with prontuario exist, no batch is created."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        result = process_census_snapshot()

        assert CensusExecutionBatch.objects.count() == 0
        assert result["batch_id"] is None
        assert result["patients_total"] == 0


@pytest.mark.django_db
class TestQueueFunctionsAcceptBatch:
    """Unit tests for queue functions accepting optional batch parameter."""

    def _make_batch(self) -> CensusExecutionBatch:
        return CensusExecutionBatch.objects.create(status="running")

    def test_queue_admissions_only_accepts_batch(self):
        """queue_admissions_only_run accepts and sets batch on created run."""
        from apps.ingestion.services import queue_admissions_only_run

        batch = self._make_batch()
        run = queue_admissions_only_run(patient_record="11111", batch=batch)

        assert run.batch_id == batch.pk
        assert run.intent == "admissions_only"
        assert run.status == "queued"

    def test_queue_demographics_only_accepts_batch(self):
        """queue_demographics_only_run accepts and sets batch on created run."""
        from apps.ingestion.services import queue_demographics_only_run

        batch = self._make_batch()
        run = queue_demographics_only_run(patient_record="22222", batch=batch)

        assert run.batch_id == batch.pk
        assert run.intent == "demographics_only"
        assert run.status == "queued"

    def test_queue_ingestion_run_accepts_batch(self):
        """queue_ingestion_run accepts and sets batch on created run."""
        from apps.ingestion.services import queue_ingestion_run

        batch = self._make_batch()
        run = queue_ingestion_run(
            patient_record="33333",
            start_date="2026-01-01",
            end_date="2026-01-31",
            intent="full_sync",
            batch=batch,
        )

        assert run.batch_id == batch.pk
        assert run.intent == "full_sync"
        assert run.status == "queued"

    def test_queue_functions_still_work_without_batch(self):
        """Queue functions work without batch parameter (backward compat)."""
        from apps.ingestion.services import queue_admissions_only_run

        run = queue_admissions_only_run(patient_record="99999")

        assert run.status == "queued"
        assert run.batch_id is None
        assert run.intent == "admissions_only"

    def test_patients_created_by_census_have_correct_batch(self):
        """Patients created during census processing get runs with batch."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI",
            leito="01",
            prontuario="55555",
            nome="PACIENTE TESTE",
            especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        result = process_census_snapshot()
        batch_id = result["batch_id"]

        patient = Patient.objects.get(patient_source_key="55555")
        assert patient.name == "PACIENTE TESTE"

        # Both runs for this patient should be in the batch
        runs = IngestionRun.objects.filter(
            batch_id=batch_id,
            parameters_json__patient_record="55555",
        )
        assert runs.count() == 2
        intents = set(runs.values_list("intent", flat=True))
        assert intents == {"admissions_only", "demographics_only"}
