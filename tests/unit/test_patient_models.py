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

    def test_patient_with_all_demographics(self):
        from datetime import date

        p = Patient.objects.create(
            patient_source_key="P002",
            source_system="tasy",
            name="JOAO SANTOS",
            social_name="JOANA SANTOS",
            date_of_birth=date(1985, 3, 15),
            gender="Masculino",
            gender_identity="Homem cisgênero",
            mother_name="ANA SANTOS",
            father_name="JOSE SANTOS",
            race_color="Preta",
            birthplace="SALVADOR - BA",
            nationality="BRASILEIRO",
            marital_status="Solteiro",
            education_level="Ensino Médio",
            profession="TECNICO DE ENFERMAGEM",
            cns="123456789012345",
            cpf="12345678901",
            phone_home="71983667587",
            phone_cellular="71986527418",
            phone_contact="",
            street="RUA SAO JOAO",
            address_number="27",
            address_complement="",
            neighborhood="LIBERDADE",
            city="SALVADOR",
            state="BA",
            postal_code="41611180",
        )
        assert p.date_of_birth == date(1985, 3, 15)
        assert p.gender == "Masculino"
        assert p.gender_identity == "Homem cisgênero"
        assert p.cns == "123456789012345"
        assert p.social_name == "JOANA SANTOS"
        assert p.father_name == "JOSE SANTOS"
        assert p.race_color == "Preta"
        assert p.birthplace == "SALVADOR - BA"
        assert p.phone_cellular == "71986527418"
        assert p.neighborhood == "LIBERDADE"
        assert p.city == "SALVADOR"
        assert p.state == "BA"
        assert p.postal_code == "41611180"

    def test_patient_new_fields_default_to_empty(self):
        """New demographic fields default to empty string when not provided."""
        p = Patient.objects.create(
            patient_source_key="P003",
            source_system="tasy",
            name="PACIENTE MINIMO",
        )
        assert p.social_name == ""
        assert p.gender_identity == ""
        assert p.father_name == ""
        assert p.race_color == ""
        assert p.birthplace == ""
        assert p.nationality == ""
        assert p.marital_status == ""
        assert p.education_level == ""
        assert p.profession == ""
        assert p.phone_home == ""
        assert p.phone_cellular == ""
        assert p.phone_contact == ""
        assert p.street == ""
        assert p.address_number == ""
        assert p.address_complement == ""
        assert p.neighborhood == ""
        assert p.city == ""
        assert p.state == ""
        assert p.postal_code == ""

    def test_patient_ordering_by_name(self):
        Patient.objects.create(patient_source_key="P010", source_system="tasy", name="ZECA")
        Patient.objects.create(patient_source_key="P011", source_system="tasy", name="ANA")
        Patient.objects.create(patient_source_key="P012", source_system="tasy", name="MARIA")
        names = list(Patient.objects.values_list("name", flat=True))
        assert names == ["ANA", "MARIA", "ZECA"]


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

    def test_identifier_history_for_new_demographic_fields(self):
        """Identifier history can track changes to new fields like cns and cpf."""
        patient = Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA",
        )
        hist_cns = PatientIdentifierHistory.objects.create(
            patient=patient,
            identifier_type="cns",
            old_value="",
            new_value="898001234567890",
        )
        hist_cpf = PatientIdentifierHistory.objects.create(
            patient=patient,
            identifier_type="cpf",
            old_value="",
            new_value="52998245009",
        )
        assert hist_cns.new_value == "898001234567890"
        assert hist_cpf.new_value == "52998245009"
