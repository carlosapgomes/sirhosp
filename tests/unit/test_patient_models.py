"""Tests for Patient and Admission models (Slice S1)."""

import pytest
from django.db import IntegrityError

from apps.patients.models import Admission, Patient, PatientIdentifierHistory


@pytest.mark.django_db
class TestPatient:
    """Patient model constraints and behavior."""

    def test_create_patient_with_source_key(self):
        p = Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA DA SILVA",
        )
        assert p.pk is not None
        assert str(p) == "MARIA DA SILVA"

    def test_unique_patient_per_source_system(self):
        Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA DA SILVA",
        )
        with pytest.raises(IntegrityError):
            Patient.objects.create(
                patient_source_key="P001",
                source_system="tasy",
                name="OUTRO NOME",
            )

    def test_same_key_different_source_system_allowed(self):
        p1 = Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA",
        )
        p2 = Patient.objects.create(
            patient_source_key="P001",
            source_system="legacy",
            name="MARIA",
        )
        assert p1.pk != p2.pk

    def test_patient_with_demographics(self):
        from datetime import date

        p = Patient.objects.create(
            patient_source_key="P002",
            source_system="tasy",
            name="JOAO SANTOS",
            date_of_birth=date(1985, 3, 15),
            gender="M",
            mother_name="ANA SANTOS",
            cns="123456789012345",
            cpf="12345678901",
        )
        assert p.date_of_birth == date(1985, 3, 15)
        assert p.gender == "M"
        assert p.cns == "123456789012345"


@pytest.mark.django_db
class TestAdmission:
    """Admission model constraints and behavior."""

    def _create_patient(self):
        return Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA DA SILVA",
        )

    def test_create_admission(self):
        patient = self._create_patient()
        adm = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM001",
            source_system="tasy",
        )
        assert adm.pk is not None
        assert adm.patient == patient

    def test_unique_admission_per_source_system(self):
        patient = self._create_patient()
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM001",
            source_system="tasy",
        )
        with pytest.raises(IntegrityError):
            Admission.objects.create(
                patient=patient,
                source_admission_key="ADM001",
                source_system="tasy",
            )

    def test_same_admission_key_different_source(self):
        patient = self._create_patient()
        adm1 = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM001",
            source_system="tasy",
        )
        adm2 = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM001",
            source_system="legacy",
        )
        assert adm1.pk != adm2.pk


@pytest.mark.django_db
class TestPatientIdentifierHistory:
    """PatientIdentifierHistory tracking."""

    def test_create_identifier_history(self):
        patient = Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA",
        )
        hist = PatientIdentifierHistory.objects.create(
            patient=patient,
            identifier_type="patient_source_key",
            old_value="OLD_P001",
            new_value="NEW_P001",
        )
        assert hist.pk is not None
        assert hist.patient == patient
