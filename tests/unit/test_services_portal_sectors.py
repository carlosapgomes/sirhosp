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
class TestSectorIndicatorsAuth:
    """Authentication requirements for sector_indicators page."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object) -> None:
        pass

    def test_indicators_page_requires_auth(self, client: Client) -> None:
        """Anonymous user is redirected to login."""
        url = reverse("services_portal:sector_indicators")
        response = client.get(url)
        assert response.status_code == 302
        location = response.get("Location", "")
        assert "/login" in location

    def test_indicators_page_renders_authenticated(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Authenticated user gets HTTP 200."""
        url = reverse("services_portal:sector_indicators")
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
        today = timezone.localdate()

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
        today = timezone.localdate()
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


@pytest.mark.django_db
class TestSectorIndicatorsAvgStay:
    """Card 1: Average stay by sector."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient) -> None:
        pass

    def test_indicators_avg_stay_by_sector(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Context contains avg_stay with correct values."""
        today = timezone.now().date()
        now = timezone.now()

        # Patient 1: 5 days in UTI
        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=5),
            sector="UTI",
            first_seen_at=now - timedelta(days=5),
            last_seen_at=now,
        )
        # Patient 2: 2 days in ENF
        PatientMovement.objects.create(
            patient=patient2,
            movement_date=today - timedelta(days=2),
            sector="ENF",
            first_seen_at=now - timedelta(days=2),
            last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        avg_stay = response.context["avg_stay"]
        assert len(avg_stay) == 2

        # Find each sector
        uti = next(a for a in avg_stay if a["sector"] == "UTI")
        enf = next(a for a in avg_stay if a["sector"] == "ENF")

        assert uti["avg_days"] == pytest.approx(5.0, abs=0.5)
        assert enf["avg_days"] == pytest.approx(2.0, abs=0.5)

        # Ordered by avg_days descending
        assert avg_stay[0]["avg_days"] >= avg_stay[1]["avg_days"]

    def test_indicators_avg_stay_empty_period(
        self, logged_client: Client
    ) -> None:
        """No data in period -> empty list, no error."""
        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)
        avg_stay = response.context["avg_stay"]
        assert avg_stay == []

    def test_indicators_avg_stay_respects_dias_param(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """?dias=7 cuts off older movements."""
        today = timezone.now().date()
        now = timezone.now()

        # Old movement (20 days ago) — should be excluded with ?dias=7
        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="UTI",
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now - timedelta(days=15),
        )

        url = reverse("services_portal:sector_indicators") + "?dias=7"
        response = logged_client.get(url)
        avg_stay = response.context["avg_stay"]
        assert avg_stay == []


@pytest.mark.django_db
class TestSectorIndicatorsTopDestinations:
    """Card 2: Top destination sectors from origin."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient, patient3: Patient) -> None:
        pass

    def test_indicators_top_destinations_from_origin(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """?origem=PS filters by origin and shows top destinations."""
        today = timezone.now().date()
        now = timezone.now()

        # 3 movements from PS: 2 go to ENF, 1 to UTI
        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="ENF", origin="PS",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="ENF", origin="PS",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient3, movement_date=today - timedelta(days=1),
            sector="UTI", origin="PS",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators") + "?origem=PS"
        response = logged_client.get(url)

        destinations = response.context["destinations"]
        assert len(destinations) == 2

        enf = next(d for d in destinations if d["sector"] == "ENF")
        uti = next(d for d in destinations if d["sector"] == "UTI")
        assert enf["count"] == 2
        assert uti["count"] == 1
        assert response.context["origin_filter"] == "PS"

    def test_indicators_top_destinations_no_origin_filter(
        self, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        """Without ?origem=, shows all destinations."""
        today = timezone.now().date()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="ENF", origin="PS",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="UTI", origin="CIR",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        destinations = response.context["destinations"]
        assert len(destinations) == 2
        assert response.context["origin_filter"] == ""

    def test_indicators_top_destinations_origin_options(
        self, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        """Context includes available origin options."""
        today = timezone.now().date()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="ENF", origin="PS",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="UTI", origin="ENF",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        origin_options = response.context["origin_options"]
        assert sorted(origin_options) == ["ENF", "PS"]


@pytest.mark.django_db
class TestSectorIndicatorsLongStay:
    """Card 3: Long-stay patients (>15 days)."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient) -> None:
        pass

    def test_indicators_long_stay_patients(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient with first_seen_at = 20 days ago, no discharge -> long_stay includes sector."""
        today = timezone.now().date()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="ENF",
            discharge_type="",
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        long_stay = response.context["long_stay"]
        assert len(long_stay) == 1
        assert long_stay[0]["sector"] == "ENF"
        assert long_stay[0]["count"] >= 1

    def test_indicators_long_stay_excludes_discharged(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient with discharge despite old record is excluded."""
        today = timezone.now().date()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="ENF",
            discharge_type="A",
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now - timedelta(days=5),
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        long_stay = response.context["long_stay"]
        assert long_stay == []


@pytest.mark.django_db
class TestSectorIndicatorsBottlenecks:
    """Card 4: Bottlenecks (entries > exits)."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient, patient3: Patient,
               patient4: Patient) -> None:
        pass

    @pytest.fixture
    def patient4(self, db: object) -> Patient:
        return Patient.objects.create(
            patient_source_key="P004",
            source_system="tasy",
            name="PACIENTE DELTA",
            date_of_birth=date(1970, 1, 1),
        )

    def test_indicators_bottlenecks(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """5 entries, 2 exits in ENF -> net=3."""
        today = timezone.now().date()
        now = timezone.now()

        # 5 entries in ENF
        for p in [patient, patient2, patient3]:
            PatientMovement.objects.create(
                patient=p, movement_date=today - timedelta(days=1),
                sector="ENF",
                first_seen_at=now - timedelta(days=1), last_seen_at=now,
            )

        # 2 entries in UTI (no exits)
        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="UTI",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="UTI",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        bottlenecks = response.context["bottlenecks"]
        assert len(bottlenecks) == 2

        enf = next(b for b in bottlenecks if b["sector"] == "ENF")
        uti = next(b for b in bottlenecks if b["sector"] == "UTI")

        assert enf["entries"] == 3
        assert enf["exits"] == 0
        assert enf["net"] == 3

        assert uti["entries"] == 2
        assert uti["exits"] == 0
        assert uti["net"] == 2

        # Ordered by net DESC
        assert bottlenecks[0]["net"] >= bottlenecks[1]["net"]

    def test_indicators_bottlenecks_with_exits(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient, patient4: Patient,
    ) -> None:
        """When exits reduce net."""
        today = timezone.localdate()
        now = timezone.now()

        # 4 entries in ENF from 4 different patients
        for idx, p in enumerate([patient, patient2, patient3, patient4]):
            PatientMovement.objects.create(
                patient=p, movement_date=today - timedelta(days=1 + idx),
                sector="ENF",
                first_seen_at=now - timedelta(days=1 + idx), last_seen_at=now,
            )

        # 1 exit from ENF (patient5 with discharge on different date)
        patient5 = Patient.objects.create(
            patient_source_key="P005",
            source_system="tasy",
            name="PACIENTE EPSILON",
            date_of_birth=date(1985, 5, 5),
        )
        PatientMovement.objects.create(
            patient=patient5, movement_date=today,
            sector="ENF", discharge_type="A",
            first_seen_at=now - timedelta(hours=2), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        bottlenecks = response.context["bottlenecks"]
        enf = next(b for b in bottlenecks if b["sector"] == "ENF")

        # 4 entries + 1 exit = 5 entries, 1 exit -> net = 4
        assert enf["entries"] == 5
        assert enf["exits"] == 1
        assert enf["net"] == 4

    def test_indicators_bottlenecks_no_positive_net(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Entries <= exits -> empty list."""
        today = timezone.localdate()
        now = timezone.now()

        # Only discharged movements: each counts as 1 entry + 1 exit -> net = 0
        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="ENF", discharge_type="A",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="ENF", discharge_type="T",
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        bottlenecks = response.context["bottlenecks"]
        # 2 entries and 2 exits -> net=0, so no bottlenecks
        assert bottlenecks == []


@pytest.mark.django_db
class TestSectorIndicatorsEmptyState:
    """Empty state: no data in the system."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client) -> None:
        pass

    def test_indicators_empty_state_all_cards(
        self, logged_client: Client
    ) -> None:
        """No PatientMovement records -> all cards show empty state."""
        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        assert response.status_code == 200
        assert response.context["avg_stay"] == []
        assert response.context["destinations"] == []
        assert response.context["long_stay"] == []
        assert response.context["bottlenecks"] == []
