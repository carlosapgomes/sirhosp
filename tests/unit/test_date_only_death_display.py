"""Date-only death closures never render an hour (DD-S2 R6).

A D 00:00 ``America/Bahia`` carrier bears the local date only: every
surface that renders the exit of a date-only death closure shows the
date alone, never ``00:00`` as if it were source information. Full
datetime exits keep rendering date and hour (regression control).

All fixtures are synthetic.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

from apps.deaths.models import DeathRecord
from apps.deaths.services import reconcile_death_record
from apps.patients.admin import AdmissionAdmin, ReconciliationEventAdmin
from apps.patients.models import (
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)
from apps.patients.reconciliation import reverse_reconciliation

TZ_LOCAL = ZoneInfo("America/Bahia")


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_open_admission(patient: Patient, key: str) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=datetime(2026, 5, 20, 8, 0, tzinfo=TZ_LOCAL),
    )


def _close_by_date_only_death(
    prontuario: str, *, data_obito: str = "01/06/2026"
) -> tuple[Patient, Admission, DeathRecord]:
    patient = _make_patient(prontuario)
    admission = _make_open_admission(patient, f"ADM-{prontuario}")
    record = DeathRecord.objects.create(
        date=date(2026, 6, 1),
        prontuario=prontuario,
        nome=f"PACIENTE {prontuario}",
        data_obito=data_obito,
    )
    assert reconcile_death_record(record=record) == (
        RECONCILIATION_STATUS_RECONCILED
    )
    admission.refresh_from_db()
    return patient, admission, record


@pytest.fixture
def auth_client(db: None) -> Client:
    User.objects.create_user(username="operador", password="testpass123")
    client = Client()
    client.login(username="operador", password="testpass123")
    return client


@pytest.fixture
def reviewer_client(db: None) -> Client:
    user = User.objects.create_user(username="revisor", password="testpass123")
    permission = Permission.objects.get(
        codename="review_reconciliation_cases",
        content_type__app_label="patients",
    )
    user.user_permissions.add(permission)
    client = Client()
    client.login(username="revisor", password="testpass123")
    return client


@pytest.mark.django_db
class TestDateOnlyExitBadgesShowDateOnly:
    def test_admission_page_hides_carrier_hour(self, auth_client: Client):
        patient, admission, _ = _close_by_date_only_death("DSP-1")

        response = auth_client.get(
            reverse("patients:admission_list", args=[patient.pk])
            + f"?admission_id={admission.pk}"
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert "01/06/2026" in html
        assert "01/06/2026 00:00" not in html

    def test_admission_page_keeps_datetime_hour(
        self, auth_client: Client
    ):
        """Control: a real datetime exit still renders date and hour."""
        patient, admission, _ = _close_by_date_only_death(
            "DSP-2", data_obito="01/06/2026 12:00"
        )

        response = auth_client.get(
            reverse("patients:admission_list", args=[patient.pk])
            + f"?admission_id={admission.pk}"
        )

        assert response.status_code == 200
        assert "01/06/2026 12:00" in response.content.decode()

    def test_timeline_header_hides_carrier_hour(self, auth_client: Client):
        _, admission, _ = _close_by_date_only_death("DSP-3")

        response = auth_client.get(
            reverse("patients:timeline", args=[admission.pk])
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert "01/06/2026" in html
        assert "01/06/2026 00:00" not in html

    def test_pending_items_banner_hides_carrier_hour(
        self, auth_client: Client
    ):
        _, admission, _ = _close_by_date_only_death("DSP-4")

        response = auth_client.get(
            reverse("pending_items:admission_items", args=[admission.pk])
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert "01/06/2026" in html
        assert "01/06/2026 00:00" not in html


@pytest.mark.django_db
class TestReviewDetailHidesCarrierHour:
    def test_death_evidence_detail_hides_carrier_hour(
        self, reviewer_client: Client
    ):
        _, _, record = _close_by_date_only_death("DSP-5")

        response = reviewer_client.get(
            reverse(
                "services_portal:reconciliation_evidence_detail",
                args=["obito", record.pk],
            )
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert "01/06/2026" in html
        assert "01/06/2026 00:00" not in html

    def test_death_evidence_detail_keeps_datetime_hour(
        self, reviewer_client: Client
    ):
        """Control: a real datetime death still renders date and hour."""
        _, _, record = _close_by_date_only_death(
            "DSP-6", data_obito="01/06/2026 12:00"
        )

        response = reviewer_client.get(
            reverse(
                "services_portal:reconciliation_evidence_detail",
                args=["obito", record.pk],
            )
        )

        assert response.status_code == 200
        assert "01/06/2026 12:00" in response.content.decode()


@pytest.mark.django_db
class TestAdminDisplayDateOnly:
    """Staff admin renders date-only closures without the carrier hour."""

    def _admission_admin(self) -> AdmissionAdmin:
        from django.contrib.admin.sites import AdminSite

        return AdmissionAdmin(Admission, AdminSite())

    def _event_admin(self) -> ReconciliationEventAdmin:
        from django.contrib.admin.sites import AdminSite

        return ReconciliationEventAdmin(ReconciliationEvent, AdminSite())

    def test_admission_admin_hides_carrier_hour(self):
        _, admission, _ = _close_by_date_only_death("ADM-1")

        rendered = self._admission_admin().display_discharge_date(admission)

        assert rendered == "01/06/2026 (data)"

    def test_admission_admin_keeps_datetime_hour(self):
        """Control: a real datetime exit still renders date and hour."""
        _, admission, _ = _close_by_date_only_death(
            "ADM-2", data_obito="01/06/2026 12:00"
        )

        rendered = self._admission_admin().display_discharge_date(admission)

        assert rendered == "01/06/2026 12:00"

    def test_event_admin_hides_carrier_hour_on_new_side(self):
        _, admission, _ = _close_by_date_only_death("ADM-3")
        event = ReconciliationEvent.objects.get(
            admission_id=admission.pk,
            status=RECONCILIATION_STATUS_RECONCILED,
        )
        event_admin = self._event_admin()

        assert event_admin.display_new_discharge_date(event) == (
            "01/06/2026 (data)"
        )
        assert event_admin.display_prior_discharge_date(event) == "-"

    def test_event_admin_keeps_datetime_hour_on_new_side(self):
        """Control: a real datetime exit still renders date and hour."""
        _, admission, _ = _close_by_date_only_death(
            "ADM-4", data_obito="01/06/2026 12:00"
        )
        event = ReconciliationEvent.objects.get(
            admission_id=admission.pk,
            status=RECONCILIATION_STATUS_RECONCILED,
        )

        rendered = self._event_admin().display_new_discharge_date(event)

        assert rendered == "01/06/2026 12:00"

    def test_event_admin_hides_carrier_hour_on_rollback_prior(self):
        _, admission, _ = _close_by_date_only_death("ADM-5")
        event = ReconciliationEvent.objects.get(
            admission_id=admission.pk,
            status=RECONCILIATION_STATUS_RECONCILED,
        )

        inverse = reverse_reconciliation(event=event)

        assert self._event_admin().display_prior_discharge_date(inverse) == (
            "01/06/2026 (data)"
        )

    def test_list_display_wires_precision_aware_columns(self):
        assert "discharge_date" not in AdmissionAdmin.list_display
        assert (
            "display_discharge_date" in AdmissionAdmin.list_display
        )
        assert "prior_discharge_date" not in (
            ReconciliationEventAdmin.list_display
        )
        assert "new_discharge_date" not in ReconciliationEventAdmin.list_display
        assert (
            "display_prior_discharge_date"
            in ReconciliationEventAdmin.list_display
        )
        assert (
            "display_new_discharge_date" in ReconciliationEventAdmin.list_display
        )
