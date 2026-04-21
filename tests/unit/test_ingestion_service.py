"""Tests for ingestion service: identity key, content hash, timezone, dedupe (Slice S2)."""

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.services import (
    compute_content_hash,
    compute_event_identity_key,
    ingest_evolution,
)
from apps.patients.models import Admission, Patient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TZ_INST = ZoneInfo("America/Sao_Paulo")


def _make_evolution(
    *,
    admission_key: str = "ADM001",
    patient_source_key: str = "P001",
    patient_name: str = "MARIA DA SILVA",
    happened_at: str = "2026-04-19 08:30:00",
    author_name: str = "DR. CARLOS",
    profession_type: str = "medica",
    content_text: str = "Paciente estável, sem intercorrências.",
    signed_at: str | None = "2026-04-19 08:35:00",
    signature_line: str = "Dr. Carlos CRM-SP 123456",
    source_system: str = "tasy",
    ward: str = "UTI",
    bed: str = "LEITO 01",
) -> dict:
    """Build a minimal evolution dict as if coming from the scraper."""
    return {
        "admission_key": admission_key,
        "patient_source_key": patient_source_key,
        "patient_name": patient_name,
        "source_system": source_system,
        "ward": ward,
        "bed": bed,
        "happened_at": happened_at,
        "signed_at": signed_at,
        "author_name": author_name,
        "profession_type": profession_type,
        "content_text": content_text,
        "signature_line": signature_line,
    }


# ---------------------------------------------------------------------------
# 2.1 - event_identity_key, content_hash, timezone normalization
# ---------------------------------------------------------------------------


class TestComputeEventIdentityKey:
    """Deterministic identity key for an event."""

    def test_deterministic(self):
        evo = _make_evolution()
        key1 = compute_event_identity_key(evo)
        key2 = compute_event_identity_key(evo)
        assert key1 == key2

    def test_changes_with_different_admission(self):
        evo1 = _make_evolution(admission_key="ADM001")
        evo2 = _make_evolution(admission_key="ADM002")
        assert compute_event_identity_key(evo1) != compute_event_identity_key(evo2)

    def test_changes_with_different_timestamp(self):
        evo1 = _make_evolution(happened_at="2026-04-19 08:30:00")
        evo2 = _make_evolution(happened_at="2026-04-19 09:00:00")
        assert compute_event_identity_key(evo1) != compute_event_identity_key(evo2)

    def test_changes_with_different_author(self):
        evo1 = _make_evolution(author_name="DR. CARLOS")
        evo2 = _make_evolution(author_name="DRA. ANA")
        assert compute_event_identity_key(evo1) != compute_event_identity_key(evo2)

    def test_stable_key_length(self):
        evo = _make_evolution()
        key = compute_event_identity_key(evo)
        assert len(key) <= 512


class TestComputeContentHash:
    """Content hash for revision detection."""

    def test_deterministic(self):
        text = "Paciente estável."
        assert compute_content_hash(text) == compute_content_hash(text)

    def test_changes_with_different_content(self):
        h1 = compute_content_hash("Versão 1")
        h2 = compute_content_hash("Versão 2")
        assert h1 != h2

    def test_uses_sha256(self):
        text = "Paciente estável."
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_content_hash(text) == expected


@pytest.mark.django_db
class TestTimezoneNormalization:
    """Naive datetimes from source must become timezone-aware (America/Sao_Paulo)."""

    def test_happened_at_becomes_aware(self):
        evo = _make_evolution(happened_at="2026-04-19 08:30:00")
        result = ingest_evolution([evo])
        event = result["events_created"][0]
        assert event.happened_at.tzinfo is not None
        assert event.happened_at == datetime(2026, 4, 19, 8, 30, 0, tzinfo=TZ_INST)

    def test_signed_at_becomes_aware(self):
        evo = _make_evolution(signed_at="2026-04-19 08:35:00")
        result = ingest_evolution([evo])
        event = result["events_created"][0]
        assert event.signed_at is not None
        assert event.signed_at.tzinfo is not None
        assert event.signed_at == datetime(2026, 4, 19, 8, 35, 0, tzinfo=TZ_INST)

    def test_none_signed_at_stays_none(self):
        evo = _make_evolution(signed_at=None)
        result = ingest_evolution([evo])
        event = result["events_created"][0]
        assert event.signed_at is None


# ---------------------------------------------------------------------------
# 2.2 - Upsert de paciente e internação
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpsertPatientAndAdmission:
    """Patient and admission upsert during ingestion."""

    def test_creates_patient_on_first_ingestion(self):
        evo = _make_evolution()
        ingest_evolution([evo])
        assert Patient.objects.filter(patient_source_key="P001", source_system="tasy").exists()

    def test_reuses_patient_on_subsequent_ingestion(self):
        evo = _make_evolution()
        ingest_evolution([evo])
        ingest_evolution([evo])
        assert Patient.objects.count() == 1

    def test_creates_admission_on_first_ingestion(self):
        evo = _make_evolution()
        ingest_evolution([evo])
        assert Admission.objects.filter(
            source_admission_key="ADM001", source_system="tasy"
        ).exists()

    def test_reuses_admission_on_subsequent_ingestion(self):
        evo = _make_evolution()
        ingest_evolution([evo])
        ingest_evolution([evo])
        assert Admission.objects.count() == 1

    def test_updates_patient_name_on_change(self):
        evo1 = _make_evolution(patient_name="MARIA DA SILVA")
        ingest_evolution([evo1])
        evo2 = _make_evolution(patient_name="MARIA DA SILVA SOUZA")
        ingest_evolution([evo2])
        p = Patient.objects.get(patient_source_key="P001")
        assert p.name == "MARIA DA SILVA SOUZA"


# ---------------------------------------------------------------------------
# 2.3 - Deduplicação por event_identity_key + content_hash
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeduplication:
    """Idempotent ingestion via event_identity_key + content_hash."""

    def test_duplicate_event_skipped(self):
        evo = _make_evolution()
        ingest_evolution([evo])
        result2 = ingest_evolution([evo])
        assert result2["skipped"] == 1
        assert ClinicalEvent.objects.count() == 1

    def test_revision_creates_new_event(self):
        evo_v1 = _make_evolution(content_text="Versão 1")
        ingest_evolution([evo_v1])
        evo_v2 = _make_evolution(content_text="Versão 2 revisada")
        result = ingest_evolution([evo_v2])
        assert result["revised"] == 1
        assert ClinicalEvent.objects.count() == 2

    def test_mixed_batch(self):
        evo = _make_evolution(content_text="Original")
        ingest_evolution([evo])
        evo_dup = _make_evolution(content_text="Original")
        evo_new = _make_evolution(
            happened_at="2026-04-19 10:00:00",
            author_name="DRA. ANA",
            content_text="Nova evolução",
        )
        result = ingest_evolution([evo_dup, evo_new])
        assert result["skipped"] == 1
        assert result["created"] == 1
        assert ClinicalEvent.objects.count() == 2


# ---------------------------------------------------------------------------
# 2.4 - IngestionRun tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestionRunTracking:
    """IngestionRun records execution metadata."""

    def test_run_created_on_ingestion(self):
        evo = _make_evolution()
        result = ingest_evolution([evo])
        run = result["run"]
        assert run is not None
        assert run.pk is not None

    def test_run_status_succeeded(self):
        evo = _make_evolution()
        result = ingest_evolution([evo])
        assert result["run"].status == "succeeded"

    def test_run_metrics(self):
        evo = _make_evolution(content_text="Texto A")
        result = ingest_evolution([evo])
        run = result["run"]
        assert run.events_processed == 1
        assert run.events_created == 1
        assert run.events_skipped == 0

    def test_run_metrics_with_dedup(self):
        evo = _make_evolution(content_text="Texto A")
        ingest_evolution([evo])
        result = ingest_evolution([evo])
        run = result["run"]
        assert run.events_processed == 1
        assert run.events_skipped == 1
        assert run.events_created == 0

    def test_run_parameters(self):
        evo = _make_evolution()
        result = ingest_evolution(
            [evo],
            parameters={"patient_source_key": "P001", "date_range": ["2026-04-19"]},
        )
        assert result["run"].parameters_json["patient_source_key"] == "P001"

    def test_run_finished_at_set(self):
        evo = _make_evolution()
        result = ingest_evolution([evo])
        assert result["run"].finished_at is not None

    def test_run_on_failure(self):
        """Run should be marked failed when an exception occurs."""
        # Pass evolution dict that will cause IntegrityError
        # by using a None patient_source_key which violates NOT NULL
        evo = _make_evolution()
        evo["patient_source_key"] = None
        result = ingest_evolution([evo])
        assert result["run"].status == "failed"
        assert result["run"].error_message != ""
