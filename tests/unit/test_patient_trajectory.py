"""Tests for patient trajectory in admission detail view (Slice PMT-S3)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from apps.census.models import PatientMovement
from apps.patients.models import Admission, Patient

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def client(db: object) -> Client:
    from django.contrib.auth.models import User

    User.objects.create_user(username="testuser", password="testpass")
    c = Client()
    c.login(username="testuser", password="testpass")
    return c


@pytest.fixture
def patient(db: object) -> Patient:
    return Patient.objects.create(
        patient_source_key="P999",
        source_system="tasy",
        name="PACIENTE TESTE",
        date_of_birth=date(1990, 1, 1),
    )


@pytest.fixture
def admission(patient: Patient) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_admission_key="ADM-PMT-S3",
        source_system="tasy",
        admission_date=datetime(2026, 5, 15, 8, 0, tzinfo=TZ),
        ward="ENF PED",
        bed="LEITO-01",
    )


# ---------------------------------------------------------------------------
# Helper to create movements
# ---------------------------------------------------------------------------

def _make_movement(
    patient: Patient,
    sector: str,
    movement_date: date,
    origin: str = "",
    discharge_type: str = "",
    sequence: int = 0,
) -> PatientMovement:
    return PatientMovement.objects.create(
        patient=patient,
        movement_date=movement_date,
        sector=sector,
        origin=origin,
        discharge_type=discharge_type,
        sequence=sequence,
        first_seen_at=datetime(2026, 5, 29, 12, 0, tzinfo=TZ),
        last_seen_at=datetime(2026, 5, 29, 12, 0, tzinfo=TZ),
    )


def _url(patient: Patient) -> str:
    return f"/patients/{patient.pk}/admissions/"


# ---------------------------------------------------------------------------
# Tests — RED phase
# ---------------------------------------------------------------------------


class TestAdmissionViewTrajectory:
    """Verify trajectory context in admission_list_view."""

    def test_admission_view_includes_trajectory_when_movements_exist(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """View context contains 'trajectory' with 2 items when 2 movements exist."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient, "ENF PED", date(2026, 5, 21), origin="PS PED", sequence=1
        )

        resp = client.get(_url(patient))
        assert resp.status_code == 200
        trajectory = resp.context["trajectory"]
        assert len(trajectory) == 2
        assert trajectory[0]["sector"] == "PS PED"
        assert trajectory[1]["sector"] == "ENF PED"

    def test_admission_view_empty_trajectory_when_no_movements(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """Without movements, trajectory is an empty list."""
        resp = client.get(_url(patient))
        assert resp.status_code == 200
        trajectory = resp.context["trajectory"]
        assert trajectory == []

    def test_trajectory_calculates_days_correctly(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """First movement days = diff to next movement. Last active = diff to today."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient, "ENF PED", date(2026, 5, 23), origin="PS PED", sequence=1
        )

        resp = client.get(_url(patient))
        trajectory = resp.context["trajectory"]

        # First: diff between 2026-05-23 and 2026-05-20 = 3 days
        assert trajectory[0]["days"] == 3

        # Last active: diff between today and 2026-05-23
        expected_last = (date.today() - date(2026, 5, 23)).days
        assert trajectory[1]["days"] == max(expected_last, 0)

    def test_trajectory_shows_origin_for_non_first(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """First movement has empty origin; second has origin='PS'."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient, "ENF PED", date(2026, 5, 21), origin="PS PED", sequence=1
        )

        resp = client.get(_url(patient))
        trajectory = resp.context["trajectory"]

        assert trajectory[0]["origin"] == ""
        assert trajectory[1]["origin"] == "PS PED"

    def test_trajectory_active_flag(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """Last movement without discharge_type -> is_active=True; previous -> False."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient, "ENF PED", date(2026, 5, 21), origin="PS PED", sequence=1
        )

        resp = client.get(_url(patient))
        trajectory = resp.context["trajectory"]

        assert trajectory[0]["is_active"] is False
        assert trajectory[1]["is_active"] is True

    def test_trajectory_discharge_closes_trajectory(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """Last movement with discharge_type -> is_active=False."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient,
            "ENF PED",
            date(2026, 5, 21),
            origin="PS PED",
            discharge_type="A",
            sequence=1,
        )

        resp = client.get(_url(patient))
        trajectory = resp.context["trajectory"]

        assert trajectory[1]["is_active"] is False
        assert trajectory[1]["discharge_type"] == "A"

    def test_template_renders_trajectory_html(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """Rendered HTML contains the sector name from the first movement."""
        _make_movement(patient, "PS PED", date(2026, 5, 20), sequence=0)
        _make_movement(
            patient, "ENF PED", date(2026, 5, 21), origin="PS PED", sequence=1
        )

        resp = client.get(_url(patient))
        content = resp.content.decode()

        assert "PS PED" in content
        assert "ENF PED" in content

    def test_template_empty_state_html(
        self, client: Client, patient: Patient, admission: Admission
    ) -> None:
        """Without movements, HTML shows 'ainda nao disponivel' message."""
        resp = client.get(_url(patient))
        content = resp.content.decode()

        # The template uses HTML entities, so check for the text
        # "ainda n&atilde;o dispon&iacute;vel"
        assert "dispon" in content
