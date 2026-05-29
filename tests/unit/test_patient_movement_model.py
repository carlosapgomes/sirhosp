"""Tests for PatientMovement model (Slice PMT-S1)."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.census.models import PatientMovement
from apps.patients.models import Patient


@pytest.mark.django_db
class TestPatientMovementModel:
    """PatientMovement model constraints and behavior."""

    def test_create_movement_minimal(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST PATIENT",
        )
        now = timezone.now()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=timezone.now().date(),
            sector="PS",
            first_seen_at=now,
            last_seen_at=now,
        )
        assert movement.pk is not None
        assert movement.discharge_type == ""

    def test_create_movement_all_fields(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="54321",
            name="FULL PATIENT",
        )
        now = timezone.now()
        movement_date = timezone.now().date()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="UTI",
            bed="UTI-01",
            origin="PS",
            discharge_type="A",
            sequence=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        assert movement.pk is not None
        assert movement.bed == "UTI-01"
        assert movement.origin == "PS"
        assert movement.discharge_type == "A"
        assert movement.sequence == 1

    def test_unique_constraint(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="11111",
            name="UNIQUE TEST",
        )
        now = timezone.now()
        movement_date = timezone.now().date()
        PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="PS",
            first_seen_at=now,
            last_seen_at=now,
        )
        with pytest.raises(IntegrityError):
            PatientMovement.objects.create(
                patient=patient,
                movement_date=movement_date,
                sector="PS",
                first_seen_at=now,
                last_seen_at=now,
            )

    def test_unique_allows_different_sector_same_day(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="22222",
            name="MULTI SECTOR",
        )
        now = timezone.now()
        movement_date = timezone.now().date()
        m1 = PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="PS",
            first_seen_at=now,
            last_seen_at=now,
        )
        m2 = PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="UTI",
            first_seen_at=now,
            last_seen_at=now,
        )
        assert m1.pk is not None
        assert m2.pk is not None

    def test_unique_allows_different_date_same_sector(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="33333",
            name="MULTI DATE",
        )
        now = timezone.now()
        m1 = PatientMovement.objects.create(
            patient=patient,
            movement_date=timezone.now().date(),
            sector="ENF",
            first_seen_at=now,
            last_seen_at=now,
        )
        m2 = PatientMovement.objects.create(
            patient=patient,
            movement_date=timezone.now().date() - timezone.timedelta(days=1),
            sector="ENF",
            first_seen_at=now,
            last_seen_at=now,
        )
        assert m1.pk is not None
        assert m2.pk is not None

    def test_ordering_by_patient_and_sequence(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="44444",
            name="ORDER TEST",
        )
        now = timezone.now()
        dates = [
            timezone.now().date() - timezone.timedelta(days=i)
            for i in range(3)
        ]
        m2 = PatientMovement.objects.create(
            patient=patient,
            movement_date=dates[0],
            sector="UTI",
            sequence=2,
            first_seen_at=now,
            last_seen_at=now,
        )
        m0 = PatientMovement.objects.create(
            patient=patient,
            movement_date=dates[1],
            sector="PS",
            sequence=0,
            first_seen_at=now,
            last_seen_at=now,
        )
        m1 = PatientMovement.objects.create(
            patient=patient,
            movement_date=dates[2],
            sector="ENF",
            sequence=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        movements = list(PatientMovement.objects.all())
        assert movements[0].pk == m0.pk
        assert movements[1].pk == m1.pk
        assert movements[2].pk == m2.pk

    def test_admission_nullable(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="55555",
            name="NULL ADMISSION",
        )
        now = timezone.now()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=timezone.now().date(),
            sector="ENF",
            first_seen_at=now,
            last_seen_at=now,
        )
        assert movement.admission is None

    def test_first_seen_at_and_last_seen_at(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="66666",
            name="TIME TEST",
        )
        now = timezone.now()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=timezone.now().date(),
            sector="ENF",
            first_seen_at=now,
            last_seen_at=now,
        )
        assert movement.first_seen_at == now
        assert movement.last_seen_at == now

    def test_str_representation(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="77777",
            name="STR TEST",
        )
        now = timezone.now()
        movement_date = timezone.now().date()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="PS",
            first_seen_at=now,
            last_seen_at=now,
        )
        expected = f"[{movement_date}] STR TEST @ PS"
        assert str(movement) == expected

    def test_str_with_discharge_type(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="88888",
            name="DISCHARGE STR",
        )
        now = timezone.now()
        movement_date = timezone.now().date()
        movement = PatientMovement.objects.create(
            patient=patient,
            movement_date=movement_date,
            sector="UTI",
            discharge_type="A",
            first_seen_at=now,
            last_seen_at=now,
        )
        expected = f"[{movement_date}] DISCHARGE STR @ UTI → A"
        assert str(movement) == expected
