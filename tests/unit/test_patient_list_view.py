"""Tests for patient list view — hub /patients/ (Slice S2)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

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
        """When there are few patients, page 1 shows all without pager."""
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
        """When patients exceed page size, pagination splits them."""
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
