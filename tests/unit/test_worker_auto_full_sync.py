from __future__ import annotations

import pytest
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestWorkerAutoFullSync:
    """Test the _enqueue_most_recent_full_sync static method."""

    def _get_method(self):
        from apps.ingestion.management.commands.process_ingestion_runs import Command
        return Command._enqueue_most_recent_full_sync

    def test_enqueues_full_sync_for_single_admission(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-KEY-1",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is not None
        assert result.intent == "full_sync"
        assert result.status == "queued"
        assert result.parameters_json["patient_record"] == "12345"
        assert result.parameters_json["admission_id"] == str(admission.pk)
        assert result.parameters_json["intent"] == "full_sync"

    def test_picks_most_recent_admission(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        _old = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-OLD",
            admission_date=timezone.now() - timezone.timedelta(days=30),
            discharge_date=timezone.now() - timezone.timedelta(days=20),
        )
        recent = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-RECENT",
            admission_date=timezone.now() - timezone.timedelta(days=3),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is not None
        # Should target the most recent admission
        assert result.parameters_json["admission_id"] == str(recent.pk)
        assert result.parameters_json["admission_source_key"] == "ADM-RECENT"

    def test_no_admissions_returns_none(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        assert result is None

    def test_full_sync_has_correct_end_date(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        adm = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-1",
            admission_date=timezone.now() - timezone.timedelta(days=10),
            discharge_date=timezone.now() - timezone.timedelta(days=2),
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        # End date should be the discharge date
        expected_end = adm.discharge_date.strftime("%Y-%m-%d")
        assert result.parameters_json["end_date"] == expected_end

    def test_full_sync_end_date_is_today_when_still_admitted(self):
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="12345",
            name="TEST",
        )
        _admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-1",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="admissions_only"
        )

        enqueue = self._get_method()
        result = enqueue(patient, run)

        # End date should be today (still admitted)
        today = timezone.now().strftime("%Y-%m-%d")
        assert result.parameters_json["end_date"] == today
