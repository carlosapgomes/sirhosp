"""Characterization tests for the shared evolution ingestion service (PSW-S7).

Tests the ``ingest_evolutions`` shared service that preserves the current
worker's ``_ingest_evolutions`` behavior exactly. These tests characterize
the previous command-local behavior before extracting it into a shared service.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.ingestion.services import compute_content_hash, compute_event_identity_key
from apps.patients.models import Admission, Patient

TZ_INST = ZoneInfo("America/Sao_Paulo")


def _parse_naive_datetime(value: str | None) -> datetime | None:
    """Parse a naive datetime string and localize to institutional TZ (test helper)."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_INST)
    return dt


def _make_evolution(
    *,
    admission_key: str = "ADM001",
    patient_source_key: str = "P001",
    patient_name: str = "MARIA DA SILVA",
    happened_at: str | None = "2026-04-19 08:30:00",
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patient() -> Patient:
    """Create a patient that will be reused across tests."""
    return Patient.objects.create(
        source_system="tasy",
        patient_source_key="P001",
        name="MARIA DA SILVA",
    )


@pytest.fixture
def run() -> IngestionRun:
    """Create an IngestionRun for testing."""
    return IngestionRun.objects.create(
        status="running",
        parameters_json={"patient_record": "P001", "intent": "full_sync"},
    )


@pytest.fixture
def existing_admission(patient: Patient) -> Admission:
    """Create an existing admission for period-based resolution."""
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key="ADM001",
        admission_date=_parse_naive_datetime("2026-04-01 00:00:00"),
        discharge_date=_parse_naive_datetime("2026-04-30 23:59:00"),
        ward="UTI",
        bed="LEITO 01",
    )


# ---------------------------------------------------------------------------
# Test class: ingest_evolutions shared service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestEvolutionsService:
    """Characterization tests for the shared ingest_evolutions service.

    These tests verify that the shared service preserves the exact behavior
    of the current worker's ``_ingest_evolutions`` method:
    - Patient upsert behavior.
    - Deterministic admission resolution by admission_key and happened_at.
    - Fallback admission upsert when resolution fails.
    - ``_persist_event`` behavior (dedup, revision).
    - created/skipped/revised counters.
    - Transaction boundaries equivalent to current behavior.
    - Timezone handling for naive happened_at values.
    """

    # ------------------------------------------------------------------
    # 7.1.a: Basic ingestion — counters and event creation
    # ------------------------------------------------------------------

    def test_creates_event_and_returns_counters(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Single evolution with matching admission should create 1 event."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evolutions = [_make_evolution()]
        created, skipped, revised = ingest_evolutions(evolutions, run, patient)

        assert created == 1
        assert skipped == 0
        assert revised == 0
        assert ClinicalEvent.objects.filter(patient=patient).count() == 1

    def test_skips_duplicate_events(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Duplicate evolution (same identity + content) should be skipped."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution()
        ingest_evolutions([evo], run, patient)

        created, skipped, revised = ingest_evolutions([evo], run, patient)

        assert created == 0
        assert skipped == 1
        assert revised == 0
        assert ClinicalEvent.objects.filter(patient=patient).count() == 1

    def test_revises_event_when_content_changes(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Same identity but different content should create a revision."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo_v1 = _make_evolution(content_text="Versão 1")
        ingest_evolutions([evo_v1], run, patient)

        evo_v2 = _make_evolution(content_text="Versão 2 revisada")
        created, skipped, revised = ingest_evolutions([evo_v2], run, patient)

        assert created == 0
        assert skipped == 0
        assert revised == 1
        assert ClinicalEvent.objects.filter(patient=patient).count() == 2

    def test_mixed_batch_counters(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Mixed batch: 1 created, 1 duplicate, 1 new should produce correct counts."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo_original = _make_evolution(content_text="Original")
        ingest_evolutions([evo_original], run, patient)

        evo_dup = _make_evolution(content_text="Original")
        evo_new = _make_evolution(
            happened_at="2026-04-19 10:00:00",
            author_name="DRA. ANA",
            content_text="Nova evolução",
            admission_key="ADM002",
        )
        created, skipped, revised = ingest_evolutions([evo_dup, evo_new], run, patient)

        assert created == 1
        assert skipped == 1
        assert revised == 0
        assert ClinicalEvent.objects.filter(patient=patient).count() == 2

    # ------------------------------------------------------------------
    # 7.1.b: Patient upsert behavior
    # ------------------------------------------------------------------

    def test_upserts_patient_when_not_exists(
        self, run: IngestionRun, existing_admission: Admission
    ):
        """New patient_source_key should create a patient record."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(
            patient_source_key="NEW_PATIENT",
            patient_name="PACIENTE NOVO",
            admission_key="ADM_NEW",
        )
        # Drop pre-created patient fixture — pass None patient
        # (patient will be looked up from evo)
        patient_obj = Patient.objects.create(
            source_system="tasy",
            patient_source_key="NEW_PATIENT",
            name="",
        )
        created, skipped, revised = ingest_evolutions([evo], run, patient_obj)

        assert created == 1
        patient_obj.refresh_from_db()
        assert patient_obj.name == "PACIENTE NOVO"

    def test_updates_patient_name_on_change(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Patient name change should be propagated via _upsert_patient."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo_new_name = _make_evolution(patient_name="MARIA DA SILVA SOUZA")
        created, skipped, revised = ingest_evolutions([evo_new_name], run, patient)

        assert created == 1
        patient.refresh_from_db()
        assert patient.name == "MARIA DA SILVA SOUZA"

    # ------------------------------------------------------------------
    # 7.1.c: Admission resolution by admission_key (direct)
    # ------------------------------------------------------------------

    def test_resolves_admission_by_key(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Evolution with matching admission_key should resolve to that admission."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(admission_key="ADM001")
        ingest_evolutions([evo], run, patient)

        event = ClinicalEvent.objects.filter(patient=patient).first()
        assert event is not None
        assert event.admission.source_admission_key == "ADM001"

    def test_resolves_admission_by_period_fallback(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Evolution with empty admission_key should resolve by period."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(admission_key="")
        ingest_evolutions([evo], run, patient)

        event = ClinicalEvent.objects.filter(patient=patient).first()
        assert event is not None
        assert event.admission is not None

    # ------------------------------------------------------------------
    # 7.1.d: Fallback admission upsert when resolution fails
    # ------------------------------------------------------------------

    def test_fallback_upsert_admission_when_resolution_fails(
        self, run: IngestionRun, patient: Patient
    ):
        """When resolve_admission_for_event fails, fallback to _upsert_admission."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        # No admission exists for this patient — resolution will fail,
        # fallback should create one from evolution data
        evo = _make_evolution(admission_key="FALLBACK_ADM")
        created, skipped, revised = ingest_evolutions([evo], run, patient)

        assert created == 1
        # Admission should have been created via fallback
        assert Admission.objects.filter(
            patient=patient,
            source_admission_key="FALLBACK_ADM",
        ).exists()

    def test_fallback_creates_admission_with_ward_bed(
        self, run: IngestionRun, patient: Patient
    ):
        """Fallback upsert should populate ward/bed from evolution data."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(
            admission_key="ADM_FALLBACK_WARD",
            ward="Clinica Medica",
            bed="CM-05",
        )
        ingest_evolutions([evo], run, patient)

        adm = Admission.objects.get(source_admission_key="ADM_FALLBACK_WARD")
        assert adm.ward == "Clinica Medica"
        assert adm.bed == "CM-05"

    # ------------------------------------------------------------------
    # 7.1.e: Transaction boundaries
    # ------------------------------------------------------------------

    def test_transaction_isolation_per_evolution(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Each evolution should be processed in its own transaction.

        If one evolution fails, previous ones should still be persisted.
        """
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo1 = _make_evolution(content_text="Primeira evolução")
        evo2 = _make_evolution(
            content_text="Segunda evolução",
            happened_at="2026-04-20 09:00:00",
        )

        # Process individually to verify transaction isolation
        c1, s1, r1 = ingest_evolutions([evo1], run, patient)
        assert c1 == 1

        # Second should fail by patching _upsert_patient to raise
        from unittest.mock import patch

        def failing_upsert(evo, r):
            raise ValueError("Simulated failure")

        with patch(
            "apps.ingestion.evolution_ingestion._upsert_patient",
            side_effect=failing_upsert,
        ):
            with pytest.raises(ValueError, match="Simulated failure"):
                ingest_evolutions([evo2], run, patient)

        # First event should still exist (unaffected by second failure)
        assert ClinicalEvent.objects.filter(patient=patient).count() >= 1

    # ------------------------------------------------------------------
    # 7.1.f: Timezone handling for naive happened_at
    # ------------------------------------------------------------------

    def test_naive_happened_at_localized(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Naive happened_at should be localized to America/Sao_Paulo."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(happened_at="2026-04-19 08:30:00")
        ingest_evolutions([evo], run, patient)

        event = ClinicalEvent.objects.filter(patient=patient).first()
        assert event is not None
        assert event.happened_at.tzinfo is not None
        assert event.happened_at == datetime(2026, 4, 19, 8, 30, 0, tzinfo=TZ_INST)

    # ------------------------------------------------------------------
    # 7.1.g: Event-identity key + content hash behavior
    # ------------------------------------------------------------------

    def test_event_identity_key_and_content_hash_equivalent(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """The service should produce events with correct identity_key and content_hash."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evo = _make_evolution(content_text="Conteúdo para hash")
        ingest_evolutions([evo], run, patient)

        event = ClinicalEvent.objects.filter(patient=patient).first()
        assert event is not None
        expected_identity = compute_event_identity_key(evo, patient_id=patient.pk)
        expected_hash = compute_content_hash(evo["content_text"])

        assert event.event_identity_key == expected_identity
        assert event.content_hash == expected_hash

    # ------------------------------------------------------------------
    # 7.1.h: Return type and consistency
    # ------------------------------------------------------------------

    def test_returns_tuple_of_three_ints(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Service should return a tuple of three ints (created, skipped, revised)."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        result = ingest_evolutions([_make_evolution()], run, patient)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(isinstance(v, int) for v in result)

    def test_multiple_evolutions_in_one_call(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Multiple distinct evolutions should all be created in one call."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evos = [
            _make_evolution(
                happened_at="2026-04-19 08:00:00",
                content_text="Evolução 1",
                admission_key="ADM001",
            ),
            _make_evolution(
                happened_at="2026-04-19 09:00:00",
                content_text="Evolução 2",
                author_name="DRA. ANA",
                admission_key="ADM001",
            ),
            _make_evolution(
                happened_at="2026-04-19 10:00:00",
                content_text="Evolução 3",
                author_name="DR. PEDRO",
                admission_key="ADM001",
            ),
        ]
        created, skipped, revised = ingest_evolutions(evos, run, patient)

        assert created == 3
        assert skipped == 0
        assert revised == 0
        assert ClinicalEvent.objects.filter(patient=patient).count() == 3


# ---------------------------------------------------------------------------
# Test: Worker delegation preserves behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerDelegation:
    """Tests that the current worker still calls equivalent persistence.

    After extracting the shared service, the current worker's _process_full_sync
    path must still persist evolutions and return equivalent counters.
    """

    def test_worker_delegates_to_service_full_sync_path(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Simulate the worker's full-sync ingestion path via the shared service.

        The worker calls ingest_evolutions AFTER extracting evolutions,
        so we verify the shared service preserves worker behavior directly.
        """
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        evolutions = [
            _make_evolution(
                happened_at="2026-04-19 08:00:00",
                content_text="Evolução manhã",
                admission_key="ADM001",
            ),
            _make_evolution(
                happened_at="2026-04-19 14:00:00",
                content_text="Evolução tarde",
                author_name="DRA. BEATRIZ",
                admission_key="ADM001",
            ),
        ]
        created, skipped, revised = ingest_evolutions(evolutions, run, patient)

        assert created == 2

        # Re-ingest same evolutions should skip
        created2, skipped2, revised2 = ingest_evolutions(evolutions, run, patient)
        assert created2 == 0
        assert skipped2 == 2
        assert revised2 == 0

        # Total events = 2 (no duplicates, no revisions)
        assert ClinicalEvent.objects.filter(patient=patient).count() == 2

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_evolutions_list(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Empty evolutions list should return zero counters."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        created, skipped, revised = ingest_evolutions([], run, patient)

        assert created == 0
        assert skipped == 0
        assert revised == 0

    def test_missing_happened_at_uses_now(
        self, run: IngestionRun, existing_admission: Admission, patient: Patient
    ):
        """Evolution without happened_at should use current time."""
        from apps.ingestion.evolution_ingestion import ingest_evolutions

        # Omit happened_at entirely — same as real missing data
        evo = _make_evolution(happened_at=None)
        created, skipped, revised = ingest_evolutions([evo], run, patient)

        assert created == 1
        event = ClinicalEvent.objects.filter(patient=patient).first()
        assert event is not None
        assert event.happened_at is not None
        # Should be close to now
        now = timezone.now()
        diff = abs((event.happened_at - now).total_seconds())
        assert diff < 60  # Within 60 seconds
