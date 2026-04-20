"""Tests for ClinicalEvent and IngestionRun models (Slice S1)."""

import pytest
from django.db import IntegrityError

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestIngestionRun:
    """IngestionRun lifecycle."""

    def test_create_ingestion_run(self):
        run = IngestionRun.objects.create(status="running")
        assert run.pk is not None
        assert run.status == "running"
        assert run.started_at is not None

    def test_ingestion_run_defaults(self):
        run = IngestionRun.objects.create(status="running")
        assert run.events_processed == 0
        assert run.events_created == 0
        assert run.events_skipped == 0
        assert run.events_revised == 0


@pytest.mark.django_db
class TestClinicalEvent:
    """ClinicalEvent model constraints and behavior."""

    def _create_admission(self):
        patient = Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="MARIA DA SILVA",
        )
        return Admission.objects.create(
            patient=patient,
            source_admission_key="ADM001",
            source_system="tasy",
        )

    def test_create_clinical_event(self):
        adm = self._create_admission()
        from django.utils import timezone

        evt = ClinicalEvent.objects.create(
            admission=adm,
            patient=adm.patient,
            event_identity_key="EVT001",
            content_hash="abc123",
            happened_at=timezone.now(),
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Paciente estável.",
            raw_payload_json={"source": "test"},
        )
        assert evt.pk is not None
        assert evt.content_text == "Paciente estável."

    def test_unique_event_identity_content_hash(self):
        adm = self._create_admission()
        from django.utils import timezone

        now = timezone.now()
        ClinicalEvent.objects.create(
            admission=adm,
            patient=adm.patient,
            event_identity_key="EVT001",
            content_hash="abc123",
            happened_at=now,
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Paciente estável.",
            raw_payload_json={},
        )
        with pytest.raises(IntegrityError):
            ClinicalEvent.objects.create(
                admission=adm,
                patient=adm.patient,
                event_identity_key="EVT001",
                content_hash="abc123",
                happened_at=now,
                author_name="DR. CARLOS",
                profession_type="medica",
                content_text="Paciente estável.",
                raw_payload_json={},
            )

    def test_same_identity_different_content_is_revision(self):
        """Same event_identity_key with different content_hash = allowed (revision)."""
        adm = self._create_admission()
        from django.utils import timezone

        now = timezone.now()
        evt1 = ClinicalEvent.objects.create(
            admission=adm,
            patient=adm.patient,
            event_identity_key="EVT001",
            content_hash="abc123",
            happened_at=now,
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Versão 1.",
            raw_payload_json={},
        )
        evt2 = ClinicalEvent.objects.create(
            admission=adm,
            patient=adm.patient,
            event_identity_key="EVT001",
            content_hash="def456",
            happened_at=now,
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Versão 2 revisada.",
            raw_payload_json={},
        )
        assert evt1.pk != evt2.pk

    def test_event_linked_to_ingestion_run(self):
        adm = self._create_admission()
        run = IngestionRun.objects.create(status="running")
        from django.utils import timezone

        evt = ClinicalEvent.objects.create(
            admission=adm,
            patient=adm.patient,
            event_identity_key="EVT001",
            content_hash="abc123",
            happened_at=timezone.now(),
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Paciente estável.",
            raw_payload_json={},
            ingestion_run=run,
        )
        assert evt.ingestion_run == run
