"""STRUCT-PEND-S2: non-destructive upgrade from the S1 catalog state.

The ``pending_items`` app is moved back to ``0005_catalog_contract_
constraints`` (the post-S1 shape), a synthetic item and its revisions
are written with the historical model, and the database is migrated
forward to the S2 leaf. The upgrade must keep every identity, state and
revision and leave the new typed details unknown.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    GROUP_NAME,
    PendingItem,
    PendingItemRevision,
)
from apps.pending_items.services import update_pending_item

TZ = ZoneInfo("America/Bahia")
BASE_MIGRATION = ("pending_items", "0005_catalog_contract_constraints")

DETAIL_FIELDS = (
    "is_scheduled",
    "scheduled_date",
    "treatment_start_date",
    "treatment_end_date",
    "signature_at",
    "contrast",
    "sedation",
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _leaf_node() -> tuple[str, str]:
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    return executor.loader.graph.leaf_nodes("pending_items")[0]


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])
    executor.loader.build_graph()
    return executor


def _seed_historical_catalog(historical_apps) -> None:
    """Seed the pre-S2 catalog rows this upgrade test needs.

    ``django_db(transaction=True)`` flushes the database between tests,
    which also removes rows written by the S1 data migration; the test
    therefore creates the post-S1 rows it expects before moving back.
    """
    Category = historical_apps.get_model(
        "pending_items", "PendingItemCategory"
    )
    ItemType = historical_apps.get_model("pending_items", "PendingItemType")
    category, _created = Category.objects.get_or_create(
        slug="exames-imagem", defaults={"name": "Exames de imagem"}
    )
    ItemType.objects.get_or_create(
        slug="imagem-tomografia",
        defaults={
            "name": "Tomografia",
            "category": category,
            "profile": "agendamento",
            "has_rnm_complements": False,
            "requires_description": False,
        },
    )


@pytest.mark.django_db(transaction=True)
class TestUpgradeFromS1:
    @pytest.fixture(autouse=True)
    def _restore_leaf(self):
        yield
        _migrate(_leaf_node())

    def test_upgrade_keeps_identity_and_leaves_details_unknown(self) -> None:
        executor = _migrate(BASE_MIGRATION)
        historical = executor.loader.project_state([BASE_MIGRATION]).apps
        _seed_historical_catalog(historical)
        ItemType = historical.get_model("pending_items", "PendingItemType")
        Item = historical.get_model("pending_items", "PendingItem")
        Revision = historical.get_model(
            "pending_items", "PendingItemRevision"
        )

        item_type = ItemType.objects.get(slug="imagem-tomografia")
        author, _created = User.objects.get_or_create(username="s2_upgrade_author")
        patient = Patient.objects.create(
            patient_source_key="P_S2_UPGRADE",
            source_system="tasy",
            name="PACIENTE SINTETICO P_S2_UPGRADE",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_P_S2_UPGRADE",
            admission_date=_dt("2026-06-01T08:00:00"),
        )
        item = Item.objects.create(
            admission_id=admission.pk,
            item_type_id=item_type.pk,
            description="tomografia anterior a atualizacao",
            status="resolved",
            version=2,
            finalized_at=_dt("2026-06-15T10:00:00"),
            created_by_id=author.pk,
            created_by_name=author.get_username(),
            updated_by_id=author.pk,
            updated_by_name=author.get_username(),
        )
        Revision.objects.create(
            item_id=item.pk,
            version=1,
            action="created",
            item_type_id=item_type.pk,
            type_name="Tomografia",
            category_name="Exames de imagem",
            category_slug="exames-imagem",
            type_slug="imagem-tomografia",
            profile="agendamento",
            has_rnm_complements=False,
            requires_description=False,
            description="tomografia anterior a atualizacao",
            status="active",
            author_id=author.pk,
            author_name=author.get_username(),
        )
        Revision.objects.create(
            item_id=item.pk,
            version=2,
            action="finalized",
            item_type_id=item_type.pk,
            type_name="Tomografia",
            category_name="Exames de imagem",
            category_slug="exames-imagem",
            type_slug="imagem-tomografia",
            profile="agendamento",
            has_rnm_complements=False,
            requires_description=False,
            description="tomografia anterior a atualizacao",
            status="resolved",
            note="",
            author_id=author.pk,
            author_name=author.get_username(),
        )
        item_pk = item.pk
        revision_count = Revision.objects.count()

        _migrate(_leaf_node())

        upgraded = PendingItem.objects.get(pk=item_pk)
        assert upgraded.admission_id == admission.pk
        assert upgraded.item_type_id == item_type.pk
        assert upgraded.description == "tomografia anterior a atualizacao"
        assert upgraded.status == "resolved"
        assert upgraded.version == 2
        assert upgraded.created_by_id == author.pk
        assert upgraded.created_by_name == author.get_username()
        assert upgraded.finalized_at is not None
        for name in DETAIL_FIELDS:
            assert getattr(upgraded, name) is None

        revisions = PendingItemRevision.objects.filter(item_id=item_pk).order_by(
            "version"
        )
        assert revisions.count() == revision_count
        for revision in revisions:
            for name in DETAIL_FIELDS:
                assert getattr(revision, name) is None
        first = revisions.first()
        assert first is not None
        assert first.type_name == "Tomografia"
        assert first.category_slug == "exames-imagem"

    def test_upgraded_item_can_be_edited_with_explicit_answer(self) -> None:
        executor = _migrate(BASE_MIGRATION)
        historical = executor.loader.project_state([BASE_MIGRATION]).apps
        _seed_historical_catalog(historical)
        ItemType = historical.get_model("pending_items", "PendingItemType")
        Item = historical.get_model("pending_items", "PendingItem")
        Revision = historical.get_model(
            "pending_items", "PendingItemRevision"
        )

        item_type = ItemType.objects.get(slug="imagem-tomografia")
        author, _created = User.objects.get_or_create(username="s2_upgrade_writer")
        group, _created = Group.objects.get_or_create(name=GROUP_NAME)
        group.user_set.add(author)
        patient = Patient.objects.create(
            patient_source_key="P_S2_UPGRADE_EDIT",
            source_system="tasy",
            name="PACIENTE SINTETICO P_S2_UPGRADE_EDIT",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_P_S2_UPGRADE_EDIT",
            admission_date=_dt("2026-06-01T08:00:00"),
        )
        CensusSnapshot.objects.create(
            captured_at=_dt("2026-06-10T08:00:00"),
            setor="CLINICA MEDICA",
            leito="L01",
            prontuario="P_S2_UPGRADE_EDIT",
            nome="PACIENTE SINTETICO P_S2_UPGRADE_EDIT",
            bed_status=BedStatus.OCCUPIED,
        )
        item = Item.objects.create(
            admission_id=admission.pk,
            item_type_id=item_type.pk,
            description="",
            status="active",
            version=1,
        )
        Revision.objects.create(
            item_id=item.pk,
            version=1,
            action="created",
            item_type_id=item_type.pk,
            type_name="Tomografia",
            category_name="Exames de imagem",
            category_slug="exames-imagem",
            type_slug="imagem-tomografia",
            profile="agendamento",
            has_rnm_complements=False,
            requires_description=False,
            description="",
            status="active",
            author_id=author.pk,
            author_name=author.get_username(),
        )

        _migrate(_leaf_node())

        current = PendingItem.objects.get(pk=item.pk)
        updated, changed = update_pending_item(
            item=current,
            item_type=current.item_type,
            description="",
            details={"is_scheduled": True},
            author=author,
            expected_version=1,
        )
        assert changed is True
        assert updated.version == 2
        assert updated.is_scheduled is True
        assert updated.scheduled_date is None
        previous = PendingItemRevision.objects.get(item=current, version=1)
        assert previous.is_scheduled is None
        assert previous.profile == "agendamento"
        assert (
            PendingItemRevision.objects.get(item=current, version=2).is_scheduled
            is True
        )
