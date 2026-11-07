"""STRUCT-PEND-S2: HTTP surfaces for structured cadastro and edition.

Covers R1/R2/R4/R5: real POST validation, progressive form contents,
shared contextual/quick-edit writes, Save-and-add-another PRG, conflicts
and lost eligibility keeping attempted values, and cache protection.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    GROUP_NAME,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    PendingItem,
    PendingItemCategory,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import CONFLICT_MESSAGE

TZ = ZoneInfo("America/Bahia")

START = date(2026, 11, 10)
END = date(2026, 11, 20)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


@pytest.fixture
def writer_client(client: Client, db: object) -> Client:
    user = User.objects.create_user(username="s2_http_writer", password="pw123456")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    client.login(username="s2_http_writer", password="pw123456")
    return client


@pytest.fixture
def reader_client(client: Client, db: object) -> Client:
    User.objects.create_user(username="s2_http_reader", password="pw123456")
    client.login(username="s2_http_reader", password="pw123456")
    return client


def _eligible_admission(key: str = "P_S2_HTTP") -> Admission:
    patient = Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM_{key}",
        admission_date=_dt("2026-06-01T08:00:00"),
    )
    CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="CLINICA MEDICA",
        leito="L01",
        prontuario=key,
        nome=f"PACIENTE SINTETICO {key}",
        bed_status=BedStatus.OCCUPIED,
    )
    return admission


def _type(slug: str) -> PendingItemType:
    return PendingItemType.objects.get(slug=slug)


def _url(admission: Admission) -> str:
    return f"/admissions/{admission.pk}/pending-items/"


def _edit_url(admission: Admission, item: PendingItem) -> str:
    return f"/admissions/{admission.pk}/pending-items/{item.pk}/edit/"


def _history_url(admission: Admission, item: PendingItem) -> str:
    return f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"


def _make_item(
    admission: Admission,
    *,
    slug: str = "imagem-rnm",
    description: str = "",
    **details,
) -> PendingItem:
    item_type = _type(slug)
    item = PendingItem.objects.create(
        admission=admission,
        item_type=item_type,
        description=description,
        status=STATUS_ACTIVE,
        version=1,
        **details,
    )
    PendingItemRevision.objects.create(
        item=item,
        version=1,
        action="created",
        item_type=item_type,
        type_name=item_type.name,
        category_name=item_type.category.name,
        category_slug=item_type.category.slug,
        type_slug=item_type.slug,
        profile=item_type.profile,
        has_rnm_complements=item_type.has_rnm_complements,
        requires_description=item_type.requires_description,
        description=description,
        status=STATUS_ACTIVE,
        **{name: details.get(name) for name in _detail_names()},
    )
    return item


def _detail_names() -> tuple[str, ...]:
    return (
        "is_scheduled",
        "scheduled_date",
        "treatment_start_date",
        "treatment_end_date",
        "signature_at",
        "contrast",
        "sedation",
    )


@pytest.mark.django_db
class TestProgressiveCreateForm:
    """PP-10/R1: the page offers category, search and profile details."""

    def test_create_form_exposes_classification_and_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_FORM")
        response = writer_client.get(_url(admission))
        content = response.content.decode()
        assert response.status_code == 200
        assert 'name="category"' in content
        assert 'name="type_search"' in content
        assert 'name="is_scheduled"' in content
        assert 'name="scheduled_date"' in content
        assert 'name="treatment_start_date"' in content
        assert 'name="treatment_end_date"' in content
        assert 'name="signature_at"' in content
        assert 'name="contrast"' in content
        assert 'name="sedation"' in content
        assert 'name="confirm_detail_removal"' in content
        assert "Salvar e adicionar outra" in content
        assert "Paciente" in content or admission.patient.name in content
        assert (writer_client.get(_url(admission)).headers["Cache-Control"]) == (
            "private, no-store"
        )

    def test_create_form_data_attributes_describe_each_type(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_FORM_DATA")
        content = writer_client.get(_url(admission)).content.decode()
        assert 'data-profile="agendamento"' in content
        assert 'data-profile="tratamento-periodo"' in content
        assert 'data-profile="assinatura-documento"' in content
        assert 'data-rnm="1"' in content
        assert 'data-requires-description="1"' in content


@pytest.mark.django_db
class TestStructuredCreatePost:
    """R1: real POST honours profile rules and conditional observations."""

    def test_scheduling_type_without_observation_is_created(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_NO_OBS")
        response = writer_client.post(
            _url(admission),
            {
                "category": str(_type("imagem-tomografia").category_id),
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "nao",
            },
        )
        assert response.status_code == 302
        item = PendingItem.objects.get(admission=admission)
        assert item.description == ""
        assert item.is_scheduled is False
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.is_scheduled is False
        assert revision.description == ""

    def test_missing_scheduling_answer_is_rejected(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_MISSING")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
            },
        )
        assert response.status_code == 200
        assert "Informe se está agendada" in response.content.decode()
        assert PendingItem.objects.count() == 0
        assert PendingItemRevision.objects.count() == 0

    def test_no_with_date_is_rejected(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_S2_POST_NO_DATE")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "nao",
                "scheduled_date": START.isoformat(),
            },
        )
        assert response.status_code == 200
        assert PendingItem.objects.count() == 0

    def test_rnm_complements_and_date_are_persisted(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_RNM")
        target = _type("imagem-rnm")
        response = writer_client.post(
            _url(admission),
            {
                "category": str(target.category_id),
                "item_type": str(target.pk),
                "description": "",
                "is_scheduled": "sim",
                "scheduled_date": START.isoformat(),
                "contrast": "sim",
                "sedation": "nao",
            },
        )
        assert response.status_code == 302
        item = PendingItem.objects.get(admission=admission)
        assert item.scheduled_date == START
        assert item.contrast is True
        assert item.sedation is False

    def test_category_mismatch_is_rejected(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_S2_POST_MISMATCH")
        response = writer_client.post(
            _url(admission),
            {
                "category": str(_type("chd-rnm").category_id),
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "nao",
            },
        )
        assert response.status_code == 200
        assert PendingItem.objects.count() == 0

    def test_out_of_profile_detail_is_rejected(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_PROFILE")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "nao",
                "contrast": "sim",
            },
        )
        assert response.status_code == 200
        assert PendingItem.objects.count() == 0

    def test_partial_treatment_dates_are_accepted(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_TREAT")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("infeccioso-antibioticos").pk),
                "description": "",
                "treatment_start_date": START.isoformat(),
            },
        )
        assert response.status_code == 302
        item = PendingItem.objects.get(admission=admission)
        assert item.treatment_start_date == START
        assert item.treatment_end_date is None

    def test_end_before_start_is_rejected(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_S2_POST_ORDER")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("infeccioso-antibioticos").pk),
                "description": "",
                "treatment_start_date": END.isoformat(),
                "treatment_end_date": START.isoformat(),
            },
        )
        assert response.status_code == 200
        assert PendingItem.objects.count() == 0

    def test_generic_type_still_requires_observation(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_POST_GENERIC")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type(OUTRO_SLUG).pk),
                "description": "   ",
            },
        )
        assert response.status_code == 200
        assert "Descrição é obrigatória" in response.content.decode()
        assert PendingItem.objects.count() == 0

    def test_reader_cannot_create(self, reader_client: Client) -> None:
        admission = _eligible_admission("P_S2_POST_READER")
        response = reader_client.post(
            _url(admission),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "is_scheduled": "nao",
            },
        )
        assert response.status_code == 403
        assert PendingItem.objects.count() == 0


@pytest.mark.django_db
class TestSaveAndAddAnother:
    """PP-10: POST/redirect/GET without duplicating a refresh."""

    def test_save_and_add_another_returns_empty_form(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_ADD_ANOTHER")
        response = writer_client.post(
            _url(admission),
            {
                "item_type": str(_type("infeccioso-antibioticos").pk),
                "description": "",
                "treatment_start_date": START.isoformat(),
                "action": "save_new",
            },
            follow=True,
        )
        assert response.redirect_chain
        content = response.content.decode()
        assert "Pendência cadastrada" in content
        assert 'value="2026-11-10"' not in content
        follow_up = writer_client.get(_url(admission))
        assert follow_up.status_code == 200
        assert PendingItem.objects.count() == 1
        refreshed = writer_client.get(_url(admission))
        assert refreshed.status_code == 200
        assert PendingItem.objects.count() == 1
        assert refreshed.content.decode().count("Início do tratamento:") >= 1


@pytest.mark.django_db
class TestContextualEdit:
    """R2/R4: contextual edit writes details, history shows them."""

    def test_edit_page_exposes_stored_values(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_PAGE")
        item = _make_item(
            admission,
            is_scheduled=True,
            scheduled_date=START,
            contrast=True,
        )
        response = writer_client.get(_edit_url(admission, item))
        content = response.content.decode()
        assert response.status_code == 200
        assert 'value="2026-11-10"' in content
        assert 'value="sim"' in content

    def test_detail_only_edit_creates_version_and_history(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_DETAIL")
        item = _make_item(
            admission,
            is_scheduled=True,
            contrast=True,
        )
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "",
                "is_scheduled": "sim",
                "scheduled_date": START.isoformat(),
                "contrast": "sim",
                "sedation": "",
                "expected_version": "1",
            },
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.version == 2
        assert item.scheduled_date == START
        history = writer_client.get(_history_url(admission, item))
        content = history.content.decode()
        assert "Data agendada: 10/11/2026" in content
        assert "Contraste: Sim" in content

    def test_untouched_details_survive_a_text_edit(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_KEEP")
        item = _make_item(
            admission,
            is_scheduled=True,
            scheduled_date=START,
            contrast=True,
            sedation=False,
        )
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "observacao nova",
                "expected_version": "1",
            },
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.description == "observacao nova"
        assert item.scheduled_date == START
        assert item.contrast is True
        assert item.sedation is False

    def test_profile_change_requires_confirmation(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_REMOVE")
        item = _make_item(
            admission,
            is_scheduled=True,
            contrast=True,
        )
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "sim",
                "expected_version": "1",
            },
        )
        content = response.content.decode()
        assert response.status_code == 200
        assert "Confirmo a remoção" in content
        item.refresh_from_db()
        assert item.item_type.slug == "imagem-rnm"
        assert item.version == 1

    def test_confirmed_profile_change_removes_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_REMOVE_CONFIRM")
        item = _make_item(
            admission,
            is_scheduled=True,
            contrast=True,
        )
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(_type("imagem-tomografia").pk),
                "description": "",
                "is_scheduled": "sim",
                "confirm_detail_removal": "on",
                "expected_version": "1",
            },
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.item_type.slug == "imagem-tomografia"
        assert item.contrast is None
        previous = PendingItemRevision.objects.get(item=item, version=1)
        assert previous.contrast is True

    def test_legacy_item_requires_explicit_scheduling_answer(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_LEGACY")
        item = _make_item(admission, is_scheduled=None)
        page = writer_client.get(_edit_url(admission, item))
        content = page.content.decode()
        assert "Não informado" in content
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "",
                "expected_version": "1",
            },
        )
        assert response.status_code == 200
        assert "Informe se está agendada" in response.content.decode()
        item.refresh_from_db()
        assert item.is_scheduled is None
        assert item.version == 1

    def test_conflict_keeps_attempted_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_CONFLICT")
        item = _make_item(admission, is_scheduled=True)
        first = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "primeira",
                "is_scheduled": "sim",
                "expected_version": "1",
            },
        )
        assert first.status_code == 302
        stale = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "envio antigo",
                "is_scheduled": "sim",
                "scheduled_date": END.isoformat(),
                "expected_version": "1",
            },
        )
        content = stale.content.decode()
        assert stale.status_code == 409
        assert CONFLICT_MESSAGE in content
        assert "envio antigo" in content
        assert "20/11/2026" in content
        item.refresh_from_db()
        assert item.description == "primeira"
        assert item.scheduled_date is None

    def test_lost_eligibility_keeps_attempted_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_EDIT_LOST")
        item = _make_item(admission, is_scheduled=True)
        CensusSnapshot.objects.filter(prontuario="P_S2_EDIT_LOST").delete()
        response = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "tentativa sem censo",
                "is_scheduled": "sim",
                "scheduled_date": START.isoformat(),
                "expected_version": "1",
            },
        )
        content = response.content.decode()
        assert response.status_code == 403
        assert "tentativa sem censo" in content
        assert "10/11/2026" in content
        item.refresh_from_db()
        assert item.version == 1


@pytest.mark.django_db
class TestQuickEditModal:
    """PP-06: the modal writes the same details safely."""

    def _modal_url(self, item: PendingItem) -> str:
        return f"/pendencias/{item.pk}/edit/?next=/pendencias/"

    def test_modal_renders_shared_fields(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_MODAL_GET")
        item = _make_item(
            admission,
            is_scheduled=True,
            scheduled_date=START,
            contrast=True,
        )
        response = writer_client.get(
            self._modal_url(item), headers={"HX-Request": "true"}
        )
        content = response.content.decode()
        assert response.status_code == 200
        assert 'name="is_scheduled"' in content
        assert 'name="contrast"' in content
        assert 'value="2026-11-10"' in content
        assert '"private, no-store"' not in content
        assert "private" in response.headers["Cache-Control"]
        assert "no-store" in response.headers["Cache-Control"]

    def test_modal_detail_change_keeps_other_values(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_MODAL_POST")
        item = _make_item(
            admission,
            description="original",
            is_scheduled=True,
            contrast=True,
            sedation=False,
        )
        response = writer_client.post(
            self._modal_url(item),
            {
                "item_type": str(item.item_type_id),
                "description": "original",
                "is_scheduled": "sim",
                "scheduled_date": START.isoformat(),
                "expected_version": "1",
                "next": "/pendencias/",
            },
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/pendencias/"
        item.refresh_from_db()
        assert item.scheduled_date == START
        assert item.contrast is True
        assert item.sedation is False
        assert item.description == "original"

    def test_modal_conflict_keeps_attempted_values(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_MODAL_CONFLICT")
        item = _make_item(admission, is_scheduled=True)
        PendingItem.objects.filter(pk=item.pk).update(version=2)
        response = writer_client.post(
            self._modal_url(item),
            {
                "item_type": str(item.item_type_id),
                "description": "tentativa",
                "is_scheduled": "sim",
                "scheduled_date": END.isoformat(),
                "expected_version": "1",
                "next": "/pendencias/",
            },
            headers={"HX-Request": "true"},
        )
        content = response.content.decode()
        # htmx swaps only successful responses, so the fragment keeps the
        # conflict message and the current version token with status 200;
        # the plain (non-HTMX) surface still answers 409.
        assert response.status_code == 200
        assert CONFLICT_MESSAGE in content
        assert "tentativa" in content
        assert "20/11/2026" in content
        assert "atualizada com sucesso" not in content


@pytest.mark.django_db
class TestFinalizeWithDetails:
    """PI-05: finalization never requires completing the cadastro fields."""

    def test_finalize_page_and_post_ignore_missing_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_FINALIZE_HTTP")
        item = PendingItem.objects.create(
            admission=admission,
            item_type=_type("imagem-tomografia"),
            description="registro anterior",
            status=STATUS_ACTIVE,
            version=1,
        )
        page = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/finalize/"
        )
        assert page.status_code == 200
        response = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/finalize/",
            {"target_status": "resolved", "note": "", "expected_version": "1"},
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.version == 2
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.is_scheduled is None


@pytest.mark.django_db
class TestDetailPresentationContext:
    """PP-03/D6: contextual list and history share the same presentation."""

    def test_list_shows_classification_and_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_LIST_DETAILS")
        _make_item(
            admission,
            slug="sumario-assinatura",
            signature_at=_dt("2026-11-12T09:30:00"),
        )
        content = writer_client.get(_url(admission)).content.decode()
        assert "Sumário de alta" in content
        assert "Assinatura do sumário em: 12/11/2026 09:30" in content

    def test_history_explains_unknown_old_version(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_HISTORY_UNKNOWN")
        item = _make_item(admission, slug="quadro-melhora-clinica")
        PendingItemRevision.objects.filter(item=item).update(
            category_name=None,
            category_slug=None,
            type_slug=None,
            profile=None,
            has_rnm_complements=None,
            requires_description=None,
        )
        content = writer_client.get(
            _history_url(admission, item)
        ).content.decode()
        assert "Classificação não registrada nesta versão" in content
        assert "Detalhes não registrados nesta versão" in content


@pytest.mark.django_db
class TestAnonymousAndCache:
    def test_anonymous_is_redirected(self, client: Client) -> None:
        admission = _eligible_admission("P_S2_ANON")
        response = client.get(_url(admission))
        assert response.status_code == 302
        assert "/login/" in response.headers["Location"]

    def test_error_repaint_keeps_cache_protection(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_CACHE")
        response = writer_client.post(
            _url(admission),
            {"item_type": str(_type("imagem-tomografia").pk)},
        )
        assert response.status_code == 200
        assert "private" in response.headers["Cache-Control"]
        assert "no-store" in response.headers["Cache-Control"]

    def test_quick_edit_conflict_keeps_cache_protection(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_CACHE_MODAL")
        item = _make_item(admission, is_scheduled=True)
        PendingItem.objects.filter(pk=item.pk).update(version=3)
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            {
                "item_type": str(item.item_type_id),
                "description": "",
                "is_scheduled": "sim",
                "expected_version": "1",
            },
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "alterada por outra pessoa" in response.content.decode()
        assert "private" in response.headers["Cache-Control"]


@pytest.mark.django_db
class TestScheduledConfirmationRemoval:
    """D3: Sim -> Não with an existing date needs confirmation on HTTP."""

    def test_sim_to_no_requires_confirmation(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_HTTP_SIM_NO")
        item = _make_item(
            admission,
            is_scheduled=True,
            scheduled_date=START,
        )
        rejected = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "",
                "is_scheduled": "nao",
                "expected_version": "1",
            },
        )
        assert rejected.status_code == 200
        assert "Confirmo a remoção" in rejected.content.decode()
        item.refresh_from_db()
        assert item.scheduled_date == START
        accepted = writer_client.post(
            _edit_url(admission, item),
            {
                "item_type": str(item.item_type_id),
                "description": "",
                "is_scheduled": "nao",
                "confirm_detail_removal": "on",
                "expected_version": "1",
            },
        )
        assert accepted.status_code == 302
        item.refresh_from_db()
        assert item.is_scheduled is False
        assert item.scheduled_date is None


@pytest.mark.django_db
class TestCategorySearchLabels:
    def test_category_options_are_offered(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_CATEGORIES")
        content = writer_client.get(_url(admission)).content.decode()
        for category in PendingItemCategory.objects.all():
            assert category.slug in content


@pytest.mark.django_db
class TestNoDuplicateOnRedirectTarget:
    def test_repeated_get_never_creates(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_S2_NO_DUP")
        before = PendingItem.objects.count()
        writer_client.get(_url(admission))
        writer_client.get(_url(admission))
        assert PendingItem.objects.count() == before


@pytest.mark.django_db
class TestClosedEpisodeKeepsDetails:
    """R3/PI-07: a confirmed exit leaves the episode read-only with details."""

    def test_closed_episode_is_read_only_and_keeps_details(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_S2_CLOSED")
        item = _make_item(
            admission,
            slug="infeccioso-antibioticos",
            treatment_start_date=START,
            treatment_end_date=END,
        )
        admission.discharge_date = _dt("2026-06-20T10:00:00")
        admission.save(update_fields=["discharge_date"])
        content = writer_client.get(_url(admission)).content.decode()
        assert "Início do tratamento: 10/11/2026" in content
        assert "Previsão de término: 20/11/2026" in content
        assert 'data-testid="pending-create"' not in content
        assert f'data-testid="pending-edit-{item.pk}"' not in content
        history = writer_client.get(
            _history_url(admission, item)
        ).content.decode()
        assert "Início do tratamento: 10/11/2026" in history
