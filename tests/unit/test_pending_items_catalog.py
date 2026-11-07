"""STRUCT-PEND-S1: catalog identity guards, S1 constraints and snapshots.

Covers R2 (immutable slugs, protected contract for used types including
history-only references, fixed ``Outro`` contract, referenced category
deletion), the S1 local constraints of design D3 exercised by direct
writes, and R4 (the seven observed classification metadata written by
every revision author).

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.catalog import type_display_label
from apps.pending_items.models import (
    ACTION_CREATED,
    GROUP_NAME,
    OUTRO_NAME,
    OUTRO_SLUG,
    PROFILE_SCHEDULING,
    PROFILE_SIMPLE,
    PROFILE_TREATMENT,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    PendingItem,
    PendingItemCategory,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import (
    close_pending_items_for_confirmed_exit,
    create_pending_item,
    finalize_pending_item,
    update_pending_item,
)

TZ = ZoneInfo("America/Bahia")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


@pytest.fixture
def writer(db: object) -> User:
    user = User.objects.create_user(username="cat_writer", password="x")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


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


def _make_census_row(prontuario: str) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="CLINICA MEDICA",
        leito="L01",
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        bed_status=BedStatus.OCCUPIED,
    )


def _eligible_admission(key: str = "P_CAT_1") -> Admission:
    patient = _make_patient(key)
    admission = _make_admission(patient, f"ADM_{key}")
    _make_census_row(key)
    return admission


def _category(slug: str, name: str) -> PendingItemCategory:
    return PendingItemCategory.objects.create(slug=slug, name=name)


def _type(
    category: PendingItemCategory,
    *,
    slug: str = "tipo-simples",
    name: str = "Tipo Simples",
    profile: str = PROFILE_SIMPLE,
    has_rnm_complements: bool = False,
    requires_description: bool = False,
) -> PendingItemType:
    return PendingItemType.objects.create(
        slug=slug,
        name=name,
        category=category,
        profile=profile,
        has_rnm_complements=has_rnm_complements,
        requires_description=requires_description,
    )


@pytest.mark.django_db
class TestCatalogIdentityGuards:
    def test_category_slug_is_immutable(self, db: object) -> None:
        category = _category("cat-fixa", "Categoria Fixa")
        category.slug = "cat-trocada"
        with pytest.raises(ValidationError):
            category.save()
        category.refresh_from_db()
        assert category.slug == "cat-fixa"

    def test_used_type_contract_is_protected(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_USED")
        category = _category("cat-usada", "Categoria Usada")
        other = _category("cat-outra", "Categoria Outra")
        item_type = _type(category)
        create_pending_item(
            admission=admission,
            item_type=item_type,
            description="pendencia sintetica",
            author=writer,
        )

        for field, value in (
            ("category", other),
            ("profile", PROFILE_TREATMENT),
            ("has_rnm_complements", True),
            ("requires_description", True),
        ):
            item_type.refresh_from_db()
            setattr(item_type, field, value)
            with pytest.raises(ValidationError):
                item_type.save()

        item_type.refresh_from_db()
        assert item_type.category_id == category.pk
        assert item_type.profile == PROFILE_SIMPLE
        assert item_type.has_rnm_complements is False
        assert item_type.requires_description is False

        item_type.name = "Nome Visivel Novo"
        item_type.save()
        item_type.refresh_from_db()
        assert item_type.name == "Nome Visivel Novo"

    def test_history_only_reference_protects_contract_and_delete(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_HISTORY")
        category = _category("cat-historica", "Categoria Histórica")
        historical_type = _type(category, slug="tipo-historico", name="Tipo Histórico")
        current_type = _type(category, slug="tipo-atual", name="Tipo Atual")
        item = create_pending_item(
            admission=admission,
            item_type=historical_type,
            description="pendencia sintetica",
            author=writer,
        )
        update_pending_item(
            item=item,
            item_type=current_type,
            description="pendencia sintetica",
            author=writer,
            expected_version=1,
        )
        assert not PendingItem.objects.filter(item_type=historical_type).exists()
        assert PendingItemRevision.objects.filter(
            item_type=historical_type
        ).exists()

        with pytest.raises(ProtectedError):
            historical_type.delete()

        historical_type.profile = PROFILE_TREATMENT
        with pytest.raises(ValidationError):
            historical_type.save()

    def test_outro_contract_is_fixed_without_use(self, db: object) -> None:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        other_category = _category("cat-destino", "Categoria Destino")
        mutations = (
            ("name", "Renomeado"),
            ("slug", "outro-trocado"),
            ("category", other_category),
            ("profile", PROFILE_SCHEDULING),
            ("has_rnm_complements", True),
            ("requires_description", False),
        )
        for field, value in mutations:
            outro.refresh_from_db()
            setattr(outro, field, value)
            with pytest.raises(ValidationError):
                outro.save()

        outro.refresh_from_db()
        assert outro.name == OUTRO_NAME
        assert outro.slug == OUTRO_SLUG
        assert outro.category.slug == "outras-pendencias"
        assert outro.profile == PROFILE_SIMPLE
        assert outro.has_rnm_complements is False
        assert outro.requires_description is True

    def test_category_with_types_cannot_be_deleted(self, db: object) -> None:
        category = _category("cat-com-tipos", "Categoria Com Tipos")
        _type(category)
        with pytest.raises(ProtectedError):
            category.delete()
        assert PendingItemCategory.objects.filter(pk=category.pk).exists()


@pytest.mark.django_db
class TestS1LocalConstraints:
    def _new_type(self) -> PendingItemType:
        return _type(_category("cat-check", "Categoria Check"))

    def test_type_profile_must_be_a_fixed_profile(self) -> None:
        item_type = self._new_type()
        with pytest.raises(IntegrityError), transaction.atomic():
            PendingItemType.objects.filter(pk=item_type.pk).update(
                profile="perfil-inventado"
            )

    def test_type_rnm_complements_require_scheduling_profile(self) -> None:
        item_type = self._new_type()
        with pytest.raises(IntegrityError), transaction.atomic():
            PendingItemType.objects.filter(pk=item_type.pk).update(
                has_rnm_complements=True
            )

    def _revision(self) -> PendingItemRevision:
        admission = _eligible_admission("P_CAT_REV")
        item_type = _type(
            _category("cat-rev", "Categoria Revisão"),
            slug="tipo-rev",
            name="Tipo Revisão",
        )
        return PendingItemRevision.objects.create(
            item=PendingItem.objects.create(
                admission=admission,
                item_type=item_type,
                description="registro sintetico",
                status=STATUS_ACTIVE,
                version=1,
            ),
            version=1,
            action=ACTION_CREATED,
            item_type=item_type,
            type_name=item_type.name,
            description="registro sintetico",
            status=STATUS_ACTIVE,
            category_name=item_type.category.name,
            category_slug=item_type.category.slug,
            type_slug=item_type.slug,
            profile=item_type.profile,
            has_rnm_complements=item_type.has_rnm_complements,
            requires_description=item_type.requires_description,
        )

    def test_revision_profile_must_be_known_value(self) -> None:
        revision = self._revision()
        with pytest.raises(IntegrityError), transaction.atomic():
            PendingItemRevision.objects.filter(pk=revision.pk).update(
                profile="perfil-inventado"
            )

    def test_revision_rnm_complements_require_scheduling_when_known(
        self,
    ) -> None:
        revision = self._revision()
        with pytest.raises(IntegrityError), transaction.atomic():
            PendingItemRevision.objects.filter(pk=revision.pk).update(
                has_rnm_complements=True
            )

    def test_revision_unknown_classification_is_allowed(self) -> None:
        revision = self._revision()
        PendingItemRevision.objects.filter(pk=revision.pk).update(
            category_name=None,
            category_slug=None,
            type_slug=None,
            profile=None,
            has_rnm_complements=None,
            requires_description=None,
        )
        stored = PendingItemRevision.objects.get(pk=revision.pk)
        assert stored.category_name is None
        assert stored.profile is None
        assert stored.has_rnm_complements is None
        assert stored.requires_description is None


@pytest.mark.django_db
class TestClassificationSnapshots:
    def test_creation_records_seven_classification_metadata(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_SNAP")
        category = _category("cat-snap", "Categoria Snapshot")
        item_type = _type(
            category,
            slug="tipo-snap",
            name="Tipo Snapshot",
            profile=PROFILE_SCHEDULING,
            has_rnm_complements=True,
            requires_description=True,
        )
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="registro sintetico",
            details={"is_scheduled": True},
            author=writer,
        )
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.type_name == "Tipo Snapshot"
        assert revision.type_slug == "tipo-snap"
        assert revision.category_name == "Categoria Snapshot"
        assert revision.category_slug == "cat-snap"
        assert revision.profile == PROFILE_SCHEDULING
        assert revision.has_rnm_complements is True
        assert revision.requires_description is True

    def test_rename_does_not_rewrite_previous_revision(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_RENAME")
        category = _category("cat-ren", "Categoria Renomeável")
        item_type = _type(category, slug="tipo-ren", name="Tipo Antigo")
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="registro sintetico",
            author=writer,
        )
        item_type.name = "Tipo Novo"
        item_type.save()
        category.name = "Categoria Renomeada"
        category.save()

        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.type_name == "Tipo Antigo"
        assert revision.category_name == "Categoria Renomeável"
        item.refresh_from_db()
        assert item.item_type.name == "Tipo Novo"

    def test_update_records_new_observed_classification(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_UPDATE")
        first = _category("cat-primeira", "Categoria Primeira")
        second = _category("cat-segunda", "Categoria Segunda")
        first_type = _type(first, slug="tipo-primeiro", name="Tipo Primeiro")
        second_type = _type(
            second,
            slug="tipo-segundo",
            name="Tipo Segundo",
            profile=PROFILE_TREATMENT,
        )
        item = create_pending_item(
            admission=admission,
            item_type=first_type,
            description="registro sintetico",
            author=writer,
        )
        update_pending_item(
            item=item,
            item_type=second_type,
            description="registro sintetico",
            author=writer,
            expected_version=1,
        )
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.category_name == "Categoria Segunda"
        assert revision.category_slug == "cat-segunda"
        assert revision.type_name == "Tipo Segundo"
        assert revision.type_slug == "tipo-segundo"
        assert revision.profile == PROFILE_TREATMENT
        assert revision.has_rnm_complements is False
        assert revision.requires_description is False

    def test_human_finalization_copies_classification(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_FINAL")
        category = _category("cat-final", "Categoria Final")
        item_type = _type(category, slug="tipo-final", name="Tipo Final")
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="registro sintetico",
            author=writer,
        )
        finalize_pending_item(
            item=item,
            target_status=STATUS_CLOSED_UNRESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.category_slug == "cat-final"
        assert revision.type_slug == "tipo-final"
        assert revision.profile == PROFILE_SIMPLE
        assert revision.requires_description is False

    def test_system_close_copies_classification(self, writer: User) -> None:
        patient = _make_patient("P_CAT_SYSTEM")
        admission = _make_admission(patient, "ADM_P_CAT_SYSTEM")
        _make_census_row("P_CAT_SYSTEM")
        category = _category("cat-sistema", "Categoria Sistema")
        item_type = _type(
            category,
            slug="tipo-sistema",
            name="Tipo Sistema",
            profile=PROFILE_SCHEDULING,
        )
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="registro sintetico",
            details={"is_scheduled": False},
            author=writer,
        )
        Admission.objects.filter(pk=admission.pk).update(
            discharge_date=_dt("2026-06-20T10:00:00")
        )
        admission.refresh_from_db()
        closed = close_pending_items_for_confirmed_exit(admission=admission)
        assert closed == 1
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.is_system is True
        assert revision.category_name == "Categoria Sistema"
        assert revision.category_slug == "cat-sistema"
        assert revision.type_slug == "tipo-sistema"
        assert revision.profile == PROFILE_SCHEDULING
        assert revision.has_rnm_complements is False
        assert revision.requires_description is False

    def test_legacy_revision_keeps_unknown_metadata_after_new_version(
        self, writer: User
    ) -> None:
        admission = _eligible_admission("P_CAT_LEGACY")
        category = _category("cat-legada", "Categoria Legada")
        item_type = _type(category, slug="tipo-legado", name="Tipo Legado")
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="registro sintetico",
            author=writer,
        )
        PendingItemRevision.objects.filter(item=item, version=1).update(
            category_name=None,
            category_slug=None,
            type_slug=None,
            profile=None,
            has_rnm_complements=None,
            requires_description=None,
        )
        finalize_pending_item(
            item=item,
            target_status=STATUS_CLOSED_UNRESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        legacy = PendingItemRevision.objects.get(item=item, version=1)
        assert legacy.category_name is None
        assert legacy.profile is None
        assert legacy.has_rnm_complements is None
        assert legacy.requires_description is None
        newest = PendingItemRevision.objects.get(item=item, version=2)
        assert newest.category_slug == "cat-legada"
        assert newest.requires_description is False


@pytest.mark.django_db
class TestTypeDisplayLabel:
    """S3-P2-1: one shared ``Categoria > Tipo`` label for homonyms."""

    def test_homonymous_types_are_qualified_by_category(self) -> None:
        imagem_rnm = PendingItemType.objects.get(slug="imagem-rnm")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        assert type_display_label(imagem_rnm) == "Exames de imagem > RNM"
        assert type_display_label(chd_rnm) == (
            "CHD (Centro de Hemorragia Digestiva) > RNM"
        )
