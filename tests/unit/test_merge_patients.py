"""Tests for merge_patients service function (Slice S6)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    Admission,
    Patient,
    PatientIdentifierHistory,
)
from apps.patients.services import merge_patients


@pytest.mark.django_db
class TestMergePatients:
    def test_moves_admissions(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )
        Admission.objects.create(
            patient=merge, source_admission_key="ADM-1",
        )
        Admission.objects.create(
            patient=merge, source_admission_key="ADM-2",
        )

        result = merge_patients(keep=keep, merge=merge)

        assert result["admissions_moved"] == 2
        assert Admission.objects.filter(patient=keep).count() == 2
        assert not Patient.objects.filter(pk=merge.pk).exists()

    def test_moves_clinical_events(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )
        adm = Admission.objects.create(
            patient=merge, source_admission_key="ADM-1",
        )
        ClinicalEvent.objects.create(
            admission=adm, patient=merge,
            event_identity_key="evt-1", content_hash="hash1",
            happened_at=timezone.now(), author_name="DR", profession_type="medica",
            content_text="test",
        )

        result = merge_patients(keep=keep, merge=merge)

        assert result["events_moved"] == 1
        assert ClinicalEvent.objects.filter(patient=keep).count() == 1
        assert not Patient.objects.filter(pk=merge.pk).exists()

    def test_creates_history_record(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )

        merge_patients(keep=keep, merge=merge)

        history = PatientIdentifierHistory.objects.filter(
            patient=keep, identifier_type="patient_merge"
        )
        assert history.count() == 1
        assert history.first().old_value == "222"
        assert history.first().new_value == "111"

    def test_merge_into_self_raises(self):
        patient = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="SELF"
        )
        with pytest.raises(ValueError, match="itself"):
            merge_patients(keep=patient, merge=patient)

    def test_with_ingestion_run(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )
        run = IngestionRun.objects.create(
            status="completed",
        )

        merge_patients(keep=keep, merge=merge, run=run)

        history = PatientIdentifierHistory.objects.filter(
            patient=keep, identifier_type="patient_merge"
        )
        assert history.count() == 1
        assert history.first().ingestion_run == run
