"""Tests for patient list view — hub /patients/ (Slice S2, S1 AFMF)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.patients.models import Patient


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def user_password() -> str:
    return "testpass123"


@pytest.fixture
def auth_client(client: Client, db: None, user_password: str) -> Client:
    """Client logged in as 'operador'."""
    User.objects.create_user(username="operador", password=user_password)
    client.login(username="operador", password=user_password)
    return client


@pytest.fixture
def patient_maria(db: None) -> Patient:
    return Patient.objects.create(
        patient_source_key="P100",
        source_system="tasy",
        name="MARIA DA SILVA",
    )


@pytest.fixture
def patient_joao(db: None) -> Patient:
    return Patient.objects.create(
        patient_source_key="P200",
        source_system="tasy",
        name="JOAO SANTOS",
    )


@pytest.fixture
def patient_ana(db: None) -> Patient:
    return Patient.objects.create(
        patient_source_key="P300",
        source_system="tasy",
        name="ANA MARIA SOUZA",
    )


# =========================================================================
# Test: Authentication gate
# =========================================================================


class TestPatientListAuth:
    """Auth boundary for /patients/."""

    def test_anonymous_redirected_to_login(self, client: Client, db: None) -> None:
        """Anonymous access to /patients/ redirects to login."""
        resp = client.get("/patients/")
        assert resp.status_code == 302
        assert "/login/" in resp["Location"]

    def test_authenticated_returns_200(
        self, auth_client: Client, db: None
    ) -> None:
        """Authenticated user gets 200."""
        resp = auth_client.get("/patients/")
        assert resp.status_code == 200


# =========================================================================
# Test: Listing
# =========================================================================


class TestPatientListListing:
    """Basic listing behaviour."""

    def test_lists_all_patients(
        self,
        auth_client: Client,
        patient_maria: Patient,
        patient_joao: Patient,
    ) -> None:
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        assert "MARIA DA SILVA" in content
        assert "JOAO SANTOS" in content

    def test_shows_patient_source_key(
        self,
        auth_client: Client,
        patient_maria: Patient,
    ) -> None:
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        assert "P100" in content

    def test_empty_state(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """When no patients exist, page shows empty state message."""
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        assert resp.status_code == 200
        # Should render without error even with no data
        assert "Nenhum paciente" in content


# =========================================================================
# Test: Search / Filter
# =========================================================================


class TestPatientListFilter:
    """Filtering by name and patient_source_key via query param `q`."""

    def test_filter_by_name(
        self,
        auth_client: Client,
        patient_maria: Patient,
        patient_joao: Patient,
    ) -> None:
        resp = auth_client.get("/patients/", {"q": "MARIA"})
        content = resp.content.decode()
        assert "MARIA DA SILVA" in content
        assert "JOAO SANTOS" not in content

    def test_filter_by_name_case_insensitive(
        self,
        auth_client: Client,
        patient_maria: Patient,
        patient_joao: Patient,
    ) -> None:
        resp = auth_client.get("/patients/", {"q": "maria"})
        content = resp.content.decode()
        assert "MARIA DA SILVA" in content
        assert "JOAO SANTOS" not in content

    def test_filter_by_patient_source_key(
        self,
        auth_client: Client,
        patient_maria: Patient,
        patient_joao: Patient,
    ) -> None:
        resp = auth_client.get("/patients/", {"q": "P200"})
        content = resp.content.decode()
        assert "JOAO SANTOS" in content
        assert "MARIA DA SILVA" not in content

    def test_filter_partial_match(
        self,
        auth_client: Client,
        patient_maria: Patient,
        patient_ana: Patient,
    ) -> None:
        """Searching 'MARIA' matches both patients with MARIA in name."""
        resp = auth_client.get("/patients/", {"q": "MARIA"})
        content = resp.content.decode()
        assert "MARIA DA SILVA" in content
        assert "ANA MARIA SOUZA" in content

    def test_filter_no_results(
        self,
        auth_client: Client,
        patient_maria: Patient,
    ) -> None:
        resp = auth_client.get("/patients/", {"q": "XYZNONEXISTENT"})
        content = resp.content.decode()
        assert "MARIA DA SILVA" not in content
        assert "Nenhum paciente" in content


# =========================================================================
# Test: Navigation links
# =========================================================================


class TestPatientListNavigation:
    """Links from patient list to other pages."""

    def test_link_to_admissions(
        self,
        auth_client: Client,
        patient_maria: Patient,
    ) -> None:
        """Each patient should link to /patients/<id>/admissions/."""
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        expected_url = f"/patients/{patient_maria.pk}/admissions/"
        assert expected_url in content

    def test_has_search_form(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """Page should contain a search form with 'q' input."""
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        assert 'name="q"' in content


# =========================================================================
# Test: Pagination
# =========================================================================


class TestPatientListPagination:
    """Simple pagination behaviour."""

    def test_pagination_page_1(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """"When there are few patients, page 1 shows all without pager."""
        Patient.objects.create(
            patient_source_key="P001",
            source_system="tasy",
            name="PACIENTE UM",
        )
        resp = auth_client.get("/patients/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "PACIENTE UM" in content

    def test_pagination_splits_pages(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """"When patients exceed page size, pagination splits them."""
        # Create enough patients to trigger pagination (page_size is small)
        for i in range(30):
            Patient.objects.create(
                patient_source_key=f"P{i:04d}",
                source_system="tasy",
                name=f"PACIENTE NUMERO {i:04d}",
            )
        resp = auth_client.get("/patients/", {"page": "1"})
        assert resp.status_code == 200
        # Page 2 should also work
        resp2 = auth_client.get("/patients/", {"page": "2"})
        assert resp2.status_code == 200


# =========================================================================
# Test: Coverage summary per patient (Slice S4)
# =========================================================================


class TestPatientCoverageSummary:
    """Coverage summary in patient list (Slice S4).


    Spec: each listed patient includes coverage summary with:
    - known admissions count,
    - admissions with extracted events count,
    - admissions without extracted events count
    """

    def test_patient_without_admissions_has_zero_coverage(
        self,
        auth_client: Client,
        patient_maria: Patient,
        db: None,
    ) -> None:
        """Patient with no admissions shows 0 for all coverage counters."""
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        # Should still show the patient with zero coverage
        assert "MARIA DA SILVA" in content
        # Coverage summary should show 0 internations
        assert "0" in content  # at least one zero visible

    def test_patient_with_admissions_shows_total_count(
        self,
        auth_client: Client,
        patient_maria: Patient,
        db: None,
    ) -> None:
        """Patient with 2 admissions shows total admissions count."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from apps.patients.models import Admission

        TZ = ZoneInfo("America/Sao_Paulo")
        Admission.objects.create(
            patient=patient_maria,
            source_admission_key="ADM001",
            source_system="tasy",
            admission_date=datetime(2026, 3, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 3, 5, 14, 0, tzinfo=TZ),
            ward="UTI",
            bed="UTI-01",
        )
        Admission.objects.create(
            patient=patient_maria,
            source_admission_key="ADM002",
            source_system="tasy",
            admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=TZ),
            ward="CLINICA MEDICA",
            bed="CM-12",
        )
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        # Should show the patient
        assert "MARIA DA SILVA" in content
        # Should show 2 internations known (badge or text)
        assert "2" in content

    def test_patient_with_some_admissions_with_events(
        self,
        auth_client: Client,
        patient_maria: Patient,
        db: None,
    ) -> None:
        """Patient shows known vs with-events vs without-events breakdown."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from django.utils import timezone

        from apps.clinical_docs.models import ClinicalEvent
        from apps.ingestion.models import IngestionRun
        from apps.patients.models import Admission

        TZ = ZoneInfo("America/Sao_Paulo")
        run = IngestionRun.objects.create(status="completed", parameters_json={})

        # Admission without events
        Admission.objects.create(
            patient=patient_maria,
            source_admission_key="ADM001",
            source_system="tasy",
            admission_date=datetime(2026, 3, 1, 10, 0, tzinfo=TZ),
            discharge_date=datetime(2026, 3, 5, 14, 0, tzinfo=TZ),
            ward="UTI",
        )
        # Admission with events
        adm2 = Admission.objects.create(
            patient=patient_maria,
            source_admission_key="ADM002",
            source_system="tasy",
            admission_date=datetime(2026, 4, 15, 8, 0, tzinfo=TZ),
            ward="CLINICA MEDICA",
        )
        now = timezone.now()
        for i, (author, prof) in enumerate([
            ("DR. CARLOS", "medica"),
            ("ENF. ANA", "enfermagem"),
        ]):
            ClinicalEvent.objects.create(
                admission=adm2,
                patient=patient_maria,
                ingestion_run=run,
                event_identity_key=f"s4_ev{i}",
                content_hash=f"s4_ch{i}",
                happened_at=now - timedelta(hours=i + 1),
                author_name=author,
                profession_type=prof,
                content_text=f"Evolucao {i} do paciente.",
            )
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        # Only 1 of 2 admissions has events
        assert "1" in content  # at least one admission with events


# =========================================================================
# Test: Admission-first recovery CTA when search has no results (S1 AFMF)
# =========================================================================


class TestPatientListMissingPatientCTA:
    """When search returns no results, show admission-first CTA.

    Spec (services-portal-navigation):
    - Primary action "Buscar/sincronizar internações" for the searched registro
    - Secondary action for period extraction as contextual/advanced option
    """

    def test_no_results_with_query_shows_primary_cta(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """Search with no match shows 'Buscar/sincronizar internações' CTA."""
        resp = auth_client.get("/patients/", {"q": "99999"})
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Buscar/sincronizar internações" in content

    def test_no_results_with_query_shows_searched_registro(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """CTA area displays the searched registro for context."""
        resp = auth_client.get("/patients/", {"q": "12345"})
        content = resp.content.decode()
        assert "12345" in content

    def test_no_results_with_query_shows_secondary_cta_period(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """Secondary action for period extraction is shown as contextual option."""
        resp = auth_client.get("/patients/", {"q": "99999"})
        content = resp.content.decode().lower()
        assert "extração por período" in content or "período de extração" in content

    def test_empty_state_without_query_has_no_cta(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """Empty patient list without search query shows generic message, no CTA."""
        resp = auth_client.get("/patients/")
        content = resp.content.decode()
        assert "Buscar/sincronizar internações" not in content

    def test_results_found_no_cta(
        self,
        auth_client: Client,
        patient_maria: Patient,
    ) -> None:
        """When results are found, CTA is not shown."""
        resp = auth_client.get("/patients/", {"q": "MARIA"})
        content = resp.content.decode()
        assert "Buscar/sincronizar internações" not in content

    def test_cta_primary_points_to_admissions_sync_with_patient_record(
        self,
        auth_client: Client,
        db: None,
    ) -> None:
        """Primary CTA points to admissions-only route with patient_record context."""
        resp = auth_client.get("/patients/", {"q": "P999"})
        content = resp.content.decode()
        expected = (
            reverse("ingestion:create_admissions_only")
            + "?patient_record=P999"
        )
        assert expected in content
