"""Tests for upsert_patient_movements service (Slice PMT-S2)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.census.services import upsert_patient_movements
from apps.patients.models import Admission, Patient


def _make_snapshot(
    captured_at=None,
    setor="PS",
    leito="LEITO-01",
    prontuario="123",
    nome="PACIENTE TESTE",
    bed_status=BedStatus.OCCUPIED,
    data_movimentacao="25/05/2026",
    tipo_alta="",
    origem="",
    especialidade="",
) -> CensusSnapshot:
    """Helper to create a CensusSnapshot for testing."""
    return CensusSnapshot.objects.create(
        captured_at=captured_at or timezone.now(),
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome=nome,
        especialidade=especialidade,
        bed_status=bed_status,
        data_movimentacao=data_movimentacao,
        tipo_alta=tipo_alta,
        origem=origem,
    )


@pytest.mark.django_db
class TestUpsertPatientMovements:
    """Tests for upsert_patient_movements()."""

    def test_creates_movement_for_occupied_patient(self):
        """Snapshot OCCUPIED with prontuario creates one PatientMovement."""
        _make_snapshot(prontuario="123", data_movimentacao="25/05/2026")
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )

        result = upsert_patient_movements()

        assert result["movements_created"] == 1
        assert result["patients_processed"] == 1
        movement = PatientMovement.objects.get()
        assert movement.sector == "PS"
        assert movement.bed == "LEITO-01"
        assert movement.movement_date == date(2026, 5, 25)

    def test_skips_empty_beds(self):
        """Snapshot EMPTY should produce no movements."""
        _make_snapshot(bed_status=BedStatus.EMPTY, prontuario="", nome="DESOCUPADO")

        result = upsert_patient_movements()

        assert result["movements_created"] == 0
        assert result["patients_processed"] == 0
        assert PatientMovement.objects.count() == 0

    def test_skips_occupied_without_prontuario(self):
        """Snapshot OCCUPIED but empty prontuario should produce no movement."""
        _make_snapshot(prontuario="", nome="PACIENTE SEM PRONT")

        result = upsert_patient_movements()

        assert result["movements_created"] == 0
        assert PatientMovement.objects.count() == 0

    def test_does_not_duplicate_same_state(self):
        """Calling upsert 2x with same snapshot only creates 1 movement."""
        _make_snapshot(prontuario="123", data_movimentacao="25/05/2026")
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )

        upsert_patient_movements()
        # Move time forward slightly
        first_last_seen = PatientMovement.objects.get().last_seen_at
        result = upsert_patient_movements()

        assert result["movements_created"] == 0
        assert result["movements_updated"] == 1
        assert PatientMovement.objects.count() == 1
        movement = PatientMovement.objects.get()
        assert movement.last_seen_at >= first_last_seen

    def test_creates_new_movement_for_different_sector(self):
        """Patient in sector A, then sector B → 2 movements."""
        t0 = timezone.now() - timedelta(hours=2)
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="PS",
            data_movimentacao="25/05/2026",
        )
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="UTI",
            data_movimentacao="25/05/2026",
        )
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )

        result = upsert_patient_movements()

        assert result["movements_created"] == 2
        assert result["patients_processed"] == 1
        assert PatientMovement.objects.count() == 2

    def test_creates_new_movement_for_different_date(self):
        """Same sector, different movement_date → 2 movements."""
        t0 = timezone.now() - timedelta(hours=2)
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="PS",
            data_movimentacao="20/05/2026",
        )
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="PS",
            data_movimentacao="25/05/2026",
        )
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )

        result = upsert_patient_movements()

        assert result["movements_created"] == 2
        assert PatientMovement.objects.count() == 2

    def test_recalculates_sequence_after_upsert(self):
        """After upsert of multiple movements, sequence is 0, 1, 2."""
        t0 = timezone.now() - timedelta(hours=2)
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        # Create movements in non-chronological order
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="UTI",
            data_movimentacao="25/05/2026",
        )
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="ENF",
            data_movimentacao="23/05/2026",
        )
        _make_snapshot(
            captured_at=t0,
            prontuario="123",
            setor="PS",
            data_movimentacao="20/05/2026",
        )

        upsert_patient_movements()

        movements = list(
            PatientMovement.objects.filter(patient=patient).order_by("sequence")
        )
        assert len(movements) == 3
        assert movements[0].sequence == 0
        assert movements[0].sector == "PS"
        assert movements[1].sequence == 1
        assert movements[1].sector == "ENF"
        assert movements[2].sequence == 2
        assert movements[2].sector == "UTI"

    def test_links_to_active_admission(self):
        """Movement is linked to the patient's active Admission."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            admission_date=timezone.now() - timedelta(days=5),
            discharge_date=None,
        )
        _make_snapshot(prontuario="123", data_movimentacao="25/05/2026")

        upsert_patient_movements()

        movement = PatientMovement.objects.get()
        assert movement.admission is not None
        assert movement.admission.source_admission_key == "ADM-001"

    def test_no_active_admission_leaves_null(self):
        """Patient without active Admission → movement.admission is None."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        _make_snapshot(prontuario="123", data_movimentacao="25/05/2026")

        upsert_patient_movements()

        movement = PatientMovement.objects.get()
        assert movement.admission is None

    def test_returns_correct_metrics(self):
        """Return dict has movements_created, movements_updated, patients_processed."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        _make_snapshot(prontuario="123", data_movimentacao="25/05/2026")

        result = upsert_patient_movements()

        assert "movements_created" in result
        assert "movements_updated" in result
        assert "patients_processed" in result
        assert "errors" in result
        assert result["movements_created"] == 1
        assert result["movements_updated"] == 0
        assert result["patients_processed"] == 1

    def test_skips_invalid_data_movimentacao(self):
        """Empty data_movimentacao should skip the patient."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        _make_snapshot(prontuario="123", data_movimentacao="")

        result = upsert_patient_movements()

        assert result["movements_created"] == 0
        assert PatientMovement.objects.count() == 0

    def test_discharge_type_populated_from_alta(self):
        """tipo_alta from snapshot goes to discharge_type."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        _make_snapshot(
            prontuario="123",
            data_movimentacao="25/05/2026",
            tipo_alta="A",
        )

        upsert_patient_movements()

        movement = PatientMovement.objects.get()
        assert movement.discharge_type == "A"

    def test_origin_populated(self):
        """origem from snapshot goes to movement origin."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="123",
            name="PACIENTE TESTE",
        )
        _make_snapshot(
            prontuario="123",
            data_movimentacao="25/05/2026",
            origem="PS",
        )

        upsert_patient_movements()

        movement = PatientMovement.objects.get()
        assert movement.origin == "PS"

    def test_no_snapshots_at_all(self):
        """No snapshots in DB → returns zeros, no crash."""
        result = upsert_patient_movements()

        assert result["movements_created"] == 0
        assert result["movements_updated"] == 0
        assert result["patients_processed"] == 0

    def test_patient_auto_created_if_missing(self):
        """If no Patient exists for prontuario, one should be created."""
        _make_snapshot(prontuario="999", nome="NEW PACIENTE", data_movimentacao="25/05/2026")

        result = upsert_patient_movements()

        assert result["movements_created"] == 1
        patient = Patient.objects.get(patient_source_key="999")
        assert patient.name == "NEW PACIENTE"
