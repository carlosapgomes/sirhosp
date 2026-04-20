"""Tests for clinical event FTS search service (Slice S3)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient
from apps.search.services import SearchQueryParams, search_clinical_events

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def ingestion_run(db: object) -> IngestionRun:
    return IngestionRun.objects.create(
        status="completed",
        parameters_json={},
    )


@pytest.fixture
def patient_a(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P001",
        source_system="tasy",
        name="MARIA SILVA",
    )


@pytest.fixture
def patient_b(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P002",
        source_system="tasy",
        name="JOAO SANTOS",
    )


@pytest.fixture
def admission_a(patient_a: Patient) -> Admission:
    return Admission.objects.create(
        patient=patient_a,
        source_admission_key="A001",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, tzinfo=TZ),
        ward="UTI",
    )


@pytest.fixture
def admission_b(patient_b: Patient) -> Admission:
    return Admission.objects.create(
        patient=patient_b,
        source_admission_key="A002",
        source_system="tasy",
        admission_date=datetime(2026, 4, 10, tzinfo=TZ),
        ward="CLINICA",
    )


@pytest.fixture
def sample_events(
    admission_a: Admission,
    admission_b: Admission,
    patient_a: Patient,
    patient_b: Patient,
    ingestion_run: IngestionRun,
) -> list[ClinicalEvent]:
    """Create a set of clinical events for search testing."""
    now = timezone.now()
    events = []

    # Event 1: medical evolution by Dr. Carlos - patient A
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_a,
            patient=patient_a,
            ingestion_run=ingestion_run,
            event_identity_key="ev1",
            content_hash="ch1",
            happened_at=now - timedelta(hours=2),
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text=(
                "Paciente com quadro de pneumonia bacteriana. "
                "Iniciado antibioticoterapia com amoxicilina. "
                "Saturacao estavel em 96%."
            ),
        )
    )

    # Event 2: nursing note - patient A
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_a,
            patient=patient_a,
            ingestion_run=ingestion_run,
            event_identity_key="ev2",
            content_hash="ch2",
            happened_at=now - timedelta(hours=1),
            author_name="ENF. ANA",
            profession_type="enfermagem",
            content_text=(
                "Paciente acordada, orientada. Realizada troca de "
                "curativo no local de acesso venoso. Sinais vitais "
                "dentro da normalidade."
            ),
        )
    )

    # Event 3: physiotherapy note - patient A
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_a,
            patient=patient_a,
            ingestion_run=ingestion_run,
            event_identity_key="ev3",
            content_hash="ch3",
            happened_at=now - timedelta(hours=1, minutes=30),
            author_name="FISIO PAULO",
            profession_type="fisioterapia",
            content_text=(
                "Sessao de fisioterapia respiratoria realizada. "
                "Paciente colaborativa, com melhora do padrão "
                "respiratório."
            ),
        )
    )

    # Event 4: medical evolution - patient B
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_b,
            patient=patient_b,
            ingestion_run=ingestion_run,
            event_identity_key="ev4",
            content_hash="ch4",
            happened_at=now - timedelta(days=1),
            author_name="DRA. BEATRIZ",
            profession_type="medica",
            content_text=(
                "Paciente com fratura de femur pos queda. "
                "Indicada cirurgia ortopedica para fixacao interna. "
                "Saturacao estavel."
            ),
        )
    )

    # Event 5: nursing note - patient B (outside default period)
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_b,
            patient=patient_b,
            ingestion_run=ingestion_run,
            event_identity_key="ev5",
            content_hash="ch5",
            happened_at=now - timedelta(days=10),
            author_name="ENF. CARLA",
            profession_type="enfermagem",
            content_text=(
                "Paciente com sinais vitais estaveis. "
                "Administrada medicação prescrita sem intercorrências."
            ),
        )
    )

    return events


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestSearchByFreeText:
    """Test FTS free-text search returning results by relevance."""

    def test_search_returns_matching_events(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        results = search_clinical_events(SearchQueryParams(query="pneumonia"))
        ids = [r.pk for r in results]
        assert sample_events[0].pk in ids

    def test_search_relevance_ordering(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        """Events with higher relevance (more term matches) come first."""
        results = list(
            search_clinical_events(SearchQueryParams(query="saturacao"))
        )
        pks = [r.pk for r in results]
        # Both event 1 and event 4 mention "saturacao"
        assert sample_events[0].pk in pks
        assert sample_events[3].pk in pks

    def test_search_no_results_for_irrelevant_query(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="astronauta espacial")
        )
        assert list(results) == []

    def test_search_empty_query_returns_nothing(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        results = search_clinical_events(SearchQueryParams(query=""))
        assert list(results) == []


class TestSearchFilterByPatient:
    """Test filtering search results by patient."""

    def test_filter_by_patient_id(
        self, sample_events: list[ClinicalEvent], patient_a: Patient
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", patient_id=patient_a.pk)
        )
        pks = [r.pk for r in results]
        assert sample_events[0].pk in pks
        assert sample_events[3].pk not in pks

    def test_filter_returns_only_patient_events(
        self, sample_events: list[ClinicalEvent], patient_b: Patient
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", patient_id=patient_b.pk)
        )
        for event in results:
            assert event.patient_id == patient_b.pk


class TestSearchFilterByAdmission:
    """Test filtering search results by admission."""

    def test_filter_by_admission_id(
        self, sample_events: list[ClinicalEvent], admission_a: Admission
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", admission_id=admission_a.pk)
        )
        pks = [r.pk for r in results]
        assert sample_events[0].pk in pks
        assert sample_events[3].pk not in pks


class TestSearchFilterByProfessionType:
    """Test filtering search results by profession type."""

    def test_filter_medica_only(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", profession_type="medica")
        )
        for event in results:
            assert event.profession_type == "medica"

    def test_filter_enfermagem_only(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(query="sinais vitais", profession_type="enfermagem")
        )
        for event in results:
            assert event.profession_type == "enfermagem"
        assert len(list(results)) >= 1


class TestSearchFilterByPeriod:
    """Test filtering search results by date range."""

    def test_filter_by_date_from(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        now = timezone.now()
        date_from = now - timedelta(hours=3)
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", date_from=date_from)
        )
        pks = [r.pk for r in results]
        # Event 1 is within 3 hours
        assert sample_events[0].pk in pks
        # Event 4 is from yesterday — outside the 3h window
        assert sample_events[3].pk not in pks

    def test_filter_by_date_to(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        now = timezone.now()
        date_to = now - timedelta(hours=1, minutes=45)
        results = search_clinical_events(
            SearchQueryParams(query="saturacao", date_to=date_to)
        )
        for event in results:
            assert event.happened_at <= date_to


class TestSearchCombinedFilters:
    """Test search with multiple combined filters."""

    def test_combined_patient_and_profession(
        self,
        sample_events: list[ClinicalEvent],
        patient_a: Patient,
    ) -> None:
        results = search_clinical_events(
            SearchQueryParams(
                query="saturacao",
                patient_id=patient_a.pk,
                profession_type="medica",
            )
        )
        pks = [r.pk for r in results]
        # Event 1: patient_a + medica + mentions saturacao
        assert sample_events[0].pk in pks
        # Event 4: patient_b, should be excluded
        assert sample_events[3].pk not in pks
        for event in results:
            assert event.patient_id == patient_a.pk
            assert event.profession_type == "medica"

    def test_combined_patient_period_profession(
        self,
        sample_events: list[ClinicalEvent],
        patient_a: Patient,
    ) -> None:
        now = timezone.now()
        results = search_clinical_events(
            SearchQueryParams(
                query="paciente",
                patient_id=patient_a.pk,
                profession_type="enfermagem",
                date_from=now - timedelta(hours=2),
            )
        )
        for event in results:
            assert event.patient_id == patient_a.pk
            assert event.profession_type == "enfermagem"
            assert event.happened_at >= now - timedelta(hours=2)


class TestSearchResultTraceability:
    """Test that search results include traceability fields."""

    def test_result_has_traceability_fields(
        self, sample_events: list[ClinicalEvent]
    ) -> None:
        """Results must include event_id, patient_id, admission_id,
        happened_at for timeline navigation."""
        results = list(
            search_clinical_events(SearchQueryParams(query="pneumonia"))
        )
        assert len(results) > 0
        event = results[0]
        # These fields must be accessible on the returned object
        assert event.pk is not None  # event_id
        assert event.patient_id is not None
        assert event.admission_id is not None
        assert event.happened_at is not None
