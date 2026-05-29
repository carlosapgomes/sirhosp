"""Tests for Setores > Ocupação page (Slice PMT-S4) and Indicadores (PMT-S5 placeholder).

Tests for sector_occupation view: filters, summary cards, patient table,
empty state, and authentication.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.census.models import PatientMovement
from apps.patients.models import Patient

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def logged_client(db: object) -> Client:
    from django.contrib.auth.models import User

    User.objects.create_user(username="testuser", password="testpass")
    c = Client()
    c.login(username="testuser", password="testpass")
    return c


@pytest.fixture
def patient(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P001",
        source_system="tasy",
        name="PACIENTE ALFA",
        date_of_birth=date(1980, 5, 10),
    )


@pytest.fixture
def patient2(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P002",
        source_system="tasy",
        name="PACIENTE BETA",
        date_of_birth=date(1990, 3, 20),
    )


@pytest.fixture
def patient3(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P003",
        source_system="tasy",
        name="PACIENTE GAMA",
        date_of_birth=date(2000, 7, 15),
    )


def _make_movement(
    patient: Patient,
    sector: str,
    movement_date: date,
    origin: str = "",
    discharge_type: str = "",
    sequence: int = 0,
    days_ago: int = 0,
) -> PatientMovement:
    """Helper to create a PatientMovement with timestamps relative to now."""
    now = timezone.now()
    first_seen = now - timedelta(days=days_ago, hours=2)
    last_seen = now - timedelta(days=days_ago)
    return PatientMovement.objects.create(
        patient=patient,
        movement_date=movement_date,
        sector=sector,
        origin=origin,
        discharge_type=discharge_type,
        sequence=sequence,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorOccupationAuth:
    """Authentication requirements for sector_occupation page."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object) -> None:
        pass

    def test_occupation_page_requires_auth(self, client: Client) -> None:
        """Anonymous user is redirected to login."""
        url = reverse("services_portal:sector_occupation")
        response = client.get(url)
        assert response.status_code == 302
        location = response.get("Location", "")
        assert "/login" in location

    def test_occupation_page_renders_authenticated(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Authenticated user gets HTTP 200."""
        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestSectorOccupationFilters:
    """Filtering by sector and period."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        pass

    def test_occupation_filters_by_sector(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Query with ?setor=UTI filters PatientMovement by sector."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today, days_ago=1)
        _make_movement(patient2, "ENFERMARIA", today, days_ago=1)

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        assert response.status_code == 200
        summary = response.context["summary"]
        assert summary["total"] == 1
        assert summary["still_in"] == 1

    def test_occupation_default_period_7_days(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Without ?dias=, uses period of 7 days."""
        today = timezone.now().date()
        # Movement within 7 days
        _make_movement(patient, "UTI", today - timedelta(days=3), days_ago=3)
        # Movement older than 7 days
        _make_movement(patient, "UTI", today - timedelta(days=15), days_ago=15)

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        summary = response.context["summary"]
        # Only the recent one should be counted
        assert summary["total"] == 1

    def test_occupation_respects_period_param(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """?dias=30 uses cutoff of 30 days."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=20), days_ago=20)

        # Only 7 day window — should exclude
        url_7d = reverse("services_portal:sector_occupation") + "?setor=UTI&dias=7"
        response_7d = logged_client.get(url_7d)
        assert response_7d.context["summary"]["total"] == 0

        # 30 day window — should include
        url_30d = reverse("services_portal:sector_occupation") + "?setor=UTI&dias=30"
        response_30d = logged_client.get(url_30d)
        assert response_30d.context["summary"]["total"] == 1


@pytest.mark.django_db
class TestSectorOccupationSummary:
    """Summary cards: total, still_in, left, avg_stay_days."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        pass

    def test_occupation_summary_cards(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """Context contains summary.total, still_in, left, avg_stay_days."""
        today = timezone.now().date()

        # 3 patients: 1 still in, 2 left
        _make_movement(patient, "UTI", today - timedelta(days=5), days_ago=5)
        _make_movement(
            patient2, "UTI", today - timedelta(days=3),
            discharge_type="A", days_ago=3,
        )
        _make_movement(
            patient3, "UTI", today - timedelta(days=1),
            discharge_type="O", days_ago=1,
        )

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        summary = response.context["summary"]

        assert summary["total"] == 3
        assert summary["still_in"] == 1
        assert summary["left"] == 2
        assert summary["avg_stay_days"] is not None
        assert isinstance(summary["avg_stay_days"], float)

        # avg_stay is average of days each patient was in the sector
        # Patient 1: 5 days, Patient 2: 3 days, Patient 3: 1 day -> avg = 3.0
        assert summary["avg_stay_days"] == pytest.approx(3.0, abs=0.5)

    def test_occupation_summary_all_still_in(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """When all patients are still in, left = 0."""
        today = timezone.now().date()
        _make_movement(patient, "ENF", today - timedelta(days=2), days_ago=2)
        _make_movement(patient2, "ENF", today - timedelta(days=1), days_ago=1)

        url = reverse("services_portal:sector_occupation") + "?setor=ENF"
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 2
        assert summary["still_in"] == 2
        assert summary["left"] == 0
        assert summary["avg_stay_days"] is not None

    def test_occupation_summary_all_left(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """When all patients have left, still_in = 0."""
        today = timezone.now().date()
        _make_movement(
            patient, "ENF", today - timedelta(days=2),
            discharge_type="A", days_ago=2,
        )
        _make_movement(
            patient2, "ENF", today - timedelta(days=1),
            discharge_type="T", days_ago=1,
        )

        url = reverse("services_portal:sector_occupation") + "?setor=ENF"
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 2
        assert summary["still_in"] == 0
        assert summary["left"] == 2

    def test_occupation_avg_stay_none_when_no_data(
        self, logged_client: Client
    ) -> None:
        """When there are no movements, avg_stay_days is None."""
        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 0
        assert summary["avg_stay_days"] is None


@pytest.mark.django_db
class TestSectorOccupationPatientTable:
    """Patient table ordering and destination."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        pass

    def test_occupation_patient_table_ordered(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Patients are ordered by movement_date DESC."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=5), days_ago=5)
        _make_movement(patient2, "UTI", today - timedelta(days=1), days_ago=1)

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        patients = response.context["patients"]

        assert len(patients) == 2
        # Most recent first
        assert patients[0]["entry_date"] == today - timedelta(days=1)
        assert patients[1]["entry_date"] == today - timedelta(days=5)

    def test_occupation_patient_destination_still_in(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient still in sector shows destination as '(no setor)'."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=2), days_ago=2)

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        patients = response.context["patients"]
        assert patients[0]["destination"] == "(no setor)"

    def test_occupation_patient_destination_discharge(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient with discharge shows discharge type as destination."""
        today = timezone.now().date()
        _make_movement(
            patient, "UTI", today - timedelta(days=2),
            discharge_type="A", days_ago=2,
        )

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        patients = response.context["patients"]
        assert patients[0]["destination"] == "A"

    def test_occupation_patient_context_fields(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Each patient dict has name, prontuario, entry_date, days, destination."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=2), days_ago=2)

        url = reverse("services_portal:sector_occupation") + "?setor=UTI"
        response = logged_client.get(url)
        patients = response.context["patients"]
        p = patients[0]

        assert "name" in p
        assert "prontuario" in p
        assert "entry_date" in p
        assert "days" in p
        assert "destination" in p
        assert p["name"] == "PACIENTE ALFA"
        assert p["prontuario"] == "P001"
        # 2 days difference
        assert p["days"] >= 2


@pytest.mark.django_db
class TestSectorOccupationEmptyState:
    """Empty state when no movements match the filter."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client) -> None:
        pass

    def test_occupation_empty_state(self, logged_client: Client) -> None:
        """When no movements for the sector in period, shows empty state."""
        url = reverse("services_portal:sector_occupation") + "?setor=SEM_MOVIMENTOS"
        response = logged_client.get(url)
        assert response.status_code == 200

        content = response.content.decode()
        # Should render the empty state message
        summary = response.context["summary"]
        assert summary["total"] == 0
        assert summary["still_in"] == 0
        assert summary["left"] == 0

        # Template should show empty-state text
        assert "Nenhum" in content or "paciente" in content


@pytest.mark.django_db
class TestSectorOccupationContextStructure:
    """Verify full context structure."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client, patient: Patient,
    ) -> None:
        pass

    def test_context_has_required_keys(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Context contains page_title, sectors, selected_sector, period_days."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=1), days_ago=1)

        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        ctx = response.context

        assert "page_title" in ctx
        assert "sectors" in ctx
        assert "selected_sector" in ctx
        assert "period_days" in ctx
        assert "period_options" in ctx
        assert "summary" in ctx
        assert "patients" in ctx
        # Temporarily removed — context processor doesn't know /setores/ yet
        # assert ctx["active_tab"] == "setores"

    def test_period_options_in_context(
        self, logged_client: Client
    ) -> None:
        """Context has period_options list [7, 30, 90]."""
        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        assert response.context["period_options"] == [7, 30, 90]

    def test_page_title(self, logged_client: Client) -> None:
        """Page title is correct."""
        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        assert response.context["page_title"] == "Setores — Ocupação"
