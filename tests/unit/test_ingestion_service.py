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
    resolve_admission_for_event,
    upsert_admission_snapshot,
)
from apps.patients.models import Admission, Patient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# S2 - Upsert de internações com período + ward/bed policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpsertAdmissionSnapshot:
    """Test upsert_admission_snapshot with period fields."""

    def test_creates_admission_with_period_fields(self, db: object) -> None:
        """Admission should be created with admission_date and discharge_date."""
        patient = Patient.objects.create(
            patient_source_key="P_SNAP",
            source_system="tasy",
            name="PACIENTE SNAPSHOT",
        )
        snapshot = [
            {
                "admission_key": "ADM_SNAP_001",
                "admission_start": "2026-04-01 08:00:00",
                "admission_end": "2026-04-10 18:00:00",
                "ward": "UTI Adulto",
                "bed": "UTI-05",
            },
        ]
        result = upsert_admission_snapshot(patient, snapshot)
        assert result["created"] == 1
        assert result["updated"] == 0
        adm = Admission.objects.get(source_admission_key="ADM_SNAP_001")
        assert adm.admission_date is not None
        assert adm.discharge_date is not None
        assert adm.ward == "UTI Adulto"
        assert adm.bed == "UTI-05"

    def test_creates_admission_with_null_discharge_date(self, db: object) -> None:
        """Active admission (no discharge date) should be persisted correctly."""
        patient = Patient.objects.create(
            patient_source_key="P_SNAP2",
            source_system="tasy",
            name="PACIENTE ATIVO",
        )
        snapshot = [
            {
                "admission_key": "ADM_ACTIVE",
                "admission_start": "2026-04-15 10:00:00",
                "admission_end": None,
                "ward": "Clinica Medica",
                "bed": "CM-12",
            },
        ]
        result = upsert_admission_snapshot(patient, snapshot)
        assert result["created"] == 1
        adm = Admission.objects.get(source_admission_key="ADM_ACTIVE")
        assert adm.discharge_date is None
        assert adm.ward == "Clinica Medica"

    def test_upsert_updates_existing_admission_period_fields(self, db: object) -> None:
        """Existing admission should have period fields updated on re-ingestion."""
        patient = Patient.objects.create(
            patient_source_key="P_SNAP3",
            source_system="tasy",
            name="PACIENTE UPDATE",
        )
        snapshot_v1 = [
            {
                "admission_key": "ADM_UPD",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-10 18:00:00",
                "ward": "UTI",
                "bed": "UTI-01",
            },
        ]
        upsert_admission_snapshot(patient, snapshot_v1)

        snapshot_v2 = [
            {
                "admission_key": "ADM_UPD",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-15 12:00:00",  # extended discharge
                "ward": "UTI",
                "bed": "UTI-01",
            },
        ]
        result = upsert_admission_snapshot(patient, snapshot_v2)
        assert result["created"] == 0
        assert result["updated"] == 1
        adm = Admission.objects.get(source_admission_key="ADM_UPD")
        assert adm.discharge_date is not None

    def test_empty_ward_bed_does_not_overwrite_existing(self, db: object) -> None:
        """Empty ward/bed in snapshot must NOT overwrite existing non-empty values."""
        patient = Patient.objects.create(
            patient_source_key="P_WARD",
            source_system="tasy",
            name="PACIENTE WARD",
        )
        # First: create with ward/bed
        snapshot_with = [
            {
                "admission_key": "ADM_WARD",
                "admission_start": "2026-04-01 08:00:00",
                "admission_end": "2026-04-05 18:00:00",
                "ward": "UTI Adulto",
                "bed": "UTI-10",
            },
        ]
        upsert_admission_snapshot(patient, snapshot_with)

        # Second: re-run with empty ward/bed (simulates past admission with no location)
        snapshot_without = [
            {
                "admission_key": "ADM_WARD",
                "admission_start": "2026-04-01 08:00:00",
                "admission_end": "2026-04-05 18:00:00",
                "ward": "",
                "bed": "",
            },
        ]
        upsert_admission_snapshot(patient, snapshot_without)

        adm = Admission.objects.get(source_admission_key="ADM_WARD")
        assert adm.ward == "UTI Adulto"  # preserved
        assert adm.bed == "UTI-10"  # preserved

    def test_non_empty_ward_bed_updates_existing_empty(self, db: object) -> None:
        """Non-empty ward/bed should update existing empty values."""
        patient = Patient.objects.create(
            patient_source_key="P_WARD2",
            source_system="tasy",
            name="PACIENTE WARD2",
        )
        # First: create WITHOUT ward/bed (simulates old admission)
        snapshot_without = [
            {
                "admission_key": "ADM_WARD2",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-10 18:00:00",
                "ward": "",
                "bed": "",
            },
        ]
        upsert_admission_snapshot(patient, snapshot_without)

        # Second: re-run WITH ward/bed
        snapshot_with = [
            {
                "admission_key": "ADM_WARD2",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-10 18:00:00",
                "ward": "Clinica Cirurgica",
                "bed": "CC-03",
            },
        ]
        upsert_admission_snapshot(patient, snapshot_with)

        adm = Admission.objects.get(source_admission_key="ADM_WARD2")
        assert adm.ward == "Clinica Cirurgica"
        assert adm.bed == "CC-03"

    def test_returns_correct_counts(self, db: object) -> None:
        """upsert_admission_snapshot should return correct created/updated counts."""
        patient = Patient.objects.create(
            patient_source_key="P_CNT",
            source_system="tasy",
            name="PACIENTE COUNTS",
        )
        # First run: 3 new admissions
        snapshot1 = [
            {
                "admission_key": "ADM_A",
                "admission_start": "2026-01-01 08:00:00",
                "admission_end": "2026-01-05 18:00:00",
                "ward": "",
                "bed": "",
            },
            {
                "admission_key": "ADM_B",
                "admission_start": "2026-02-01 08:00:00",
                "admission_end": "2026-02-05 18:00:00",
                "ward": "",
                "bed": "",
            },
            {
                "admission_key": "ADM_C",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-05 18:00:00",
                "ward": "",
                "bed": "",
            },
        ]
        result1 = upsert_admission_snapshot(patient, snapshot1)
        assert result1["created"] == 3
        assert result1["updated"] == 0

        # Second run: 1 new (D) + 1 updated (B extended) + 1 unchanged (C)
        snapshot2 = [
            {
                "admission_key": "ADM_B",
                "admission_start": "2026-02-01 08:00:00",
                "admission_end": "2026-02-10 18:00:00",
                "ward": "",
                "bed": "",
            },
            {
                "admission_key": "ADM_C",
                "admission_start": "2026-03-01 08:00:00",
                "admission_end": "2026-03-05 18:00:00",
                "ward": "",
                "bed": "",
            },
            {
                "admission_key": "ADM_D",
                "admission_start": "2026-04-01 08:00:00",
                "admission_end": "2026-04-05 18:00:00",
                "ward": "",
                "bed": "",
            },
        ]
        result2 = upsert_admission_snapshot(patient, snapshot2)
        assert result2["created"] == 1  # ADM_D
        assert result2["updated"] == 1  # ADM_B


# ---------------------------------------------------------------------------
# S2 - Fallback determinístico de associação evento -> internação
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResolveAdmissionDeterministicFallback:
    """Test resolve_admission_for_event with deterministic fallback rules."""

    # Counter for unique patient source keys within this test class
    _patient_counter = 0

    def _make_patient(self) -> Patient:
        """Create a unique patient for each admission set."""
        TestResolveAdmissionDeterministicFallback._patient_counter += 1
        return Patient.objects.create(
            patient_source_key=f"P_RESOLVE_{TestResolveAdmissionDeterministicFallback._patient_counter}",
            source_system="tasy",
            name="PACIENTE RESOLVE",
        )

    def _make_adm(
        self,
        source_admission_key: str,
        admission_start: str,
        admission_end: str | None,
        patient: Patient | None = None,
    ) -> tuple[Admission, Patient]:
        """Helper to create an admission with a patient (timezone-aware)."""
        if patient is None:
            patient = self._make_patient()
        # Parse and localize to institutional timezone to suppress Django warnings
        adm_start = _parse_naive_datetime(admission_start)
        adm_end = _parse_naive_datetime(admission_end) if admission_end else None
        adm = Admission.objects.create(
            patient=patient,
            source_admission_key=source_admission_key,
            source_system="tasy",
            admission_date=adm_start,
            discharge_date=adm_end,
        )
        return adm, patient

    def test_resolves_by_admission_key_direct(self, db: object) -> None:
        """Evolution with valid admission_key should return that admission directly."""
        adm, patient = self._make_adm("ADM_DIRECT", "2026-04-01T08:00:00", "2026-04-10T18:00:00")
        result = resolve_admission_for_event(
            admission_key="ADM_DIRECT",
            happened_at=datetime(2026, 4, 5, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm.pk

    def test_resolves_by_period_fallback(self, db: object) -> None:
        """Evolution without admission_key should resolve by happened_at period."""
        adm, patient = self._make_adm("ADM_PERIOD", "2026-04-01T08:00:00", "2026-04-10T18:00:00")
        result = resolve_admission_for_event(
            admission_key="",  # invalid key
            happened_at=datetime(2026, 4, 5, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm.pk

    def test_resolves_by_period_active_admission(self, db: object) -> None:
        """Active admission (null discharge_date) should match happened_at >= admission_date."""
        adm, patient = self._make_adm("ADM_ACTIVE", "2026-04-15T08:00:00", None)
        result = resolve_admission_for_event(
            admission_key="",
            happened_at=datetime(2026, 4, 20, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm.pk

    def test_fallback_multiple_matches_picks_latest_admission_date(
        self, db: object
    ) -> None:
        """When multiple admissions match the period, pick the one with latest admission_date."""
        patient = self._make_patient()
        adm_old, _ = self._make_adm(
            "ADM_OLD", "2026-01-01T08:00:00", "2026-01-10T18:00:00", patient=patient
        )
        adm_new, _ = self._make_adm(
            "ADM_NEW", "2026-01-15T08:00:00", "2026-02-10T18:00:00", patient=patient
        )
        result = resolve_admission_for_event(
            admission_key="",
            happened_at=datetime(2026, 2, 1, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm_new.pk

    def test_fallback_no_match_picks_nearest_previous(
        self, db: object
    ) -> None:
        """When no period match, pick the admission with nearest previous admission_date."""
        patient = self._make_patient()
        adm1, _ = self._make_adm(
            "ADM_1", "2026-01-01T08:00:00", "2026-01-10T18:00:00", patient=patient
        )
        adm2, _ = self._make_adm(
            "ADM_2", "2026-03-01T08:00:00", "2026-04-20T08:00:00", patient=patient
        )
        result = resolve_admission_for_event(
            admission_key="",
            happened_at=datetime(2026, 4, 20, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm2.pk

    def test_fallback_no_previous_picks_nearest_posterior(
        self, db: object
    ) -> None:
        """When no previous admission exists, pick the nearest posterior."""
        adm_future, patient = self._make_adm(
            "ADM_FUTURE", "2026-05-01T08:00:00", "2026-05-10T18:00:00"
        )
        result = resolve_admission_for_event(
            admission_key="",
            happened_at=datetime(2026, 4, 1, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == adm_future.pk

    def test_fallback_tiebreak_by_source_admission_key_ascending(
        self, db: object
    ) -> None:
        """When admissions are equally distant, tiebreak by source_admission_key ascending."""
        patient = Patient.objects.create(
            patient_source_key="P_TIE",
            source_system="tasy",
            name="PACIENTE TIE",
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM_AAA",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 8, 0, tzinfo=TZ_INST),
            discharge_date=datetime(2026, 4, 10, 18, 0, tzinfo=TZ_INST),
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM_BBB",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 8, 0, tzinfo=TZ_INST),
            discharge_date=datetime(2026, 4, 10, 18, 0, tzinfo=TZ_INST),
        )
        result = resolve_admission_for_event(
            admission_key="",
            happened_at=datetime(2026, 6, 1, 10, 0, tzinfo=TZ_INST),
            patient=patient,
        )
        assert result.pk == Admission.objects.get(source_admission_key="ADM_AAA").pk

    def test_resolve_requires_patient_argument(self, db: object) -> None:
        """resolve_admission_for_event must receive a patient to scope the search."""
        from pytest import raises
        with raises(ValueError, match="patient"):
            resolve_admission_for_event(
                admission_key="",
                happened_at=datetime(2026, 4, 5, 10, 0, tzinfo=TZ_INST),
                patient=None,
            )

    def test_resolve_raises_when_no_admission_for_patient(
        self, db: object
    ) -> None:
        """resolve_admission_for_event should raise when patient has no admissions."""
        patient_no_adm = Patient.objects.create(
            patient_source_key="P_NO_ADM",
            source_system="tasy",
            name="SEM INTERNACOES",
        )
        from pytest import raises
        with raises(Admission.DoesNotExist):
            resolve_admission_for_event(
                admission_key="",
                happened_at=datetime(2026, 4, 5, 10, 0, tzinfo=TZ_INST),
                patient=patient_no_adm,
            )
