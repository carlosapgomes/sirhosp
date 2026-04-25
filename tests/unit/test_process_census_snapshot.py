from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.services import process_census_snapshot
from apps.ingestion.models import IngestionRun
from apps.patients.models import Patient


@pytest.mark.django_db
class TestProcessCensusSnapshot:
    def test_empty_snapshot_returns_zero(self):
        """When no CensusSnapshot exists, all counts are zero."""
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["patients_new"] == 0
        assert result["runs_enqueued"] == 0

    def test_only_empty_beds_no_patients(self):
        """Beds without prontuario are skipped."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["runs_enqueued"] == 0
        assert Patient.objects.count() == 0

    def test_new_patient_created_and_run_enqueued(self):
        """New prontuario → Patient created + admissions_only enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_new"] == 1
        assert result["patients_total"] == 1
        assert result["runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "JOSE AUGUSTO MERCES"

        # Verify IngestionRun was enqueued
        queued_run = IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).first()
        assert queued_run is not None
        assert queued_run.parameters_json["patient_record"] == "14160147"

    def test_existing_patient_not_duplicated(self):
        """Patient already exists → no duplicate, but run is still enqueued."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE AUGUSTO MERCES",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_new"] == 0
        assert result["patients_updated"] == 0
        assert result["runs_enqueued"] == 1
        assert Patient.objects.count() == 1

    def test_existing_patient_name_updated(self):
        """Patient exists with different name → name updated."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="NOME ANTIGO",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="NOME NOVO",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["patients_updated"] == 1
        assert result["runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "NOME NOVO"

    def test_duplicate_prontuario_in_same_run_deduplicated(self):
        """Same prontuario appears twice → only 1 run enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        snap_time = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES UPDATED",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        result = process_census_snapshot()
        assert result["runs_enqueued"] == 1
        assert result["patients_total"] == 1

        # Name should be from the LAST occurrence
        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        last_snap = CensusSnapshot.objects.order_by("-pk").first()
        assert patient.name == last_snap.nome

    def test_specific_run_id(self):
        """Can process a specific run by ID."""
        run1 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now() - timezone.timedelta(hours=2),
            ingestion_run=run1,
            setor="OLD",
            leito="01",
            prontuario="111",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        run2 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run2,
            setor="NEW",
            leito="01",
            prontuario="222",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        # Process only run1
        result = process_census_snapshot(run_id=run1.pk)
        assert result["patients_total"] == 1
        assert Patient.objects.filter(patient_source_key="111").exists()
        assert not Patient.objects.filter(patient_source_key="222").exists()

    def test_multiple_patients_in_snapshot(self):
        """Multiple occupied beds → multiple patients + runs."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        for i, (pront, nome) in enumerate(
            [("111", "A"), ("222", "B"), ("333", "C")]
        ):
            CensusSnapshot.objects.create(
                captured_at=now,
                ingestion_run=run,
                setor="UTI",
                leito=f"L{i}",
                prontuario=pront,
                nome=nome,
                especialidade="TST",
                bed_status=BedStatus.OCCUPIED,
            )
        result = process_census_snapshot()
        assert result["patients_total"] == 3
        assert result["patients_new"] == 3
        assert result["runs_enqueued"] == 3
        assert Patient.objects.count() == 3
        assert IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).count() == 3
