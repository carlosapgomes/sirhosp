"""PEND-S1: HTTP integration for the contextual pending-items surface.

Covers R2 (episode-scoped page, eligibility blocks with the exact
message), R3 (group-only writes over HTTP, anonymous redirect), R4 (forms,
conflicts, no System impersonation) and R5 (read-only history, cache
headers, admin catalog guards, no clinical payload in logs).

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    INELIGIBLE_MESSAGE,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)

TZ = ZoneInfo("America/Bahia")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None = "2026-06-01T08:00:00",
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start) if start else None,
        discharge_date=_dt(end) if end else None,
    )


def _make_census_row(
    prontuario: str,
    *,
    setor: str = "CLINICA MEDICA",
    leito: str = "L01",
    captured_at: str = "2026-06-10T08:00:00",
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=_dt(captured_at),
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        bed_status=BedStatus.OCCUPIED,
    )


@pytest.fixture
def group_name(db: object) -> Group:
    return Group.objects.get(name="Desospitalização")


@pytest.fixture
def writer_client(client: Client, db: object) -> Client:
    user = User.objects.create_user(username="http_writer", password="pw123456")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    client.login(username="http_writer", password="pw123456")
    return client


@pytest.fixture
def reader_client(client: Client, db: object) -> Client:
    User.objects.create_user(username="http_reader", password="pw123456")
    client.login(username="http_reader", password="pw123456")
    return client


def _eligible_admission(key: str = "P_HTTP_1") -> Admission:
    patient = _make_patient(key)
    admission = _make_admission(patient, f"ADM_{key}")
    _make_census_row(key)
    return admission


def _cache_directives(response) -> set[str]:
    header = response.headers.get("Cache-Control", "")
    return {part.strip().lower() for part in header.split(",") if part.strip()}


def _assert_private_no_store(response) -> None:
    directives = _cache_directives(response)
    assert "private" in directives
    assert "no-store" in directives


@pytest.mark.django_db
class TestContextualPage:
    def test_eligible_page_lists_only_selected_episode(
        self, writer_client: Client
    ) -> None:
        current = _eligible_admission("P_HTTP_LIST")
        old = _make_admission(
            current.patient, "ADM_HTTP_LIST_OLD", end="2026-05-02T10:00:00"
        )
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        PendingItem.objects.create(
            admission=current,
            item_type=outro,
            description="pendencia do episodio atual",
            status=STATUS_ACTIVE,
            version=1,
        )
        PendingItem.objects.create(
            admission=old,
            item_type=outro,
            description="pendencia do episodio antigo",
            status=STATUS_ACTIVE,
            version=1,
        )
        response = writer_client.get(f"/admissions/{current.pk}/pending-items/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "pendencia do episodio atual" in content
        assert "pendencia do episodio antigo" not in content
        assert current.patient.name in content

    def test_old_episode_is_read_only(
        self, writer_client: Client
    ) -> None:
        current = _eligible_admission("P_HTTP_OLD")
        old = _make_admission(
            current.patient, "ADM_HTTP_OLD_OLD", end="2026-05-02T10:00:00"
        )
        response = writer_client.get(f"/admissions/{old.pk}/pending-items/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "pendencia do episodio atual" not in content
        assert 'name="description"' not in content

    def test_absent_census_shows_exact_message(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_HTTP_ABS")
        admission = _make_admission(patient, "ADM_HTTP_ABS")
        response = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/"
        )
        assert response.status_code == 200
        assert INELIGIBLE_MESSAGE in response.content.decode()

    def test_reader_sees_no_write_actions(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_READ")
        response = reader_client.get(
            f"/admissions/{admission.pk}/pending-items/"
        )
        assert response.status_code == 200
        assert 'name="description"' not in response.content.decode()

    def test_anonymous_redirected_to_login(self, client: Client) -> None:
        admission = _eligible_admission("P_HTTP_ANON")
        response = client.get(f"/admissions/{admission.pk}/pending-items/")
        assert response.status_code == 302
        assert "/login/" in response.url  # type: ignore[attr-defined]
        history_response = client.get(
            f"/admissions/{admission.pk}/pending-items/1/history/"
        )
        assert history_response.status_code == 302
        assert "/login/" in history_response.url  # type: ignore[attr-defined]
        # login_required runs before the item lookup, so even a missing
        # item redirects instead of leaking existence via 404.
        for surface in ("edit", "finalize"):
            surface_response = client.get(
                f"/admissions/{admission.pk}/pending-items/999/{surface}/"
            )
            assert surface_response.status_code == 302
            assert "/login/" in surface_response.url  # type: ignore[attr-defined]

    def test_reinterned_old_episode_never_redirects_write(
        self, writer_client: Client
    ) -> None:
        current = _eligible_admission("P_HTTP_REINT")
        old = _make_admission(
            current.patient, "ADM_HTTP_REINT_OLD", end="2026-05-02T10:00:00"
        )
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        before = Admission.objects.count()
        response = writer_client.post(
            f"/admissions/{old.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "no episodio antigo"},
        )
        assert response.status_code == 403
        assert PendingItem.objects.count() == 0
        assert Admission.objects.count() == before
        current_response = writer_client.post(
            f"/admissions/{current.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "no episodio atual"},
        )
        assert current_response.status_code == 302
        item = PendingItem.objects.get()
        assert item.admission_id == current.pk

    def test_admission_page_links_to_pending_items(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_LINK")
        response = writer_client.get(
            f"/patients/{admission.patient_id}/admissions/"
            f"?admission_id={admission.pk}"
        )
        assert response.status_code == 200
        expected = f"/admissions/{admission.pk}/pending-items/"
        assert expected in response.content.decode()


@pytest.mark.django_db
class TestWriteEndpoints:
    def test_create_post_ok(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_HTTP_W1")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "nova pendencia http"},
        )
        assert response.status_code == 302
        item = PendingItem.objects.get(admission=admission)
        assert item.description == "nova pendencia http"
        assert item.version == 1

    def test_create_post_denied_for_reader(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_W2")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = reader_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "tentativa de leitor"},
        )
        assert response.status_code == 403
        assert PendingItem.objects.count() == 0

    def test_create_post_denied_for_superuser_without_group(
        self, client: Client, db: object
    ) -> None:
        User.objects.create_superuser(
            username="http_admin", password="pw123456", email=""
        )
        client.login(username="http_admin", password="pw123456")
        admission = _eligible_admission("P_HTTP_W3")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "tentativa admin"},
        )
        assert response.status_code == 403
        assert PendingItem.objects.count() == 0

    def test_create_post_blocked_without_census(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_HTTP_W4")
        admission = _make_admission(patient, "ADM_HTTP_W4")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "sem censo"},
        )
        assert response.status_code == 403
        assert INELIGIBLE_MESSAGE in response.content.decode()
        assert PendingItem.objects.count() == 0

    def test_create_post_blocked_with_conflicting_census(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_HTTP_W4B")
        admission = _make_admission(patient, "ADM_HTTP_W4B")
        _make_census_row("P_HTTP_W4B", setor="UTI", leito="U01")
        _make_census_row("P_HTTP_W4B", setor="ENFERMARIA", leito="E02")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        before = Admission.objects.count()
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "censo conflitante"},
        )
        assert response.status_code == 403
        assert INELIGIBLE_MESSAGE in response.content.decode()
        assert PendingItem.objects.count() == 0
        assert Admission.objects.count() == before

    def test_create_post_blocked_with_two_open_admissions(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_HTTP_W4C")
        admission = _make_admission(patient, "ADM_HTTP_W4C_A")
        _make_admission(patient, "ADM_HTTP_W4C_B")
        _make_census_row("P_HTTP_W4C")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "duas abertas"},
        )
        assert response.status_code == 403
        assert INELIGIBLE_MESSAGE in response.content.decode()
        assert PendingItem.objects.count() == 0

    def test_edit_post_on_old_episode_is_blocked(
        self, writer_client: Client
    ) -> None:
        current = _eligible_admission("P_HTTP_W4D")
        old = _make_admission(
            current.patient, "ADM_HTTP_W4D_OLD", end="2026-05-02T10:00:00"
        )
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=old,
            item_type=outro,
            description="texto antigo",
            status=STATUS_ACTIVE,
            version=1,
        )
        response = writer_client.post(
            f"/admissions/{old.pk}/pending-items/{item.pk}/edit/",
            {
                "item_type": str(outro.pk),
                "description": "tentativa tardia",
                "expected_version": "1",
            },
        )
        assert response.status_code == 403
        item.refresh_from_db()
        assert item.description == "texto antigo"
        assert item.version == 1

    def test_create_post_ignores_system_impersonation(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_W5")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {
                "item_type": str(outro.pk),
                "description": "sem impersonacao",
                "is_system": "1",
                "author": "system",
            },
        )
        assert response.status_code == 302
        item = PendingItem.objects.get(admission=admission)
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.is_system is False
        assert revision.author_name == "http_writer"

    def test_create_requires_csrf(self, db: object) -> None:
        admission = _eligible_admission("P_HTTP_W6")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        csrf_client = Client(enforce_csrf_checks=True)
        user = User.objects.create_user(
            username="http_csrf", password="pw123456"
        )
        Group.objects.get(name="Desospitalização").user_set.add(user)
        csrf_client.login(username="http_csrf", password="pw123456")
        response = csrf_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "sem csrf"},
        )
        assert response.status_code == 403
        assert PendingItem.objects.count() == 0

    def test_edit_post_with_stale_version_conflicts(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_W7")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="original",
            status=STATUS_ACTIVE,
            version=2,
        )
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/edit/",
            {
                "item_type": str(outro.pk),
                "description": "envio antigo",
                "expected_version": "1",
            },
        )
        assert response.status_code == 409
        item.refresh_from_db()
        assert item.description == "original"
        assert item.version == 2

    def test_edit_post_on_finalized_is_rejected(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_W8")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="finalizada",
            status=STATUS_RESOLVED,
            version=2,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/edit/",
            {
                "item_type": str(outro.pk),
                "description": "tentativa tardia",
                "expected_version": "2",
            },
        )
        assert response.status_code == 400
        item.refresh_from_db()
        assert item.description == "finalizada"

    def test_finalize_post_ok(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_HTTP_W9")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="a finalizar",
            status=STATUS_ACTIVE,
            version=1,
        )
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/finalize/",
            {
                "target_status": STATUS_CLOSED_UNRESOLVED,
                "note": "",
                "expected_version": "1",
            },
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        assert item.description == "a finalizar"


@pytest.mark.django_db
class TestHistorySurface:
    def test_history_lists_versions_deterministically(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_H1")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="texto-versao-dois",
            status=STATUS_ACTIVE,
            version=2,
        )
        PendingItemRevision.objects.create(
            item=item,
            version=1,
            action="created",
            item_type=outro,
            type_name=outro.name,
            description="texto-versao-um",
            status=STATUS_ACTIVE,
        )
        PendingItemRevision.objects.create(
            item=item,
            version=2,
            action="updated",
            item_type=outro,
            type_name=outro.name,
            description="texto-versao-dois",
            status=STATUS_ACTIVE,
        )
        response = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"
        )
        assert response.status_code == 200
        content = response.content.decode()
        first = content.index("texto-versao-um")
        assert first < content.index("texto-versao-dois", first + 1)
        assert "delete" not in content.lower() or 'name="delete"' not in content

    def test_reader_can_view_history(self, reader_client: Client) -> None:
        admission = _eligible_admission("P_HTTP_H2")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="leitura de historico",
            status=STATUS_ACTIVE,
            version=1,
        )
        response = reader_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"
        )
        assert response.status_code == 200
        assert "leitura de historico" in response.content.decode()


@pytest.mark.django_db
class TestClinicalEscaping:
    def test_description_html_is_escaped_on_page_and_history(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_ESC")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        marker = "XSS-SINTETICO-9917"
        description = f"{marker}<script>alert('pend')</script>"
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description=description,
            status=STATUS_ACTIVE,
            version=1,
        )
        page = writer_client.get(f"/admissions/{admission.pk}/pending-items/")
        assert page.status_code == 200
        page_content = page.content.decode()
        assert marker in page_content
        assert "&lt;script&gt;" in page_content
        assert "<script>alert" not in page_content
        history = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"
        )
        assert history.status_code == 200
        history_content = history.content.decode()
        assert marker in history_content
        assert "&lt;script&gt;" in history_content
        assert "<script>alert" not in history_content


@pytest.mark.django_db
class TestCacheHeaders:
    def test_page_form_history_and_error_are_private_no_store(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_HTTP_CACHE")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="cache",
            status=STATUS_ACTIVE,
            version=1,
        )
        page = writer_client.get(f"/admissions/{admission.pk}/pending-items/")
        assert page.status_code == 200
        _assert_private_no_store(page)

        form = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/edit/"
        )
        assert form.status_code == 200
        _assert_private_no_store(form)

        finalize_form = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/finalize/"
        )
        assert finalize_form.status_code == 200
        _assert_private_no_store(finalize_form)

        history = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"
        )
        assert history.status_code == 200
        _assert_private_no_store(history)

        error = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/",
            {"item_type": str(outro.pk), "description": "   "},
        )
        assert error.status_code == 200
        _assert_private_no_store(error)


@pytest.mark.django_db
class TestAdminCatalog:
    def _admin_client(self, client: Client) -> Client:
        User.objects.create_superuser(
            username="catalog_admin", password="pw123456", email=""
        )
        client.login(username="catalog_admin", password="pw123456")
        return client

    def test_admin_can_add_type(self, client: Client) -> None:
        admin_client = self._admin_client(client)
        response = admin_client.post(
            "/admin/pending_items/pendingitemtype/add/",
            {"name": "Transporte", "slug": "transporte"},
        )
        assert response.status_code == 302
        assert PendingItemType.objects.filter(slug="transporte").exists()

    def test_admin_cannot_rename_outro(self, client: Client) -> None:
        admin_client = self._admin_client(client)
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = admin_client.post(
            f"/admin/pending_items/pendingitemtype/{outro.pk}/change/",
            {"name": "Renamed", "slug": outro.slug},
        )
        assert response.status_code == 200
        outro.refresh_from_db()
        assert outro.name == "Outro"

    def test_admin_cannot_delete_outro(self, client: Client) -> None:
        admin_client = self._admin_client(client)
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        response = admin_client.post(
            f"/admin/pending_items/pendingitemtype/{outro.pk}/delete/",
            {"post": "yes"},
        )
        assert response.status_code in (200, 403)
        assert PendingItemType.objects.filter(slug=OUTRO_SLUG).exists()

    def test_admin_cannot_delete_referenced_type(
        self, client: Client
    ) -> None:
        admin_client = self._admin_client(client)
        admission = _eligible_admission("P_HTTP_ADM")
        item_type = PendingItemType.objects.create(
            slug="admref", name="Referenciado"
        )
        PendingItem.objects.create(
            admission=admission,
            item_type=item_type,
            description="referencia",
            status=STATUS_ACTIVE,
            version=1,
        )
        response = admin_client.post(
            f"/admin/pending_items/pendingitemtype/{item_type.pk}/delete/",
            {"post": "yes"},
        )
        assert response.status_code == 200
        assert PendingItemType.objects.filter(slug="admref").exists()

    def test_items_and_revisions_have_no_admin_crud(
        self, db: object
    ) -> None:
        from django.contrib import admin

        registered = {
            model.__name__ for model in admin.site._registry
        }
        assert "PendingItem" not in registered
        assert "PendingItemRevision" not in registered


@pytest.mark.django_db
class TestClinicalPayloadHygiene:
    def test_services_emit_no_clinical_logs(
        self, writer_client: Client, caplog
    ) -> None:
        import logging

        from apps.pending_items import services

        admission = _eligible_admission("P_HTTP_LOG")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        marker = "marcador-sintetico-unico-4821"
        with caplog.at_level(logging.DEBUG):
            services.create_pending_item(
                admission=admission,
                item_type=outro,
                description=marker,
                author=User.objects.get(username="http_writer"),
            )
        for record in caplog.records:
            assert marker not in record.getMessage()
