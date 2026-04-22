"""Tests for patient admission list and timeline views (Slice S4)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def ingestion_run(db: object) -> IngestionRun:
    return IngestionRun.objects.create(
        status="completed",
        parameters_json={},
    )


@pytest.fixture
def patient_maria(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P100",
        source_system="tasy",
        name="MARIA DA SILVA",
        date_of_birth=datetime(1980, 5, 15, tzinfo=TZ).date(),
    )


@pytest.fixture
def patient_joao(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P200",
        source_system="tasy",
        name="JOAO SANTOS",
    )


@pytest.fixture
def admission_maria_1(patient_maria: Patient) -> Admission:
    """First admission of Maria (earlier)."""
    return Admission.objects.create(
        patient=patient_maria,
        source_admission_key="ADM001",
        source_system="tasy",
        admission_date=datetime(2026, 3, 1, 10, 0, tzinfo=TZ),
        discharge_date=datetime(2026, 3, 5, 14, 0, tzinfo=TZ),
        ward="UTI",
        bed="UTI-01",
    )


@pytest.fixture
def admission_maria_2(patient_maria: Patient) -> Admission:
    """Second admission of Maria (current)."""
    return Admission.objects.create(
        patient=patient_maria,
        source_admission_key="ADM002",
        source_system="tasy",
        admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=TZ),
        ward="CLINICA MEDICA",
        bed="CM-12",
    )


@pytest.fixture
def admission_joao(patient_joao: Patient) -> Admission:
    return Admission.objects.create(
        patient=patient_joao,
        source_admission_key="ADM003",
        source_system="tasy",
        admission_date=datetime(2026, 4, 10, 9, 0, tzinfo=TZ),
        ward="ORTOPEDIA",
    )


@pytest.fixture
def timeline_events(
    admission_maria_2: Admission,
    patient_maria: Patient,
    ingestion_run: IngestionRun,
) -> list[ClinicalEvent]:
    """Create timeline events for Maria's second admission."""
    now = timezone.now()
    events = []

    # Medical evolution
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="tl_ev1",
            content_hash="tl_ch1",
            happened_at=now - timedelta(hours=3),
            author_name="DR. CARLOS",
            profession_type="medica",
            content_text="Paciente com melhora do quadro respiratorio.",
        )
    )

    # Nursing note
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="tl_ev2",
            content_hash="tl_ch2",
            happened_at=now - timedelta(hours=2),
            author_name="ENF. ANA",
            profession_type="enfermagem",
            content_text="Realizada troca de curativo. Sinais vitais estaveis.",
        )
    )

    # Physiotherapy note
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="tl_ev3",
            content_hash="tl_ch3",
            happened_at=now - timedelta(hours=1),
            author_name="FISIO PAULO",
            profession_type="fisioterapia",
            content_text="Sessao de fisioterapia motora realizada com sucesso.",
        )
    )

    # Another medical evolution (most recent)
    events.append(
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="tl_ev4",
            content_hash="tl_ch4",
            happened_at=now - timedelta(minutes=30),
            author_name="DRA. BEATRIZ",
            profession_type="medica",
            content_text="Paciente estavel para alta em 24h.",
        )
    )

    return events


# =========================================================================
# Test: Admission list by patient
# =========================================================================


# =========================================================================
# Test: Anonymous redirect for operational pages
# =========================================================================


class TestAnonymousRedirect:
    """Anonymous users must be redirected to login for operational pages."""

    def test_anonymous_admission_list_redirects(
        self,
        client: Client,
        patient_maria: Patient,
    ) -> None:
        response = client.get(f"/patients/{patient_maria.pk}/admissions/")
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_timeline_redirects(
        self,
        client: Client,
        admission_maria_2: Admission,
    ) -> None:
        response = client.get(f"/admissions/{admission_maria_2.pk}/timeline/")
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


# =========================================================================
# Helper: authenticated client fixture for navigation tests
# =========================================================================


@pytest.fixture
def auth_client(client: Client, db: object) -> Client:
    """Return a Client logged in as a standard user."""
    from django.contrib.auth.models import User

    User.objects.create_user(username="navuser", password="navpass123")
    client.login(username="navuser", password="navpass123")
    return client


# =========================================================================
# Test: Admission list by patient
# =========================================================================


class TestAdmissionListView:
    """Test listing admissions for a given patient."""

    def test_list_admissions_returns_200(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_1: Admission,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        assert response.status_code == 200

    def test_list_admissions_shows_patient_name(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_1: Admission,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        assert "MARIA DA SILVA" in content

    def test_list_admissions_shows_all_admissions(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_1: Admission,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        assert "UTI" in content
        assert "CLINICA MEDICA" in content

    def test_list_admissions_shows_admission_date(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        # Should show the admission date somewhere
        assert "2026" in content

    def test_list_admissions_shows_event_count(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        # Should indicate number of events
        assert "4" in content  # 4 events in admission_maria_2

    def test_list_admissions_ordered_by_date_desc(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_1: Admission,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        pos_recent = content.find("CLINICA MEDICA")
        pos_older = content.find("UTI")
        assert pos_recent < pos_older

    def test_list_admissions_404_for_unknown_patient(
        self,
        auth_client: Client,
        db: object,
    ) -> None:
        response = auth_client.get("/patients/99999/admissions/")
        # With login_required, unknown patient returns 404 (not login redirect)
        assert response.status_code == 404

    def test_list_admissions_links_to_timeline(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        # Should contain a link to the timeline view
        assert f"/admissions/{admission_maria_2.pk}/timeline/" in content

    def test_list_admissions_mobile_friendly(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        # Should have viewport meta tag for mobile
        assert "viewport" in content


# =========================================================================
# Test: Timeline by admission
# =========================================================================


class TestTimelineView:
    """Test timeline view for a specific admission."""

    def test_timeline_returns_200(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        assert response.status_code == 200

    def test_timeline_shows_patient_name(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "MARIA DA SILVA" in content

    def test_timeline_shows_all_events(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "DR. CARLOS" in content
        assert "ENF. ANA" in content
        assert "FISIO PAULO" in content
        assert "DRA. BEATRIZ" in content

    def test_timeline_shows_event_content(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "melhora do quadro respiratorio" in content

    def test_timeline_ordered_by_happened_at_desc(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        # Most recent (DRA. BEATRIZ) should appear before oldest (DR. CARLOS)
        pos_recent = content.find("DRA. BEATRIZ")
        pos_older = content.find("DR. CARLOS")
        assert pos_recent < pos_older

    def test_timeline_404_for_unknown_admission(
        self,
        auth_client: Client,
        db: object,
    ) -> None:
        response = auth_client.get("/admissions/99999/timeline/")
        assert response.status_code == 404

    def test_timeline_shows_admission_ward(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "CLINICA MEDICA" in content

    def test_timeline_mobile_friendly(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "viewport" in content


# =========================================================================
# Test: Timeline filter by profession type
# =========================================================================


class TestTimelineFilterByProfession:
    """Test filtering timeline events by profession type."""

    def test_filter_medica_only(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
            "?profession_type=medica"
        )
        content = response.content.decode()
        assert "DR. CARLOS" in content
        assert "DRA. BEATRIZ" in content
        assert "ENF. ANA" not in content
        assert "FISIO PAULO" not in content

    def test_filter_enfermagem_only(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
            "?profession_type=enfermagem"
        )
        content = response.content.decode()
        assert "ENF. ANA" in content
        assert "DR. CARLOS" not in content

    def test_filter_fisioterapia_only(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
            "?profession_type=fisioterapia"
        )
        content = response.content.decode()
        assert "FISIO PAULO" in content
        assert "DR. CARLOS" not in content

    def test_filter_shows_filter_options(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """Timeline should show available profession types as filter options."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        # Should have filter UI elements
        assert "medica" in content
        assert "enfermagem" in content
        assert "fisioterapia" in content

    def test_filter_preserves_selection(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """When filtered, the active filter should be visually indicated."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
            "?profession_type=medica"
        )
        content = response.content.decode()
        # The active filter should be marked somehow
        assert "medica" in content

    def test_no_filter_shows_all(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """Without filter, all events should be shown."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "DR. CARLOS" in content
        assert "ENF. ANA" in content
        assert "FISIO PAULO" in content
        assert "DRA. BEATRIZ" in content

    def test_empty_filter_shows_all(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """Empty profession_type filter should show all events."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
            "?profession_type="
        )
        content = response.content.decode()
        assert "DR. CARLOS" in content
        assert "ENF. ANA" in content


# =========================================================================
# Test: Card layout structure
# =========================================================================


# =========================================================================
# Test: Contextual CTAs (Nova extração + Busca JSON)
# =========================================================================


class TestAdmissionListContextualActions:
    """Test contextual actions on admission list page."""

    def test_admission_list_has_new_extraction_cta(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        """Admission list shows 'Nova extração' CTA linked with patient record."""
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        assert "Nova extra" in content
        assert f"patient_record={patient_maria.patient_source_key}" in content

    def test_admission_list_has_json_search_link(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        """Admission list shows link to JSON search endpoint."""
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        assert "/search/clinical-events/" in content

    def test_admission_list_back_link_goes_to_patients(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_2: Admission,
    ) -> None:
        """Admission list back link goes to patient list."""
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        assert '/patients/"' in content or "/patients/" in content


class TestTimelineContextualActions:
    """Test contextual actions on timeline page."""

    def test_timeline_has_new_extraction_cta(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        patient_maria: Patient,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """Timeline shows 'Nova extração' CTA linked with patient record."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "Nova extra" in content
        assert f"patient_record={patient_maria.patient_source_key}" in content

    def test_timeline_has_json_search_link(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        """Timeline shows link to JSON search endpoint."""
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "/search/clinical-events/" in content

    def test_timeline_displays_fisioterapia_for_phisiotherapy(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        patient_maria: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        """Legacy token should be rendered as fisioterapia in UI labels."""
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="legacy_type_ui",
            content_hash="legacy_type_ui_hash",
            happened_at=timezone.now(),
            author_name="FISIO UI",
            profession_type="phisiotherapy",
            content_text="Conteudo sem o termo para evitar falso-positivo.",
        )

        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "fisioterapia" in content

    def test_timeline_long_content_has_expand_button(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        patient_maria: Patient,
        ingestion_run: IngestionRun,
    ) -> None:
        """Long content should offer Bootstrap collapse expansion."""
        ClinicalEvent.objects.create(
            admission=admission_maria_2,
            patient=patient_maria,
            ingestion_run=ingestion_run,
            event_identity_key="long_content_test",
            content_hash="long_content_hash",
            happened_at=timezone.now(),
            author_name="DR. LONGO",
            profession_type="medica",
            content_text=("Linha 1 de evolução longa.\n" * 20),
        )

        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        assert "Ver mais" in content
        assert 'data-bs-toggle="collapse"' in content


class TestCardLayout:
    """Test that views use card-based layout."""

    def test_admission_list_uses_cards(
        self,
        auth_client: Client,
        patient_maria: Patient,
        admission_maria_1: Admission,
        admission_maria_2: Admission,
    ) -> None:
        response = auth_client.get(
            f"/patients/{patient_maria.pk}/admissions/"
        )
        content = response.content.decode()
        # Should have card-like structure (Bootstrap card classes)
        assert "card" in content.lower()

    def test_timeline_uses_cards(
        self,
        auth_client: Client,
        admission_maria_2: Admission,
        timeline_events: list[ClinicalEvent],
    ) -> None:
        response = auth_client.get(
            f"/admissions/{admission_maria_2.pk}/timeline/"
        )
        content = response.content.decode()
        # Should have card-like structure
        assert "card" in content.lower()
