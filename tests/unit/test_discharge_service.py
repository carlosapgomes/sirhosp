from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.discharges.services import process_discharges
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestProcessDischarges:
    """Tests for DischargeService.process_discharges()."""

    def test_empty_list_returns_zeros(self):
        """Empty input returns all zeros."""
        result = process_discharges([])
        assert result == {
            "total_pdf": 0,
            "patient_not_found": 0,
            "admission_not_found": 0,
            "already_discharged": 0,
            "discharge_set": 0,
        }

    def test_patient_not_found_is_skipped(self):
        """Patient not in DB is skipped, not created."""
        patients = [
            {
                "prontuario": "99999",
                "nome": "PACIENTE INEXISTENTE",
                "leito": "X01",
                "especialidade": "NEF",
                "data_internacao": "15/04/2026",
            }
        ]
        result = process_discharges(patients)
        assert result["total_pdf"] == 1
        assert result["patient_not_found"] == 1
        assert result["discharge_set"] == 0
        # Confirm patient was NOT created
        assert not Patient.objects.filter(patient_source_key="99999").exists()

    def test_discharge_set_with_data_internacao_match(self):
        """Matching by data_internacao sets discharge_date."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO DE TAL",
        )
        data_int = date.today() - timedelta(days=10)
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=datetime.combine(data_int, datetime.min.time()),
            discharge_date=None,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO DE TAL",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": data_int.strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1
        assert result["patient_not_found"] == 0
        assert result["admission_not_found"] == 0

        admission.refresh_from_db()
        assert admission.discharge_date is not None
        # discharge_date should be approximately now
        assert (timezone.now() - admission.discharge_date).total_seconds() < 10

    def test_fallback_to_most_recent_admission(self):
        """When data_internacao doesn't match, use most recent without discharge."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        now = timezone.now()
        # Older admission
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-OLD",
            source_system="tasy",
            admission_date=now - timedelta(days=30),
            discharge_date=None,
        )
        # Most recent admission
        recent = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-RECENT",
            source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=None,
        )

        # data_internacao that doesn't match any admission
        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=3)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1

        recent.refresh_from_db()
        assert recent.discharge_date is not None

    def test_already_discharged_is_skipped(self):
        """Admission with discharge_date already set is skipped."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        already_discharged_date = timezone.now() - timedelta(hours=2)
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=10),
            discharge_date=already_discharged_date,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=10)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["already_discharged"] == 1
        assert result["discharge_set"] == 0

    def test_admission_not_found_when_all_discharged(self):
        """When all admissions have discharge_date, count as not_found."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=10),
            discharge_date=timezone.now() - timedelta(days=1),
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=10)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["admission_not_found"] == 1
        assert result["discharge_set"] == 0

    def test_invalid_date_format_falls_back(self):
        """Invalid data_internacao format should not crash, uses fallback."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5),
            discharge_date=None,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": "DATA-INVALIDA",
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1  # fallback succeeded

        admission.refresh_from_db()
        assert admission.discharge_date is not None

    def test_multiple_patients_mixed_results(self):
        """Mixed results: some found, some not, some already discharged."""
        # Patient 1: normal discharge
        p1 = Patient.objects.create(
            patient_source_key="111", source_system="tasy", name="P1")
        Admission.objects.create(
            patient=p1, source_admission_key="A1", source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5), discharge_date=None)

        # Patient 2: already discharged
        p2 = Patient.objects.create(
            patient_source_key="222", source_system="tasy", name="P2")
        Admission.objects.create(
            patient=p2, source_admission_key="A2", source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5),
            discharge_date=timezone.now() - timedelta(hours=3))

        # Patient 3: not in DB (no Patient created)
        # Patient 4: no prontuario (empty)

        patients = [
            {"prontuario": "111", "nome": "P1", "leito": "B1",
             "especialidade": "NEF",
             "data_internacao": (date.today() - timedelta(days=5)).strftime("%d/%m/%Y")},
            {"prontuario": "222", "nome": "P2", "leito": "B2",
             "especialidade": "CIV",
             "data_internacao": (date.today() - timedelta(days=5)).strftime("%d/%m/%Y")},
            {"prontuario": "333", "nome": "P3", "leito": "B3",
             "especialidade": "PED",
             "data_internacao": "15/04/2026"},
            {"prontuario": "", "nome": "", "leito": "",
             "especialidade": "", "data_internacao": ""},
        ]

        result = process_discharges(patients)
        assert result["total_pdf"] == 4
        assert result["discharge_set"] == 1      # P1
        assert result["already_discharged"] == 1  # P2
        assert result["patient_not_found"] == 1   # P3
        # P4: prontuario vazio é ignorado, não conta como patient_not_found
