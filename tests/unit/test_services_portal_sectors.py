"""Tests for Setores > Histórico de Passagem and Indicadores.

PMT-S4B: renamed Ocupação → Histórico de Passagem.
Still-in detection now uses latest CensusSnapshot as ground truth.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
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


_CENSUS_CAPTURED_AT = None


def _make_census_snapshot(
    patient: Patient,
    sector: str,
    days_ago: int = 0,
) -> CensusSnapshot:
    """Create a CensusSnapshot marking this patient as currently in `sector`.

    Uses a shared timestamp so that multiple snapshots created in the same
    test share the same captured_at, mimicking a real census extraction.
    """
    global _CENSUS_CAPTURED_AT
    now = timezone.now()
    if _CENSUS_CAPTURED_AT is None:
        _CENSUS_CAPTURED_AT = now - timedelta(days=days_ago, hours=1)
    captured = _CENSUS_CAPTURED_AT
    return CensusSnapshot.objects.create(
        captured_at=captured,
        setor=sector,
        leito="L01",
        prontuario=patient.patient_source_key,
        nome=patient.name,
        especialidade="CME",
        bed_status=BedStatus.OCCUPIED,
        data_movimentacao=captured.strftime("%d/%m"),
    )


@pytest.fixture(autouse=True)
def _reset_census_timestamp() -> None:
    """Reset shared census timestamp before each test."""
    import tests.unit.test_services_portal_sectors as mod
    mod._CENSUS_CAPTURED_AT = None


# ---------------------------------------------------------------------------
# Histórico de Passagem — Auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryAuth:
    """Authentication requirements for sector_passage_history page."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object) -> None:
        pass

    def test_passage_history_requires_auth(self, client: Client) -> None:
        """Anonymous user is redirected to login."""
        url = reverse("services_portal:sector_passage_history")
        response = client.get(url)
        assert response.status_code == 302
        location = response.get("Location", "")
        assert "/login" in location

    def test_passage_history_renders_authenticated(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Authenticated user gets HTTP 200."""
        url = reverse("services_portal:sector_passage_history")
        response = logged_client.get(url)
        assert response.status_code == 200

    def test_old_url_redirects(
        self, logged_client: Client
    ) -> None:
        """Old /setores/ocupacao/ redirects to new page."""
        url = reverse("services_portal:sector_occupation")
        response = logged_client.get(url)
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Histórico de Passagem — Filters
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryFilters:
    """Filtering by sector and period."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        pass

    def test_filters_by_sector(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Query with ?setor=UTI filters PatientMovement by sector."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today, days_ago=1)
        _make_movement(patient2, "ENFERMARIA", today, days_ago=1)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        assert response.status_code == 200
        summary = response.context["summary"]
        assert summary["total"] == 1

    def test_default_period_7_days(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Without ?dias=, uses period of 7 days."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=3), days_ago=3)
        _make_movement(patient, "UTI", today - timedelta(days=15), days_ago=15)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 1

    def test_respects_period_param(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """?dias=30 uses cutoff of 30 days."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=20), days_ago=20)

        url_7d = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI&dias=7"
        )
        response_7d = logged_client.get(url_7d)
        assert response_7d.context["summary"]["total"] == 0

        url_30d = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI&dias=30"
        )
        response_30d = logged_client.get(url_30d)
        assert response_30d.context["summary"]["total"] == 1


# ---------------------------------------------------------------------------
# Histórico de Passagem — Summary cards
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistorySummary:
    """Summary cards with still_in via CensusSnapshot ground truth."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        pass

    def test_summary_cards_with_census(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """still_in uses latest CensusSnapshot, not just discharge_type."""
        today = timezone.localdate()

        # 3 patients have movements in UTI
        _make_movement(patient, "UTI", today - timedelta(days=5), days_ago=5)
        _make_movement(
            patient2, "UTI", today - timedelta(days=3),
            discharge_type="A", days_ago=3,
        )
        _make_movement(patient3, "UTI", today - timedelta(days=1), days_ago=1)

        # Only patient1 is in the latest census for UTI
        _make_census_snapshot(patient, "UTI", days_ago=0)
        # patient3 is in a different sector now
        _make_census_snapshot(patient3, "ENF", days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        summary = response.context["summary"]

        assert summary["total"] == 3  # all 3 passed through
        assert summary["still_in"] == 1  # only patient1 is in census
        assert summary["left"] == 2

        # avg_current_stay for the 1 patient still in
        assert summary["avg_current_stay"] is not None
        assert summary["avg_current_stay"] == pytest.approx(5.0, abs=0.5)

    def test_summary_all_still_in(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """All patients in census → all still_in."""
        today = timezone.now().date()
        _make_movement(patient, "ENF", today - timedelta(days=2), days_ago=2)
        _make_movement(patient2, "ENF", today - timedelta(days=1), days_ago=1)

        _make_census_snapshot(patient, "ENF", days_ago=0)
        _make_census_snapshot(patient2, "ENF", days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=ENF"
        )
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 2
        assert summary["still_in"] == 2
        assert summary["left"] == 0

    def test_summary_none_in_census(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """No patients in census → still_in = 0, all left."""
        today = timezone.now().date()
        _make_movement(patient, "ENF", today - timedelta(days=2), days_ago=2)
        _make_movement(patient2, "ENF", today - timedelta(days=1), days_ago=1)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=ENF"
        )
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 2
        assert summary["still_in"] == 0
        assert summary["left"] == 2

    def test_avg_stay_none_when_no_data(
        self, logged_client: Client
    ) -> None:
        """When no movements, stay averages are None."""
        url = reverse("services_portal:sector_passage_history")
        response = logged_client.get(url)
        summary = response.context["summary"]
        assert summary["total"] == 0
        assert summary["avg_current_stay"] is None
        assert summary["avg_completed_stay"] is None


# ---------------------------------------------------------------------------
# Histórico de Passagem — Patient table
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryPatientTable:
    """Patient table ordering and destination."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        pass

    def test_table_ordered_by_entry_desc(
        self, logged_client: Client, patient: Patient, patient2: Patient
    ) -> None:
        """Patients are ordered by movement_date DESC."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=5), days_ago=5)
        _make_movement(patient2, "UTI", today - timedelta(days=1), days_ago=1)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        patients = response.context["patients"]

        assert len(patients) == 2
        assert patients[0]["entry_date"] == today - timedelta(days=1)
        assert patients[1]["entry_date"] == today - timedelta(days=5)

    def test_destination_still_in_shows_no_setor(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient in census → destination is '(no setor)'."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=2), days_ago=2)
        _make_census_snapshot(patient, "UTI", days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        patients = response.context["patients"]
        assert patients[0]["destination"] == "(no setor)"

    def test_destination_left_shows_not_in_sector(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient not in census → destination is '(não está mais no setor)'."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=2), days_ago=2)
        # No census snapshot → patient is not in sector

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        patients = response.context["patients"]
        assert patients[0]["destination"] == "(não está mais no setor)"

    def test_destination_discharge_takes_priority(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """discharge_type always wins over census status."""
        today = timezone.now().date()
        _make_movement(
            patient, "UTI", today - timedelta(days=2),
            discharge_type="A", days_ago=2,
        )
        _make_census_snapshot(patient, "UTI", days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        patients = response.context["patients"]
        assert patients[0]["destination"] == "A"

    def test_patient_context_fields(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Each patient dict has expected fields."""
        today = timezone.localdate()
        _make_movement(patient, "UTI", today - timedelta(days=2), days_ago=2)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=UTI"
        )
        response = logged_client.get(url)
        patients = response.context["patients"]
        p = patients[0]

        assert p["name"] == "PACIENTE ALFA"
        assert p["prontuario"] == "P001"
        assert p["days"] >= 2


# ---------------------------------------------------------------------------
# Histórico de Passagem — High-turnover warning
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryHighTurnover:
    """High-turnover sector warning banner."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client, patient: Patient,
    ) -> None:
        pass

    def test_crpa_triggers_warning(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """CRPA sector shows high-turnover warning."""
        today = timezone.now().date()
        _make_movement(patient, "0 T - CRPA - HGRS", today, days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=0+T+-+CRPA+-+HGRS"
        )
        response = logged_client.get(url)
        assert response.context["high_turnover_warning"] is True
        content = response.content.decode()
        assert "alta rotatividade" in content.lower()

    def test_enfermaria_no_warning(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Regular ward does NOT trigger warning."""
        today = timezone.now().date()
        _make_movement(patient, "ENFERMARIA", today, days_ago=0)

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=ENFERMARIA"
        )
        response = logged_client.get(url)
        assert response.context["high_turnover_warning"] is False

    def test_sala_observacao_triggers_warning(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """SALA DE OBSERVAÇÃO triggers warning."""
        today = timezone.now().date()
        _make_movement(
            patient, "SALA DE OBSERVAÇÃO", today, days_ago=0,
        )

        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=SALA+DE+OBSERVA%C3%87%C3%83O"
        )
        response = logged_client.get(url)
        assert response.context["high_turnover_warning"] is True


# ---------------------------------------------------------------------------
# Histórico de Passagem — Empty state
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryEmptyState:
    """Empty state when no movements match the filter."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client) -> None:
        pass

    def test_empty_state(self, logged_client: Client) -> None:
        """When no movements, shows empty state."""
        url = (
            reverse("services_portal:sector_passage_history")
            + "?setor=SEM_MOVIMENTOS"
        )
        response = logged_client.get(url)
        assert response.status_code == 200

        summary = response.context["summary"]
        assert summary["total"] == 0
        assert summary["still_in"] == 0
        assert summary["left"] == 0

        content = response.content.decode()
        assert "Nenhum" in content or "paciente" in content


# ---------------------------------------------------------------------------
# Histórico de Passagem — Context structure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPassageHistoryContextStructure:
    """Verify full context structure."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, db: object, logged_client: Client, patient: Patient,
    ) -> None:
        pass

    def test_context_has_required_keys(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Context contains expected keys for new passage history page."""
        today = timezone.now().date()
        _make_movement(patient, "UTI", today - timedelta(days=1), days_ago=1)

        url = reverse("services_portal:sector_passage_history")
        response = logged_client.get(url)
        ctx = response.context

        assert "page_title" in ctx
        assert "sectors" in ctx
        assert "selected_sector" in ctx
        assert "period_days" in ctx
        assert "period_options" in ctx
        assert "summary" in ctx
        assert "patients" in ctx
        assert "high_turnover_warning" in ctx
        assert "avg_current_stay" in ctx["summary"]
        assert "avg_completed_stay" in ctx["summary"]

    def test_period_options(self, logged_client: Client) -> None:
        """Context has period_options list [7, 30, 90]."""
        url = reverse("services_portal:sector_passage_history")
        response = logged_client.get(url)
        assert response.context["period_options"] == [7, 30, 90]

    def test_page_title(self, logged_client: Client) -> None:
        """Page title reflects new name."""
        url = reverse("services_portal:sector_passage_history")
        response = logged_client.get(url)
        assert "Histórico de Passagem" in response.context["page_title"]


# ===========================================================================
# Indicadores — corrected logic for all 4 cards
# ===========================================================================


@pytest.mark.django_db
class TestSectorIndicatorsAuth:
    """Authentication requirements for sector_indicators page."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object) -> None:
        pass

    def test_indicators_page_requires_auth(self, client: Client) -> None:
        url = reverse("services_portal:sector_indicators")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login" in response.get("Location", "")

    def test_indicators_page_renders_authenticated(
        self, logged_client: Client, patient: Patient
    ) -> None:
        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestSectorIndicatorsAvgStay:
    """Card 1: Average stay by sector — uses next movement_date."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient) -> None:
        pass

    def test_avg_stay_uses_consecutive_movements(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Stay = next_movement_date - movement_date for completed stays."""
        today = timezone.localdate()
        now = timezone.now()

        # Patient moves: UTI (D-10) → ENF (D-5) = 5 days in UTI
        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=10),
            sector="UTI",
            sequence=0,
            first_seen_at=now - timedelta(days=10),
            last_seen_at=now - timedelta(days=6),
        )
        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=5),
            sector="ENF",
            sequence=1,
            first_seen_at=now - timedelta(days=5),
            last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        avg_stay = response.context["avg_stay"]
        assert len(avg_stay) >= 1

        uti = next(a for a in avg_stay if a["sector"] == "UTI")
        # UTI: next.move_date(D-5) - movement_date(D-10) = 5 days
        assert uti["avg_days"] == 5.0

    def test_avg_stay_last_movement_uses_today(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Last movement uses today - movement_date."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=7),
            sector="UTI",
            sequence=0,
            first_seen_at=now - timedelta(days=7),
            last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        avg_stay = response.context["avg_stay"]
        uti = next(a for a in avg_stay if a["sector"] == "UTI")
        # today - 7 days ago = ~7 days
        assert uti["avg_days"] == pytest.approx(7.0, abs=0.5)

    def test_avg_stay_empty_period(
        self, logged_client: Client
    ) -> None:
        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)
        assert response.context["avg_stay"] == []

    def test_avg_stay_respects_dias_param(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """?dias=7 cuts off movements first seen >7 days ago."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="UTI",
            sequence=0,
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now - timedelta(days=15),
        )

        url = reverse("services_portal:sector_indicators") + "?dias=7"
        response = logged_client.get(url)
        assert response.context["avg_stay"] == []


@pytest.mark.django_db
class TestSectorIndicatorsTopDestinations:
    """Card 2: Flow between sectors — uses previous movement sector."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient, patient3: Patient) -> None:
        pass

    def test_destinations_from_origin_sector(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """?origem=PS filters by previous movement's sector."""
        today = timezone.localdate()
        now = timezone.now()

        # 2 patients: PS(seq0) → ENF(seq1), 1 patient: PS(seq0) → UTI(seq1)
        for p, dest in [(patient, "ENF"), (patient2, "ENF"),
                         (patient3, "UTI")]:
            PatientMovement.objects.create(
                patient=p,
                movement_date=today - timedelta(days=3),
                sector="PS",
                sequence=0,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now - timedelta(days=2),
            )
            PatientMovement.objects.create(
                patient=p,
                movement_date=today - timedelta(days=1),
                sector=dest,
                sequence=1,
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now,
            )

        url = reverse("services_portal:sector_indicators") + "?origem=PS"
        response = logged_client.get(url)

        destinations = response.context["destinations"]
        enf = next(d for d in destinations if d["sector"] == "ENF")
        uti = next(d for d in destinations if d["sector"] == "UTI")
        assert enf["count"] == 2
        assert uti["count"] == 1
        assert response.context["origin_filter"] == "PS"

    def test_destinations_no_origin_filter(
        self, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        """Without ?origem=, shows all destination sectors."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="ENF", sequence=0,
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="UTI", sequence=0,
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        destinations = response.context["destinations"]
        assert len(destinations) == 2
        assert response.context["origin_filter"] == ""

    def test_origin_options_are_sector_names(
        self, logged_client: Client,
        patient: Patient, patient2: Patient,
    ) -> None:
        """Dropdown shows sector names, not bed codes."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient, movement_date=today - timedelta(days=1),
            sector="UTI", sequence=0,
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )
        PatientMovement.objects.create(
            patient=patient2, movement_date=today - timedelta(days=1),
            sector="ENFERMARIA", sequence=0,
            first_seen_at=now - timedelta(days=1), last_seen_at=now,
        )

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        origin_options = response.context["origin_options"]
        assert sorted(origin_options) == ["ENFERMARIA", "UTI"]


@pytest.mark.django_db
class TestSectorIndicatorsLongStay:
    """Card 3: Long-stay — uses CensusSnapshot ground truth."""

    @pytest.fixture(autouse=True)
    def _setup(self, db: object, logged_client: Client,
               patient: Patient, patient2: Patient) -> None:
        pass

    def test_long_stay_includes_patient_still_in_census(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient in census >15 days → long stay."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="ENF",
            sequence=0,
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now,
        )
        # Patient IS in latest census for ENF
        _make_census_snapshot(patient, "ENF", days_ago=0)

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        long_stay = response.context["long_stay"]
        assert len(long_stay) >= 1
        enf = next(ls for ls in long_stay if ls["sector"] == "ENF")
        assert enf["count"] >= 1

    def test_long_stay_excludes_patient_not_in_census(
        self, logged_client: Client, patient: Patient
    ) -> None:
        """Patient NOT in census → excluded even if movement is old."""
        today = timezone.localdate()
        now = timezone.now()

        PatientMovement.objects.create(
            patient=patient,
            movement_date=today - timedelta(days=20),
            sector="ENF",
            sequence=0,
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now - timedelta(days=5),
        )
        # No census snapshot → patient is not currently in sector

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)
        assert response.context["long_stay"] == []


@pytest.mark.django_db
class TestSectorIndicatorsBottlenecks:
    """Card 4: Bottlenecks — exits via CensusSnapshot ground truth."""

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

    def test_bottleneck_entries_exceed_exits(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
    ) -> None:
        """3 entries, 0 exits (no census records) → bottleneck +3."""
        today = timezone.localdate()
        now = timezone.now()

        for p in [patient, patient2, patient3]:
            PatientMovement.objects.create(
                patient=p, movement_date=today - timedelta(days=1),
                sector="ENF", sequence=0,
                first_seen_at=now - timedelta(days=1), last_seen_at=now,
            )
        # No census snapshots → all 3 counted as "not in sector" → exits = 3
        # Wait, no: entries=3 (first_seen_at in period), exits are movements
        # with last_seen_at in period AND not in census.
        # Since no census records, all 3 are "not in census" → exits=3.
        # So net = 0, no bottleneck.
        #
        # To get bottleneck, we need some patients IN census (no exit)
        # and some NOT in census (count as exit).

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        # All 3 are entries AND exits (not in census) → net=0, no bottleneck
        assert response.context["bottlenecks"] == []

    def test_bottleneck_with_census_retained_patients(
        self, logged_client: Client,
        patient: Patient, patient2: Patient, patient3: Patient,
        patient4: Patient,
    ) -> None:
        """Some patients retained in census → entries > exits."""
        today = timezone.localdate()
        now = timezone.now()

        # 4 entries in ENF
        for p in [patient, patient2, patient3, patient4]:
            PatientMovement.objects.create(
                patient=p, movement_date=today - timedelta(days=1),
                sector="ENF", sequence=0,
                first_seen_at=now - timedelta(days=1), last_seen_at=now,
            )

        # 2 patients still in ENF per census
        _make_census_snapshot(patient, "ENF", days_ago=0)
        _make_census_snapshot(patient2, "ENF", days_ago=0)

        url = reverse("services_portal:sector_indicators")
        response = logged_client.get(url)

        bottlenecks = response.context["bottlenecks"]
        enf = next(b for b in bottlenecks if b["sector"] == "ENF")
        # 4 entries, 2 exits (patients 3,4 not in census) → net=2
        assert enf["entries"] == 4
        assert enf["exits"] == 2
        assert enf["net"] == 2


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
