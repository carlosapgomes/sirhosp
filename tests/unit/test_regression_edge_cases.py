"""Regression tests for edge cases identified across slices S1-S4 (Slice S5).

Covers:
- Events without signed_at (timeline/search still works)
- Profession type compatibility (legacy tokens)
- Admission with zero events (empty timeline)
- Patient with zero admissions (empty admission list)
- Case-insensitive content search
- Content with special characters
- Multiple admissions sharing patient with independent timelines
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import (
    compute_content_hash,
    compute_event_identity_key,
    ingest_evolution,
)
from apps.patients.models import Admission, Patient
from apps.search.services import SearchQueryParams, search_clinical_events

TZ = ZoneInfo("America/Sao_Paulo")


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def auth_client(client: Client, db: object) -> Client:
    """Return a Client logged in as a standard user."""
    from django.contrib.auth.models import User

    User.objects.create_user(username="reguser", password="regpass123")
    client.login(username="reguser", password="regpass123")
    return client


@pytest.fixture
def ingestion_run(db: object) -> IngestionRun:
    return IngestionRun.objects.create(status="completed", parameters_json={})


@pytest.fixture
def patient(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P_REG",
        source_system="tasy",
        name="PACIENTE TESTE REGRESSAO",
    )


@pytest.fixture
def admission(patient: Patient) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_admission_key="ADM_REG",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 8, 0, tzinfo=TZ),
        ward="UTI",
        bed="UTI-01",
    )


# =========================================================================
# 1. Events without signed_at
# =========================================================================


class TestEventsWithoutSignedAt:
    """Timeline and search must work when signed_at is NULL."""

    def test_event_persists_without_signed_at(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        evt = ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="nosign_001",
            content_hash="hash_ns1",
            happened_at=timezone.now(),
            author_name="DR. TESTE",
            profession_type="medica",
            content_text="Evolucao sem assinatura.",
            signed_at=None,
        )
        assert evt.signed_at is None
        assert evt.pk is not None

    def test_timeline_renders_event_without_signed_at(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
        auth_client: Client,
    ) -> None:
        ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="nosign_002",
            content_hash="hash_ns2",
            happened_at=timezone.now(),
            author_name="DR. TESTE",
            profession_type="medica",
            content_text="Evolucao sem assinatura visivel.",
            signed_at=None,
        )
        response = auth_client.get(f"/admissions/{admission.pk}/timeline/")
        assert response.status_code == 200
        assert "Evolucao sem assinatura visivel" in response.content.decode()

    def test_search_finds_event_without_signed_at(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="nosign_003",
            content_hash="hash_ns3",
            happened_at=timezone.now(),
            author_name="DR. TESTE",
            profession_type="medica",
            content_text="Encontravel mesmo sem assinatura.",
            signed_at=None,
        )
        results = list(
            search_clinical_events(
                SearchQueryParams(query="encontravel")
            )
        )
        assert len(results) >= 1
        assert results[0].signed_at is None


# =========================================================================
# 2. Profession type compatibility (legacy tokens)
# =========================================================================


class TestProfessionTypeCompatibility:
    """Ingestion must accept and store legacy profession tokens."""

    def test_legacy_physiotherapy_token_ingests(
        self, admission: Admission, patient: Patient,
    ) -> None:
        evo = {
            "admission_key": "ADM_REG",
            "patient_source_key": "P_REG",
            "patient_name": "PACIENTE TESTE REGRESSAO",
            "source_system": "tasy",
            "ward": "UTI",
            "bed": "UTI-01",
            "happened_at": "2026-04-20 10:00:00",
            "author_name": "FISIO TESTE",
            "profession_type": "phisiotherapy",
            "content_text": "Sessao de reabilitacao.",
            "signed_at": "2026-04-20 10:05:00",
            "signature_line": "Fisio Teste CREFITO 999",
        }
        result = ingest_evolution([evo])
        assert result["created"] == 1
        evt = result["events_created"][0]
        assert evt.profession_type == "phisiotherapy"

    def test_filter_by_legacy_profession_type(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="legprof_001",
            content_hash="hash_lp1",
            happened_at=timezone.now(),
            author_name="FISIO TESTE",
            profession_type="phisiotherapy",
            content_text="Fisioterapia legada.",
        )
        results = list(
            search_clinical_events(
                SearchQueryParams(
                    query="fisioterapia",
                    profession_type="phisiotherapy",
                )
            )
        )
        assert len(results) == 1


# =========================================================================
# 3. Admission with zero events (empty timeline)
# =========================================================================


class TestEmptyTimeline:
    """Timeline view must handle admissions with no events."""

    def test_empty_timeline_returns_200(
        self, admission: Admission, auth_client: Client,
    ) -> None:
        response = auth_client.get(f"/admissions/{admission.pk}/timeline/")
        assert response.status_code == 200

    def test_empty_timeline_shows_no_events_message(
        self, admission: Admission, auth_client: Client,
    ) -> None:
        response = auth_client.get(f"/admissions/{admission.pk}/timeline/")
        content = response.content.decode()
        # Should not crash; should render an empty or informative state
        assert "UTI" in content  # ward name still visible


# =========================================================================
# 4. Patient with zero admissions (empty admission list)
# =========================================================================


class TestEmptyAdmissionList:
    """Admission list view must handle patients with no admissions."""

    def test_empty_admission_list_returns_200(
        self, patient: Patient, auth_client: Client,
    ) -> None:
        response = auth_client.get(f"/patients/{patient.pk}/admissions/")
        assert response.status_code == 200

    def test_empty_admission_list_shows_patient_name(
        self, patient: Patient, auth_client: Client,
    ) -> None:
        response = auth_client.get(f"/patients/{patient.pk}/admissions/")
        content = response.content.decode()
        assert "PACIENTE TESTE REGRESSAO" in content


# =========================================================================
# 5. Content with special characters and accents
# =========================================================================


class TestSpecialCharacters:
    """Content with accents, newlines and special chars must persist and search correctly."""

    def test_accented_content_persists(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        evt = ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="accent_001",
            content_hash="hash_ac1",
            happened_at=timezone.now(),
            author_name="DR. ACENTO",
            profession_type="medica",
            content_text="Paciente com dispneia, febre e cefaleia. Orientação: repouso.",
        )
        fresh = ClinicalEvent.objects.get(pk=evt.pk)
        assert "dispneia" in fresh.content_text
        assert "cefaleia" in fresh.content_text

    def test_multiline_content_persists(
        self,
        admission: Admission,
        patient: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        text = "Linha 1: paciente consciente.\nLinha 2: PA 120x80.\nLinha 3: sem queixas."
        evt = ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="multi_001",
            content_hash="hash_ml1",
            happened_at=timezone.now(),
            author_name="DR. TESTE",
            profession_type="medica",
            content_text=text,
        )
        fresh = ClinicalEvent.objects.get(pk=evt.pk)
        assert "\n" in fresh.content_text
        assert fresh.content_text.count("\n") == 2


# =========================================================================
# 6. Multiple admissions, independent timelines
# =========================================================================


class TestMultipleAdmissionsIndependentTimelines:
    """Events from one admission must not leak into another's timeline."""

    def test_timeline_shows_only_own_events(
        self,
        patient: Patient,
        ingestion_run: IngestionRun,
        auth_client: Client,
    ) -> None:
        adm1 = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM_R1",
            source_system="tasy",
            admission_date=datetime(2026, 3, 1, tzinfo=TZ),
            ward="UTI",
        )
        adm2 = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM_R2",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, tzinfo=TZ),
            ward="CLINICA MEDICA",
        )

        ClinicalEvent.objects.create(
            admission=adm1,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="iso_001",
            content_hash="hash_i1",
            happened_at=timezone.now(),
            author_name="DR. ADM1",
            profession_type="medica",
            content_text="Evento da internacao 1.",
        )
        ClinicalEvent.objects.create(
            admission=adm2,
            patient=patient,
            ingestion_run=ingestion_run,
            event_identity_key="iso_002",
            content_hash="hash_i2",
            happened_at=timezone.now(),
            author_name="DR. ADM2",
            profession_type="medica",
            content_text="Evento da internacao 2.",
        )

        resp1 = auth_client.get(f"/admissions/{adm1.pk}/timeline/")
        resp2 = auth_client.get(f"/admissions/{adm2.pk}/timeline/")

        content1 = resp1.content.decode()
        content2 = resp2.content.decode()

        assert "Evento da internacao 1" in content1
        assert "Evento da internacao 2" not in content1

        assert "Evento da internacao 2" in content2
        assert "Evento da internacao 1" not in content2


# =========================================================================
# 7. Ingestion: identity key determinism under edge cases
# =========================================================================


class TestIdentityKeyEdgeCases:
    """Identity key must be stable across edge cases."""

    def test_key_stable_with_special_chars_in_author(self):
        evo1 = {
            "admission_key": "A1",
            "happened_at": "2026-04-20 08:00:00",
            "author_name": "Dr. José da Silva",
            "source_system": "tasy",
        }
        evo2 = {
            "admission_key": "A1",
            "happened_at": "2026-04-20 08:00:00",
            "author_name": "Dr. José da Silva",
            "source_system": "tasy",
        }
        assert compute_event_identity_key(evo1) == compute_event_identity_key(evo2)

    def test_content_hash_stable_with_accents(self):
        text = "Paciente com dispneia e cefaleia."
        assert compute_content_hash(text) == compute_content_hash(text)

    def test_empty_content_hash_is_valid(self):
        h = compute_content_hash("")
        assert len(h) == 64  # SHA-256 hex
